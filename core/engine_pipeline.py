from __future__ import annotations

import bisect
import io
import json
import posixpath
import re
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urljoin, urlparse

import numpy as np
import requests
from bs4 import BeautifulSoup
from PIL import Image

try:
    import piexif
except ModuleNotFoundError:  # pragma: no cover - dependency availability check
    piexif = None

from core.default_camera_meta import defaults_for_record


# Metashape-friendly fallback camera EXIF when LBL does not expose calibration fields.
DEFAULT_FOCAL_LENGTH_MM = 34.0
DEFAULT_FOCAL_PLANE_RESOLUTION = 1351.3513513513512
MASTCAM_BAYER_APPLY_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "mastcam_bayer_apply_config.json"
MASTCAM_BAYER_PROCESS_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "mastcam_bayer_config.json"
_MASTCAM_APPLY_RULES_CACHE: Optional[dict[str, Any]] = None
_MASTCAM_PIPELINE_CACHE: Any = None
_MASTCAM_PIPELINE_CACHE_KEY: Optional[str] = None

from core.mastcam_bayer_cli import MastcamBayerPipeline, MastcamConfig

from core.metashape_engine import (
    EngineResult,
    MatchInfo,
    PdsProduct,
    _utc_now_iso,
    build_meta_payload,
    build_product_from_lbl,
    derive_output_paths,
    load_rover_csv,
    match_rover_row,
    write_meta_json,
)


# ============================================================
# Network and filesystem helpers
# ============================================================

def _ensure_parent_dir(path: str | Path) -> None:
    """
    Ensures that the parent directory of a file path exists.

    This helper is used before writing local cache files such as:
    - rover CSV cache
    - output JPG
    - output meta.json
    - catalog JSON
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def _session_with_retries() -> requests.Session:
    """
    Creates a plain requests session.

    This is intentionally kept simple for now.
    If needed later, retry adapters can be added here centrally.
    """
    session = requests.Session()
    try:
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        try:
            retry = Retry(
                total=3,
                connect=3,
                read=3,
                status=3,
                backoff_factor=0.3,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset({"HEAD", "GET"}),
                raise_on_status=False,
                respect_retry_after_header=True,
            )
        except TypeError:
            # Older urllib3 uses method_whitelist instead of allowed_methods.
            retry = Retry(
                total=3,
                connect=3,
                read=3,
                status=3,
                backoff_factor=0.3,
                status_forcelist=(429, 500, 502, 503, 504),
                method_whitelist=frozenset({"HEAD", "GET"}),  # type: ignore[call-arg]
                raise_on_status=False,
                respect_retry_after_header=True,
            )

        adapter = HTTPAdapter(max_retries=retry, pool_connections=32, pool_maxsize=32)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
    except Exception:
        # If retry setup fails for any reason, keep a plain session.
        pass
    return session


def _load_json_file(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(default)
    return parsed if isinstance(parsed, dict) else dict(default)


def _load_mastcam_apply_rules() -> dict[str, Any]:
    global _MASTCAM_APPLY_RULES_CACHE
    if _MASTCAM_APPLY_RULES_CACHE is None:
        _MASTCAM_APPLY_RULES_CACHE = _load_json_file(
            MASTCAM_BAYER_APPLY_CONFIG_PATH,
            {
                "enabled": False,
                "match": {
                    "product_ids": [],
                    "product_id_prefixes": [],
                    "instrument_ids": [],
                },
            },
        )
    return _MASTCAM_APPLY_RULES_CACHE


def _get_mastcam_pipeline() -> MastcamBayerPipeline:
    global _MASTCAM_PIPELINE_CACHE, _MASTCAM_PIPELINE_CACHE_KEY
    cfg_raw = _load_json_file(MASTCAM_BAYER_PROCESS_CONFIG_PATH, {})
    key = json.dumps(cfg_raw, sort_keys=True)
    if _MASTCAM_PIPELINE_CACHE is not None and _MASTCAM_PIPELINE_CACHE_KEY == key:
        return _MASTCAM_PIPELINE_CACHE

    base = MastcamConfig()
    cfg = MastcamConfig(
        best_pattern=str(cfg_raw.get("best_pattern", base.best_pattern)).upper(),
        final_sigma=float(cfg_raw.get("final_sigma", base.final_sigma)),
        wb_strength=float(cfg_raw.get("wb_strength", base.wb_strength)),
        flat_threshold=float(cfg_raw.get("flat_threshold", base.flat_threshold)),
        chroma_sigma=float(cfg_raw.get("chroma_sigma", base.chroma_sigma)),
        chroma_blend=float(cfg_raw.get("chroma_blend", base.chroma_blend)),
        color_replace_sigma=float(cfg_raw.get("color_replace_sigma", base.color_replace_sigma)),
        green_neutralize=float(cfg_raw.get("green_neutralize", base.green_neutralize)),
        clahe_clip=float(cfg_raw.get("clahe_clip", base.clahe_clip)),
        clahe_grid=tuple(cfg_raw.get("clahe_grid", list(base.clahe_grid))),  # type: ignore[arg-type]
        gamma=float(cfg_raw.get("gamma", base.gamma)),
        debayer_profile=str(cfg_raw.get("debayer_profile", base.debayer_profile)).lower(),
        superpixel_upscale=bool(cfg_raw.get("superpixel_upscale", base.superpixel_upscale)),
    )
    if cfg.best_pattern not in {"RGGB", "BGGR", "GRBG", "GBRG"}:
        cfg.best_pattern = base.best_pattern
    if cfg.debayer_profile not in {"auto", "ea", "std", "bggr_ea_hard", "superpixel", "superpixel_mean"}:
        cfg.debayer_profile = base.debayer_profile
    if not isinstance(cfg.clahe_grid, tuple) or len(cfg.clahe_grid) != 2:
        cfg.clahe_grid = base.clahe_grid

    _MASTCAM_PIPELINE_CACHE = MastcamBayerPipeline(cfg)
    _MASTCAM_PIPELINE_CACHE_KEY = key
    return _MASTCAM_PIPELINE_CACHE


def _matches_mastcam_apply_rule(product: Optional[PdsProduct]) -> tuple[bool, str]:
    rules = _load_mastcam_apply_rules()
    if not bool(rules.get("enabled", False)):
        return False, "disabled"
    if product is None:
        return False, "missing_product"

    match_cfg = rules.get("match", {})
    if not isinstance(match_cfg, dict):
        return False, "invalid_match_config"

    ids = {str(x).strip().upper() for x in (match_cfg.get("product_ids") or []) if str(x).strip()}
    prefixes = {str(x).strip().upper() for x in (match_cfg.get("product_id_prefixes") or []) if str(x).strip()}
    instruments = {str(x).strip().upper() for x in (match_cfg.get("instrument_ids") or []) if str(x).strip()}
    if not ids and not prefixes and not instruments:
        return False, "no_match_rules"

    pid = str(product.product_id or "").strip().upper()
    inst = str(product.instrument_id or "").strip().upper()

    if pid and pid in ids:
        return True, "product_id"
    if pid and any(pid.startswith(p) for p in prefixes):
        return True, "product_id_prefix"
    if inst and inst in instruments:
        return True, "instrument_id"
    return False, "no_rule_matched"


def fetch_text(
    url: str,
    timeout: int = 60,
    session: Optional[requests.Session] = None,
) -> str:
    """
    Downloads a remote text resource and returns it as a UTF-8 string.

    This is used for:
    - LBL files
    - HTML directory listings

    Raises:
    - requests.HTTPError if the request fails
    """
    own_session = session is None
    session = session or _session_with_retries()

    try:
        response = session.get(url, timeout=timeout)
        response.raise_for_status()
        response.encoding = response.encoding or "utf-8"
        return response.text
    finally:
        if own_session:
            session.close()


def fetch_bytes(
    url: str,
    timeout: int = 120,
    session: Optional[requests.Session] = None,
) -> bytes:
    """
    Downloads a remote binary resource and returns it as bytes.

    This is used for:
    - IMG files
    - any future binary asset fetched by the engine

    Raises:
    - requests.HTTPError if the request fails
    """
    own_session = session is None
    session = session or _session_with_retries()

    try:
        response = session.get(url, timeout=timeout)
        response.raise_for_status()
        return response.content
    finally:
        if own_session:
            session.close()


def download_file(
    url: str,
    output_path: str | Path,
    timeout: int = 120,
    session: Optional[requests.Session] = None,
) -> Path:
    """
    Downloads a remote file to a local path.

    This is used for persistent local cache files such as the rover CSV.

    Returns:
    - the local Path that was written
    """
    output_path = Path(output_path)
    _ensure_parent_dir(output_path)

    own_session = session is None
    session = session or _session_with_retries()

    try:
        response = session.get(url, timeout=timeout)
        response.raise_for_status()
        output_path.write_bytes(response.content)
        return output_path
    finally:
        if own_session:
            session.close()


# ============================================================
# Progress helpers
# ============================================================

def _emit_progress(
    progress_callback: Optional[Callable[[dict[str, Any]], None]],
    *,
    stage: str,
    message: str,
    current: Optional[int] = None,
    total: Optional[int] = None,
    product_id: Optional[str] = None,
    img_url: Optional[str] = None,
    lbl_url: Optional[str] = None,
    base_url: Optional[str] = None,
    record: Optional[dict[str, Any]] = None,
) -> None:
    """
    Emits a structured progress event to the optional callback.

    This keeps the engine UI-independent while allowing:
    - terminal progress messages
    - dashboard progress bars
    - future logging hooks
    """
    if progress_callback is None:
        return

    payload = {
        "stage": stage,
        "message": message,
        "current": current,
        "total": total,
        "product_id": product_id,
        "img_url": img_url,
        "lbl_url": lbl_url,
        "base_url": base_url,
        "record": record,
    }

    progress_callback(payload)


# ============================================================
# PDS catalog scanning
# ============================================================

def _is_directory_href(href: str) -> bool:
    """
    Returns True if an href looks like a directory entry.

    The JPL PDS directory listings typically expose directories with a
    trailing slash. This helper keeps the rule centralised.
    """
    return href.endswith("/")


def _is_img_href(href: str) -> bool:
    """
    Returns True only for IMG products that are intended to be processed.

    Current rule:
    - accept only DRCL IMG products
    - reject all other IMG variants

    This keeps the scanner conservative and avoids pulling products whose
    decoding path is not currently supported by the engine.
    """
    href_u = href.upper()
    return href_u.endswith("_DRCL.IMG")


def _lbl_from_img_href(href: str) -> str:
    """
    Converts an IMG href into the corresponding LBL href.

    Example:
    - 3419ML...IMG -> 3419ML...LBL
    """
    if href.upper().endswith(".IMG"):
        return href[:-4] + ".LBL"
    return href


def _normalise_url(url: str) -> str:
    """
    Normalises a URL string by removing duplicate slashes in the path
    while preserving scheme and host.
    """
    parsed = urlparse(url)
    normalised_path = posixpath.normpath(parsed.path)
    if parsed.path.endswith("/") and not normalised_path.endswith("/"):
        normalised_path += "/"
    return parsed._replace(path=normalised_path).geturl()


def _is_within_base_tree(url: str, base_root_url: str) -> bool:
    """
    Returns True only when `url` is under the same scheme/host/path tree of
    `base_root_url`.

    This prevents the recursive scanner from walking upward via links such as
    "Parent Directory", which in these indexes is often an absolute URL.
    """
    url_n = _normalise_url(url)
    base_n = _normalise_url(base_root_url)

    u = urlparse(url_n)
    b = urlparse(base_n)

    if u.scheme != b.scheme or u.netloc != b.netloc:
        return False

    base_path = b.path if b.path.endswith("/") else f"{b.path}/"
    return u.path.startswith(base_path)


def _extract_catalog_metadata(
    img_url: str,
    directory_url: str,
    *,
    img_size_human: Optional[str],
    img_size_bytes: Optional[int],
) -> dict[str, Any]:
    """
    Extracts lightweight metadata from URL/path naming conventions.

    This metadata is intended for pre-download filtering in a catalog UI.
    """
    product_id = Path(img_url).stem
    filename = Path(img_url).name

    parsed_dir = urlparse(directory_url)
    dir_name = Path(parsed_dir.path.rstrip("/")).name

    sol = None
    if dir_name.isdigit():
        sol = int(dir_name)
    else:
        m_sol = re.match(r"^SOL0*([0-9]+)$", dir_name, flags=re.IGNORECASE)
        if m_sol:
            sol = int(m_sol.group(1))

    instrument_code = None
    m_instrument = re.match(r"^\d{4}([A-Z]{2})", product_id)
    if m_instrument:
        instrument_code = m_instrument.group(1)

    product_class = None
    m_class = re.search(r"\d([CI])\d{2}_", product_id)
    if m_class:
        product_class = m_class.group(1)

    variant = None
    if "_" in product_id:
        tail = product_id.split("_", 1)[1]
        if tail:
            variant = tail

    return {
        "filename": filename,
        "sol": sol,
        "instrument_code": instrument_code,
        "product_class": product_class,
        "variant": variant,
        "img_size_human": img_size_human,
        "img_size_bytes": img_size_bytes,
    }


def _size_text_to_bytes(size_text: str) -> Optional[int]:
    """
    Converts Apache-style human-readable size strings (e.g. 162K, 1.7M) to bytes.
    Returns None when size is unknown/non-numeric.
    """
    s = (size_text or "").strip().upper()
    if not s or s == "-":
        return None

    m = re.match(r"^(\d+(?:\.\d+)?)([KMGTP]?)$", s)
    if not m:
        return None

    value = float(m.group(1))
    unit = m.group(2)
    factors = {
        "": 1,
        "K": 1024,
        "M": 1024 ** 2,
        "G": 1024 ** 3,
        "T": 1024 ** 4,
        "P": 1024 ** 5,
    }
    return int(round(value * factors[unit]))


def list_directory_links(
    base_url: str,
    session: Optional[requests.Session] = None,
) -> list[dict[str, Any]]:
    """
    Lists unique href entries found in an HTML directory page.

    Each entry includes:
    - href
    - size_human
    - size_bytes
    """
    html = fetch_text(base_url, session=session)
    soup = BeautifulSoup(html, "html.parser")

    hrefs: list[dict[str, Any]] = []
    seen: set[str] = set()

    for a in soup.select("table#indexlist a[href]"):
        href = str(a.get("href", "")).strip()
        if not href or href in {"../", "./"}:
            continue
        if href in seen:
            continue
        seen.add(href)

        size_human: Optional[str] = None
        size_bytes: Optional[int] = None

        tr = a.find_parent("tr")
        if tr is not None:
            size_cell = tr.find("td", class_="indexcolsize")
            if size_cell is not None:
                raw_size = size_cell.get_text(" ", strip=True)
                if raw_size and raw_size != "-":
                    size_human = raw_size
                    size_bytes = _size_text_to_bytes(raw_size)

        hrefs.append(
            {
                "href": href,
                "size_human": size_human,
                "size_bytes": size_bytes,
            }
        )

    return hrefs


def scan_pds_products_recursive(
    base_url: str,
    session: Optional[requests.Session] = None,
    progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
) -> list[dict[str, Any]]:
    """
    Recursively scans a PDS directory tree and returns IMG/LBL product pairs.

    Each returned record contains:
    - base_url
    - img_url
    - lbl_url

    Only IMG files are treated as primary products. The corresponding LBL
    URL is inferred from the IMG filename.
    """
    base_url = _normalise_url(base_url)
    if not base_url.endswith("/"):
        base_url = f"{base_url}/"

    own_session = session is None
    session = session or _session_with_retries()

    products: list[dict[str, Any]] = []
    visited_dirs: set[str] = set()
    seen_product_urls: set[str] = set()

    def _walk(url: str) -> None:
        url = _normalise_url(url)

        if not _is_within_base_tree(url, base_url):
            _emit_progress(
                progress_callback,
                stage="scan_skip_outside_base",
                message=f"Skipping outside-base directory link: {url}",
                base_url=url,
            )
            return

        if url in visited_dirs:
            return
        visited_dirs.add(url)

        _emit_progress(
            progress_callback,
            stage="scan_directory",
            message=f"Scanning directory: {url}",
            base_url=url,
        )

        hrefs = list_directory_links(url, session=session)

        for entry in hrefs:
            href = str(entry.get("href", "")).strip()
            if not href:
                continue
            if href.startswith(("?", "#", "mailto:", "javascript:")):
                continue

            full_url = _normalise_url(urljoin(url, href))

            if _is_directory_href(href):
                if not _is_within_base_tree(full_url, base_url):
                    continue
                _walk(full_url)
                continue

            if _is_img_href(href):
                if not _is_within_base_tree(full_url, base_url):
                    continue
                if full_url in seen_product_urls:
                    continue

                seen_product_urls.add(full_url)

                record = {
                    "base_url": url,
                    "img_url": full_url,
                    "lbl_url": _normalise_url(urljoin(url, _lbl_from_img_href(href))),
                }
                record.update(
                    _extract_catalog_metadata(
                        record["img_url"],
                        url,
                        img_size_human=entry.get("size_human"),
                        img_size_bytes=entry.get("size_bytes"),
                    )
                )
                products.append(record)

                _emit_progress(
                    progress_callback,
                    stage="scan_found_product",
                    message=f"Found product: {full_url}",
                    current=len(products),
                    product_id=Path(full_url).stem,
                    img_url=record["img_url"],
                    lbl_url=record["lbl_url"],
                    base_url=url,
                    record=record,
                )

    try:
        _emit_progress(
            progress_callback,
            stage="scan_start",
            message=f"Starting recursive scan from: {base_url}",
            base_url=base_url,
        )

        _walk(base_url)

        _emit_progress(
            progress_callback,
            stage="scan_done",
            message=f"Scan completed. Found {len(products)} products.",
            current=len(products),
            total=len(products),
            base_url=base_url,
        )

        return products
    finally:
        if own_session:
            session.close()


def scan_pds_products_in_directory(
    base_url: str,
    session: Optional[requests.Session] = None,
    progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
) -> list[dict[str, Any]]:
    """
    Scans a single directory page (non-recursive) and returns IMG/LBL pairs.

    This is faster than recursive scanning when caller already knows the exact
    SOL directory to inspect.
    """
    base_url = _normalise_url(base_url)
    if not base_url.endswith("/"):
        base_url = f"{base_url}/"

    own_session = session is None
    session = session or _session_with_retries()

    products: list[dict[str, Any]] = []
    seen_product_urls: set[str] = set()

    try:
        _emit_progress(
            progress_callback,
            stage="scan_directory",
            message=f"Scanning directory: {base_url}",
            base_url=base_url,
        )

        hrefs = list_directory_links(base_url, session=session)
        for entry in hrefs:
            href = str(entry.get("href", "")).strip()
            if not href:
                continue
            if href.startswith(("?", "#", "mailto:", "javascript:")):
                continue
            if not _is_img_href(href):
                continue

            full_url = _normalise_url(urljoin(base_url, href))
            if full_url in seen_product_urls:
                continue
            seen_product_urls.add(full_url)

            record = {
                "base_url": base_url,
                "img_url": full_url,
                "lbl_url": _normalise_url(urljoin(base_url, _lbl_from_img_href(href))),
            }
            record.update(
                _extract_catalog_metadata(
                    record["img_url"],
                    base_url,
                    img_size_human=entry.get("size_human"),
                    img_size_bytes=entry.get("size_bytes"),
                )
            )
            products.append(record)

            _emit_progress(
                progress_callback,
                stage="scan_found_product",
                message=f"Found product: {full_url}",
                current=len(products),
                product_id=Path(full_url).stem,
                img_url=record["img_url"],
                lbl_url=record["lbl_url"],
                base_url=base_url,
                record=record,
            )

        _emit_progress(
            progress_callback,
            stage="scan_done",
            message=f"Scan completed. Found {len(products)} products in directory.",
            current=len(products),
            total=len(products),
            base_url=base_url,
        )
        return products
    finally:
        if own_session:
            session.close()


def build_global_catalog_for_sol(
    *,
    sol: int,
    include_surface: bool = True,
    include_navcam_mosaic: bool = True,
    session: Optional[requests.Session] = None,
    progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
) -> list[dict[str, Any]]:
    """
    Builds a combined catalog for one SOL from multiple data sources.

    Current supported sources:
    - SURFACE RDR
    - NAVCAM MOSAIC
    """
    source_urls: list[tuple[str, str]] = []

    if include_surface:
        source_urls.append(
            (
                "surface_rdr",
                f"https://planetarydata.jpl.nasa.gov/img/data/msl/MSLMST_0030/DATA/RDR/SURFACE/{sol}/",
            )
        )
    if include_navcam_mosaic:
        source_urls.append(
            (
                "navcam_mosaic",
                f"https://planetarydata.jpl.nasa.gov/img/data/msl/msl_navcam_mosaic/DATA/SOL{sol:05d}/",
            )
        )

    own_session = session is None
    session = session or _session_with_retries()

    global_catalog: list[dict[str, Any]] = []
    seen_img_urls: set[str] = set()

    try:
        for source_key, url in source_urls:
            _emit_progress(
                progress_callback,
                stage="global_scan_source_start",
                message=f"Scanning source '{source_key}'",
                base_url=url,
            )

            try:
                records = scan_pds_products_in_directory(
                    url,
                    session=session,
                    progress_callback=progress_callback,
                )
            except Exception as exc:
                _emit_progress(
                    progress_callback,
                    stage="global_scan_source_error",
                    message=f"Source '{source_key}' failed: {exc}",
                    base_url=url,
                )
                continue

            added = 0
            for r in records:
                img_url = str(r.get("img_url", ""))
                if not img_url or img_url in seen_img_urls:
                    continue
                seen_img_urls.add(img_url)
                rr = dict(r)
                rr["source"] = source_key
                global_catalog.append(rr)
                added += 1

            _emit_progress(
                progress_callback,
                stage="global_scan_source_done",
                message=f"Source '{source_key}': +{added} items",
                current=len(global_catalog),
                total=None,
                base_url=url,
            )

        _emit_progress(
            progress_callback,
            stage="global_scan_done",
            message=f"Global catalog built: {len(global_catalog)} items",
            current=len(global_catalog),
            total=len(global_catalog),
        )
        return global_catalog
    finally:
        if own_session:
            session.close()


# ============================================================
# Rover CSV cache management
# ============================================================

_ROVER_CSV_ROWS_CACHE: Optional[list[dict[str, Any]]] = None
_ROVER_CSV_ROVER_ROWS_CACHE: Optional[list[dict[str, Any]]] = None
_ROVER_CSV_INDEX_CACHE: Optional[dict[str, Any]] = None
_ROVER_CSV_CACHE_KEY: str = ""


def _build_rover_rows_index(rover_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Build in-memory indexes to make per-product rover matching fast.

    The naive matcher scans the whole rover_rows list multiple times per image.
    For large CSVs this dominates runtime.
    """
    by_sdp: dict[tuple[Any, Any, Any], list[dict[str, Any]]] = {}
    by_sd: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
    by_sol: dict[Any, list[dict[str, Any]]] = {}
    by_sd_sclk_vals: dict[tuple[Any, Any], list[float]] = {}
    by_sd_sclk_rows: dict[tuple[Any, Any], list[dict[str, Any]]] = {}

    for r in rover_rows:
        site = r.get("site")
        drive = r.get("drive")
        pose = r.get("pose")
        sol = r.get("sol")

        if site is not None and drive is not None and pose is not None:
            by_sdp.setdefault((site, drive, pose), []).append(r)

        if site is not None and drive is not None:
            sd_key = (site, drive)
            by_sd.setdefault(sd_key, []).append(r)
            sclk = r.get("sclk")
            if sclk is not None:
                try:
                    sclk_f = float(sclk)
                except Exception:
                    sclk_f = None
                if sclk_f is not None:
                    by_sd_sclk_vals.setdefault(sd_key, []).append(sclk_f)
                    by_sd_sclk_rows.setdefault(sd_key, []).append(r)

        if sol is not None:
            by_sol.setdefault(sol, []).append(r)

    for sd_key, vals in list(by_sd_sclk_vals.items()):
        rows = by_sd_sclk_rows.get(sd_key) or []
        if not vals or len(vals) != len(rows):
            by_sd_sclk_vals.pop(sd_key, None)
            by_sd_sclk_rows.pop(sd_key, None)
            continue
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        by_sd_sclk_vals[sd_key] = [vals[i] for i in order]
        by_sd_sclk_rows[sd_key] = [rows[i] for i in order]

    return {
        "by_sdp": by_sdp,
        "by_sd": by_sd,
        "by_sol": by_sol,
        "by_sd_sclk_vals": by_sd_sclk_vals,
        "by_sd_sclk_rows": by_sd_sclk_rows,
    }


def _load_rover_csv_cached(csv_path: str | Path) -> list[dict[str, Any]]:
    """
    Load rover CSV rows with an in-process cache.

    The rover localisation CSV is large; re-reading it for every product makes
    processing dramatically slower. Caching is safe because the file is
    immutable during a run (and we refresh it explicitly on demand).
    """
    global _ROVER_CSV_ROWS_CACHE, _ROVER_CSV_ROVER_ROWS_CACHE, _ROVER_CSV_INDEX_CACHE, _ROVER_CSV_CACHE_KEY
    p = Path(csv_path)
    try:
        st = p.stat()
        key = f"{str(p.resolve())}:{st.st_mtime:.6f}:{st.st_size}"
    except Exception:
        key = str(p)
    if _ROVER_CSV_ROWS_CACHE is not None and _ROVER_CSV_CACHE_KEY == key:
        return _ROVER_CSV_ROWS_CACHE
    rows = load_rover_csv(p)
    _ROVER_CSV_ROWS_CACHE = rows
    try:
        rover_rows = [r for r in rows if str(r.get("frame", "")).upper() == "ROVER"]
    except Exception:
        rover_rows = rows
    _ROVER_CSV_ROVER_ROWS_CACHE = rover_rows
    _ROVER_CSV_INDEX_CACHE = _build_rover_rows_index(rover_rows)
    _ROVER_CSV_CACHE_KEY = key
    return rows


def _match_rover_row_fast(product: PdsProduct) -> tuple[Optional[dict[str, Any]], MatchInfo]:
    idx = _ROVER_CSV_INDEX_CACHE
    if not isinstance(idx, dict):
        return None, MatchInfo(strategy="none", gps_found=False, csv_refreshed=False, csv_match_count=0, frame=None)

    by_sdp = idx.get("by_sdp") or {}
    by_sd = idx.get("by_sd") or {}
    by_sol = idx.get("by_sol") or {}
    by_sd_sclk_vals = idx.get("by_sd_sclk_vals") or {}
    by_sd_sclk_rows = idx.get("by_sd_sclk_rows") or {}

    # 1) site + drive + pose
    if product.site is not None and product.drive is not None and product.pose is not None:
        strong = by_sdp.get((product.site, product.drive, product.pose), [])
    else:
        strong = []
    if len(strong) == 1:
        r0 = strong[0]
        return r0, MatchInfo(strategy="site_drive_pose", gps_found=True, csv_refreshed=False, csv_match_count=1, frame=r0.get("frame"))
    if len(strong) > 1 and product.sol is not None:
        narrowed = [r for r in strong if r.get("sol") == product.sol]
        if len(narrowed) == 1:
            r0 = narrowed[0]
            return r0, MatchInfo(strategy="site_drive_pose+sol", gps_found=True, csv_refreshed=False, csv_match_count=1, frame=r0.get("frame"))

    # 2) site + drive
    if product.site is not None and product.drive is not None:
        mid = by_sd.get((product.site, product.drive), [])
    else:
        mid = []
    if len(mid) == 1:
        r0 = mid[0]
        return r0, MatchInfo(strategy="site_drive", gps_found=True, csv_refreshed=False, csv_match_count=1, frame=r0.get("frame"))
    if len(mid) > 1 and product.sol is not None:
        narrowed = [r for r in mid if r.get("sol") == product.sol]
        if len(narrowed) == 1:
            r0 = narrowed[0]
            return r0, MatchInfo(strategy="site_drive+sol", gps_found=True, csv_refreshed=False, csv_match_count=1, frame=r0.get("frame"))

    # 3) nearest sclk within same site + drive
    if product.sclk is not None and product.site is not None and product.drive is not None:
        try:
            sclk_f = float(product.sclk)
        except Exception:
            sclk_f = None
        if sclk_f is not None:
            key = (product.site, product.drive)
            vals = by_sd_sclk_vals.get(key) or []
            rows = by_sd_sclk_rows.get(key) or []
            if vals and len(vals) == len(rows):
                pos = bisect.bisect_left(vals, sclk_f)
                if pos <= 0:
                    best_i = 0
                elif pos >= len(vals):
                    best_i = len(vals) - 1
                else:
                    a = abs(vals[pos - 1] - sclk_f)
                    b = abs(vals[pos] - sclk_f)
                    best_i = (pos - 1) if a <= b else pos
                best = rows[int(best_i)]
                return best, MatchInfo(
                    strategy="site_drive+sclk_nearest",
                    gps_found=True,
                    csv_refreshed=False,
                    csv_match_count=len(vals),
                    frame=best.get("frame"),
                )

    # 4) unique sol match
    if product.sol is not None:
        weak = by_sol.get(product.sol, [])
        if len(weak) == 1:
            r0 = weak[0]
            return r0, MatchInfo(strategy="sol", gps_found=True, csv_refreshed=False, csv_match_count=1, frame=r0.get("frame"))

    return None, MatchInfo(strategy="none", gps_found=False, csv_refreshed=False, csv_match_count=0, frame=None)

def refresh_rover_csv(
    rover_csv_url: str,
    rover_csv_local_path: str | Path,
    session: Optional[requests.Session] = None,
) -> Path:
    """
    Forces a fresh download of the rover localisation CSV into local cache.

    This function is called:
    - explicitly by the dashboard if requested
    - automatically by the engine when a product cannot be matched
    """
    out = download_file(
        url=rover_csv_url,
        output_path=rover_csv_local_path,
        session=session,
    )
    # Invalidate cached rows (the file may have changed).
    global _ROVER_CSV_ROWS_CACHE, _ROVER_CSV_ROVER_ROWS_CACHE, _ROVER_CSV_INDEX_CACHE, _ROVER_CSV_CACHE_KEY
    _ROVER_CSV_ROWS_CACHE = None
    _ROVER_CSV_ROVER_ROWS_CACHE = None
    _ROVER_CSV_INDEX_CACHE = None
    _ROVER_CSV_CACHE_KEY = ""
    return out


def ensure_rover_csv(
    rover_csv_url: str,
    rover_csv_local_path: str | Path,
    session: Optional[requests.Session] = None,
) -> Path:
    """
    Ensures that a local rover CSV cache file exists.

    If the file does not exist locally, it is downloaded once.
    If it already exists, it is left untouched.
    """
    rover_csv_local_path = Path(rover_csv_local_path)
    if rover_csv_local_path.exists():
        return rover_csv_local_path
    return refresh_rover_csv(rover_csv_url, rover_csv_local_path, session=session)


def match_rover_row_with_refresh(
    product: PdsProduct,
    rover_csv_url: str,
    rover_csv_local_path: str | Path,
    session: Optional[requests.Session] = None,
) -> tuple[Optional[dict[str, Any]], MatchInfo, list[dict[str, Any]]]:
    """
    Matches a rover CSV row for a product, refreshing the local CSV cache
    only if the first match attempt fails.

    Returns:
    - matched row or None
    - MatchInfo describing the final outcome
    - the loaded CSV rows used in the final attempt
    """
    rover_csv_local_path = ensure_rover_csv(
        rover_csv_url,
        rover_csv_local_path,
        session=session,
    )
    rows = _load_rover_csv_cached(rover_csv_local_path)

    row, info = _match_rover_row_fast(product)
    if row is not None:
        return row, info, rows

    refresh_rover_csv(rover_csv_url, rover_csv_local_path, session=session)
    # Refresh invalidates the cache; reload.
    rows = _load_rover_csv_cached(rover_csv_local_path)

    row, info = _match_rover_row_fast(product)
    info.csv_refreshed = True
    return row, info, rows


# ============================================================
# EXIF preparation helpers
# ============================================================

def build_minimal_metashape_exif_from_fields(
    *,
    focal_length_mm: Optional[float],
    focal_plane_x_resolution: Optional[float],
    focal_plane_y_resolution: Optional[float],
    focal_plane_resolution_unit: int = 3,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    altitude: Optional[float] = None,
) -> dict[str, Any]:
    """
    Builds a minimal EXIF description for Metashape.

    This function does not encode EXIF bytes yet.
    It returns a clean, serialisable description of the values that should
    be written into the JPG.

    Fields included:
    - FocalLength
    - FocalPlaneXResolution
    - FocalPlaneYResolution
    - FocalPlaneResolutionUnit
    - GPSLatitude
    - GPSLongitude
    - GPSAltitude

    Missing GPS values are simply omitted.
    """
    exif_written: dict[str, Any] = {}

    if focal_length_mm is not None:
        exif_written["FocalLength"] = focal_length_mm

    if focal_plane_x_resolution is not None:
        exif_written["FocalPlaneXResolution"] = focal_plane_x_resolution

    if focal_plane_y_resolution is not None:
        exif_written["FocalPlaneYResolution"] = focal_plane_y_resolution

    exif_written["FocalPlaneResolutionUnit"] = focal_plane_resolution_unit

    if latitude is not None:
        exif_written["GPSLatitude"] = latitude

    if longitude is not None:
        exif_written["GPSLongitude"] = longitude

    if altitude is not None:
        exif_written["GPSAltitude"] = altitude

    return exif_written


# ============================================================
# IMG decoding helpers
# ============================================================

def _lbl_get_int(lbl_text: str, key: str) -> Optional[int]:
    """
    Extracts an integer scalar value from a simple LBL field.

    Example:
    - LINES = 1024
    """
    m = re.search(rf"(?mi)^\s*{re.escape(key)}\s*=\s*([+-]?\d+)\s*$", lbl_text)
    if not m:
        return None

    try:
        return int(m.group(1))
    except Exception:
        return None


def _lbl_get_float(lbl_text: str, key: str) -> Optional[float]:
    """
    Extracts a float scalar value from a simple LBL field.

    Example:
    - FOCAL_LENGTH = 14.67
    """
    m = re.search(
        rf"(?mi)^\s*{re.escape(key)}\s*=\s*\"?([+-]?\d+(?:\.\d+)?)\"?(?:\s*<[^>]+>)?\s*$",
        lbl_text,
    )
    if not m:
        return None

    try:
        return float(m.group(1))
    except Exception:
        return None


def _lbl_get_string(lbl_text: str, key: str) -> Optional[str]:
    """
    Extracts a raw scalar string value from a simple LBL field.

    Handles both quoted and unquoted values.
    """
    m = re.search(rf"(?mi)^\s*{re.escape(key)}\s*=\s*(.+?)\s*$", lbl_text)
    if not m:
        return None

    value = m.group(1).strip()
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    return value


def _extract_object_block(lbl_text: str, object_name: str) -> Optional[str]:
    """
    Extracts the text block for a specific PDS OBJECT section.
    """
    pattern = (
        rf"(?mis)^\s*OBJECT\s*=\s*{re.escape(object_name)}\s*$"
        rf"(.*?)"
        rf"^\s*END_OBJECT\s*=\s*{re.escape(object_name)}\s*$"
    )
    m = re.search(pattern, lbl_text)
    if not m:
        return None
    return m.group(1)


def _lbl_get_int_image_first(lbl_text: str, key: str) -> Optional[int]:
    """
    Reads an integer key preferring OBJECT = IMAGE values when present.
    """
    image_block = _extract_object_block(lbl_text, "IMAGE")
    if image_block:
        value = _lbl_get_int(image_block, key)
        if value is not None:
            return value
    return _lbl_get_int(lbl_text, key)


def _lbl_get_string_image_first(lbl_text: str, key: str) -> Optional[str]:
    """
    Reads a string key preferring OBJECT = IMAGE values when present.
    """
    image_block = _extract_object_block(lbl_text, "IMAGE")
    if image_block:
        value = _lbl_get_string(image_block, key)
        if value is not None:
            return value
    return _lbl_get_string(lbl_text, key)


def _lbl_get_image_pointer_record(lbl_text: str) -> Optional[int]:
    """
    Parses ^IMAGE pointer as a record index when available.

    Supported forms:
    - ^IMAGE = 12
    - ^IMAGE = ("FILE.IMG", 12)
    """
    direct = _lbl_get_int(lbl_text, "^IMAGE")
    if direct is not None:
        return direct

    # Also support multiline tuple form, e.g.:
    # ^IMAGE = ("FILE.IMG",
    #           25)
    m = re.search(r"(?mis)^\s*\^IMAGE\s*=\s*\((.*?)\)", lbl_text)
    if not m:
        return None

    tuple_content = m.group(1)
    nums = re.findall(r"[+-]?\d+", tuple_content)
    if not nums:
        return None

    try:
        return int(nums[-1])
    except Exception:
        return None


def _extract_image_data_block(img_bytes: bytes, lbl_text: str) -> bytes:
    """
    Extracts the raw image block from an IMG file.

    PDS IMG files may contain a label or header area before the binary image
    block. This helper uses the ^IMAGE pointer when available and falls back
    to the full byte stream when no usable pointer is present.

    Current assumption:
    - record-based layout
    - ^IMAGE expressed as a record index
    """
    record_bytes = _lbl_get_int(lbl_text, "RECORD_BYTES")
    image_pointer = _lbl_get_image_pointer_record(lbl_text)

    if record_bytes and image_pointer and image_pointer > 0:
        offset = (image_pointer - 1) * record_bytes
        if 0 <= offset < len(img_bytes):
            return img_bytes[offset:]

    return img_bytes


def _decode_pds_image_array(img_bytes: bytes, lbl_text: str) -> np.ndarray:
    """
    Decodes the IMG image payload into a numpy array.

    Current supported cases:
    - SAMPLE_BITS = 8 or 16
    - SAMPLE_TYPE = UNSIGNED_INTEGER / SIGNED_INTEGER (MSB/LSB variants)
    - BANDS = 1 or 3 (for BANDS > 3, first band is used as grayscale fallback)
    - BAND_STORAGE_TYPE = BAND_SEQUENTIAL

    Output is returned as a numeric numpy array and later normalised to uint8
    before JPEG export.
    """
    lines = _lbl_get_int_image_first(lbl_text, "LINES")
    line_samples = _lbl_get_int_image_first(lbl_text, "LINE_SAMPLES")
    bands = _lbl_get_int_image_first(lbl_text, "BANDS") or 1
    sample_bits = _lbl_get_int_image_first(lbl_text, "SAMPLE_BITS")
    sample_type = (_lbl_get_string_image_first(lbl_text, "SAMPLE_TYPE") or "").strip().upper()
    band_storage_type = (
        _lbl_get_string_image_first(lbl_text, "BAND_STORAGE_TYPE") or "BAND_SEQUENTIAL"
    ).strip().upper()

    if not lines or not line_samples or not sample_bits:
        raise ValueError(
            "LBL is missing required image geometry fields: "
            "LINES, LINE_SAMPLES, SAMPLE_BITS"
        )

    if sample_bits not in {8, 16}:
        raise ValueError(f"Unsupported SAMPLE_BITS={sample_bits}")

    if band_storage_type != "BAND_SEQUENTIAL":
        raise ValueError(f"Unsupported BAND_STORAGE_TYPE={band_storage_type}")

    if bands < 1:
        raise ValueError(f"Unsupported BANDS={bands}")

    data = _extract_image_data_block(img_bytes, lbl_text)

    expected_count = lines * line_samples * bands
    dtype: Optional[np.dtype] = None
    if sample_bits == 8:
        if sample_type in {"UNSIGNED_INTEGER", "MSB_UNSIGNED_INTEGER", "LSB_UNSIGNED_INTEGER"}:
            dtype = np.dtype(np.uint8)
        elif sample_type in {"INTEGER", "MSB_INTEGER", "LSB_INTEGER", "SIGNED_INTEGER"}:
            dtype = np.dtype(np.int8)
    elif sample_bits == 16:
        if sample_type in {"UNSIGNED_INTEGER", "MSB_UNSIGNED_INTEGER"}:
            dtype = np.dtype(">u2")
        elif sample_type == "LSB_UNSIGNED_INTEGER":
            dtype = np.dtype("<u2")
        elif sample_type in {"INTEGER", "SIGNED_INTEGER", "MSB_INTEGER"}:
            dtype = np.dtype(">i2")
        elif sample_type == "LSB_INTEGER":
            dtype = np.dtype("<i2")

    if dtype is None:
        raise ValueError(f"Unsupported SAMPLE_TYPE={sample_type} for SAMPLE_BITS={sample_bits}")

    arr = np.frombuffer(data, dtype=dtype, count=expected_count)

    if arr.size < expected_count:
        raise ValueError(
            f"IMG payload shorter than expected. "
            f"Expected {expected_count} samples, found {arr.size}"
        )

    if bands == 1:
        return arr.reshape((lines, line_samples))

    arr = arr.reshape((bands, lines, line_samples))

    if bands == 3:
        arr = np.transpose(arr, (1, 2, 0))
        return arr

    # Fallback for uncommon multi-band products (e.g. BANDS=5):
    # keep pipeline resilient by exporting the first band as grayscale.
    return arr[0]


def _normalise_image_to_uint8(arr: np.ndarray) -> np.ndarray:
    """
    Normalises a decoded image array to uint8 for JPEG export.

    Behaviour:
    - if already uint8, returns it as-is
    - for non-uint8 arrays, applies robust percentile stretch (1..99)
      followed by a light gamma lift to preserve dark details.
    - for 2D arrays, works on full image
    - for 3D arrays, works independently per channel
    """
    if arr.dtype == np.uint8:
        return arr

    arr_float = arr.astype(np.float32, copy=False)

    def _scale_channel_u8(channel: np.ndarray) -> np.ndarray:
        finite = np.isfinite(channel)
        if not np.any(finite):
            return np.zeros(channel.shape, dtype=np.uint8)

        valid = channel[finite]
        # Robust stretch: avoids being dominated by spikes/outliers.
        p1 = float(np.percentile(valid, 1.0))
        p99 = float(np.percentile(valid, 99.0))

        if p99 <= p1:
            vmin = float(np.min(valid))
            vmax = float(np.max(valid))
            if vmax <= vmin:
                return np.zeros(channel.shape, dtype=np.uint8)
            p1, p99 = vmin, vmax

        clipped = np.clip(channel, p1, p99)
        scaled = (clipped - p1) / (p99 - p1)
        scaled = np.clip(scaled, 0.0, 1.0)

        # Slight lift for dark scenes.
        gamma = 0.85
        scaled = np.power(scaled, gamma)
        return np.clip(scaled * 255.0, 0, 255).astype(np.uint8)

    if arr.ndim == 2:
        return _scale_channel_u8(arr_float)

    if arr.ndim == 3:
        out = np.empty(arr.shape, dtype=np.uint8)

        for c in range(arr.shape[2]):
            out[:, :, c] = _scale_channel_u8(arr_float[:, :, c])

        return out

    raise ValueError(f"Unsupported decoded array ndim={arr.ndim}")


def _safe_float_from_row(row: Optional[dict[str, Any]], *keys: str) -> Optional[float]:
    """
    Reads the first available numeric value from a CSV row among candidate keys.

    This helper is intentionally tolerant because localisation CSV schemas
    may vary slightly across datasets or preparation steps.
    """
    if not row:
        return None

    for key in keys:
        value = row.get(key)
        if value is None or value == "":
            continue

        try:
            return float(value)
        except Exception:
            continue

    return None


def _to_rational(value: float, max_denominator: int = 1_000_000) -> tuple[int, int]:
    """
    Converts a float to an EXIF-compatible rational pair.

    EXIF stores many numeric fields as rational values represented by:
    - numerator
    - denominator
    """
    frac = Fraction(float(value)).limit_denominator(max_denominator)
    return frac.numerator, frac.denominator


def _decimal_degrees_to_dms_rational(
    value: float,
) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
    """
    Converts decimal degrees into EXIF GPS DMS rational tuples.

    EXIF GPS stores latitude and longitude as:
    - degrees
    - minutes
    - seconds

    Each component is stored as a rational pair.
    """
    absolute = abs(float(value))
    degrees = int(absolute)
    minutes_float = (absolute - degrees) * 60.0
    minutes = int(minutes_float)
    seconds = (minutes_float - minutes) * 60.0

    return (
        _to_rational(degrees, 1),
        _to_rational(minutes, 1),
        _to_rational(seconds),
    )


def _build_piexif_bytes_for_metashape(
    *,
    focal_length_mm: Optional[float],
    focal_plane_x_resolution: Optional[float],
    focal_plane_y_resolution: Optional[float],
    focal_plane_resolution_unit: int,
    latitude: Optional[float],
    longitude: Optional[float],
    altitude: Optional[float],
) -> bytes:
    """
    Builds EXIF bytes using piexif for Metashape-required tags.
    """
    if piexif is None:
        raise ModuleNotFoundError(
            "piexif is required to write EXIF tags in this decoder. "
            "Install it with: python -m pip install piexif"
        )
    exif_dict: dict[str, Any] = {
        "0th": {},
        "Exif": {},
        "GPS": {},
        "1st": {},
        "thumbnail": None,
    }

    if focal_length_mm is not None:
        exif_dict["Exif"][piexif.ExifIFD.FocalLength] = _to_rational(focal_length_mm)

    if focal_plane_x_resolution is not None:
        exif_dict["Exif"][piexif.ExifIFD.FocalPlaneXResolution] = _to_rational(
            focal_plane_x_resolution
        )

    if focal_plane_y_resolution is not None:
        exif_dict["Exif"][piexif.ExifIFD.FocalPlaneYResolution] = _to_rational(
            focal_plane_y_resolution
        )

    exif_dict["Exif"][piexif.ExifIFD.FocalPlaneResolutionUnit] = int(
        focal_plane_resolution_unit
    )

    if latitude is not None:
        exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] = b"N" if latitude >= 0 else b"S"
        exif_dict["GPS"][piexif.GPSIFD.GPSLatitude] = _decimal_degrees_to_dms_rational(
            latitude
        )

    if longitude is not None:
        exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef] = (
            b"E" if longitude >= 0 else b"W"
        )
        exif_dict["GPS"][piexif.GPSIFD.GPSLongitude] = _decimal_degrees_to_dms_rational(
            longitude
        )

    if altitude is not None:
        exif_dict["GPS"][piexif.GPSIFD.GPSAltitudeRef] = 0 if altitude >= 0 else 1
        exif_dict["GPS"][piexif.GPSIFD.GPSAltitude] = _to_rational(abs(altitude))

    return piexif.dump(exif_dict)


def _extract_camera_fields_from_lbl(
    lbl_text: str,
) -> tuple[Optional[float], Optional[float], Optional[float], int, Optional[int]]:
    """
    Derives the camera-related EXIF values from the LBL.

    Returns:
    - focal_length_mm
    - focal_plane_x_resolution
    - focal_plane_y_resolution
    - focal_plane_resolution_unit
    - focal_length_in_35mm_film

    Current behaviour:
    - reads FOCAL_LENGTH directly when available
    - derives focal plane resolution from pixel pitch when available
    - optionally derives a 35mm-equivalent focal length as a fallback
    """
    focal_length_mm = _lbl_get_float(lbl_text, "FOCAL_LENGTH")

    pixel_pitch_mm = (
        _lbl_get_float(lbl_text, "PIXEL_PITCH")
        or _lbl_get_float(lbl_text, "PIXEL_SIZE")
    )

    focal_plane_x_resolution = None
    focal_plane_y_resolution = None
    focal_plane_resolution_unit = 3  # 3 = centimetre in EXIF

    if pixel_pitch_mm and pixel_pitch_mm > 0:
        px_per_cm = 10.0 / pixel_pitch_mm
        focal_plane_x_resolution = px_per_cm
        focal_plane_y_resolution = px_per_cm

    focal_length_in_35mm_film = None

    if focal_length_mm and pixel_pitch_mm:
        line_samples = _lbl_get_int(lbl_text, "LINE_SAMPLES")
        lines = _lbl_get_int(lbl_text, "LINES")

        if line_samples and lines:
            sensor_width_mm = line_samples * pixel_pitch_mm
            sensor_height_mm = lines * pixel_pitch_mm
            sensor_diag_mm = (sensor_width_mm ** 2 + sensor_height_mm ** 2) ** 0.5

            if sensor_diag_mm > 0:
                full_frame_diag_mm = 43.266615305567875
                focal_length_in_35mm_film = int(
                    round(focal_length_mm * (full_frame_diag_mm / sensor_diag_mm))
                )

    return (
        focal_length_mm,
        focal_plane_x_resolution,
        focal_plane_y_resolution,
        focal_plane_resolution_unit,
        focal_length_in_35mm_film,
    )


def _extract_gps_fields_from_csv_row(
    csv_row: Optional[dict[str, Any]],
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Extracts GPS-related values from the matched rover CSV row.

    Returns:
    - latitude
    - longitude
    - altitude

    The helper accepts a few common key aliases to tolerate minor schema
    differences in the localisation table.
    """
    latitude = _safe_float_from_row(
        csv_row,
        "latitude",
        "lat",
        "planetocentric_latitude",
        "planetodetic_latitude",
    )
    longitude = _safe_float_from_row(csv_row, "longitude", "lon", "long")
    altitude = _safe_float_from_row(csv_row, "elevation", "elev", "altitude", "alt")

    return latitude, longitude, altitude


def _iso_to_exif_datetime(value: Optional[str]) -> Optional[str]:
    """
    Converts an ISO-8601 timestamp to EXIF DateTime format.
    """
    if not value:
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})", value.strip())
    if not m:
        return None
    return f"{m.group(1)}:{m.group(2)}:{m.group(3)} {m.group(4)}:{m.group(5)}:{m.group(6)}"


# ============================================================
# Decode adapter implementation
# ============================================================

def decode_img_bytes_to_jpg_bytes(
    img_bytes: bytes,
    lbl_text: str,
    csv_row: Optional[dict[str, Any]],
    product: Optional[PdsProduct] = None,
) -> tuple[bytes, dict[str, Any], dict[str, Any]]:
    """
    Converts IMG bytes into final JPG bytes and returns:
    - JPG bytes ready to be written to disk
    - a dictionary of EXIF fields actually written

    This implementation:
    1. decodes IMG in memory
    2. derives camera fields from LBL
    3. derives GPS fields from csv_row if available
    4. writes a minimal, clean EXIF block for Metashape
    5. returns final JPG bytes
    """
    decoded = _decode_pds_image_array(img_bytes, lbl_text)

    image_u8 = _normalise_image_to_uint8(decoded)

    processing_info: dict[str, Any] = {
        "mastcam_bayer_applied": False,
        "mastcam_bayer_reason": "not_evaluated",
        "mastcam_bayer_config_path": str(MASTCAM_BAYER_PROCESS_CONFIG_PATH),
        "mastcam_bayer_apply_rules_path": str(MASTCAM_BAYER_APPLY_CONFIG_PATH),
    }
    should_apply, reason = _matches_mastcam_apply_rule(product)
    processing_info["mastcam_bayer_reason"] = reason

    if image_u8.ndim == 2 and should_apply:
        pipe = _get_mastcam_pipeline()
        processed_rgb = pipe.process(image_u8)
        image = Image.fromarray(processed_rgb, mode="RGB")
        processing_info["mastcam_bayer_applied"] = True
        processing_info["mastcam_bayer_pattern"] = pipe.cfg.best_pattern
        processing_info["mastcam_bayer_profile"] = pipe.cfg.debayer_profile
    elif image_u8.ndim == 2:
        image = Image.fromarray(image_u8, mode="L")
    elif image_u8.ndim == 3 and image_u8.shape[2] == 3:
        image = Image.fromarray(image_u8, mode="RGB")
    else:
        raise ValueError(
            f"Unsupported decoded image shape for JPEG export: {image_u8.shape}"
        )

    (
        focal_length_mm,
        focal_plane_x_resolution,
        focal_plane_y_resolution,
        focal_plane_resolution_unit,
        focal_length_in_35mm_film,
    ) = _extract_camera_fields_from_lbl(lbl_text)

    # Ensure required Metashape camera EXIF tags are always present.
    # Prefer camera-scoped defaults when LBL has missing calibration fields.
    defaults: dict[str, Any] = {}
    if product is not None:
        defaults = defaults_for_record(
            camera=None,
            instrument_id=str(product.instrument_id or ""),
            product_id=str(product.product_id or ""),
        )

    if focal_length_mm is None:
        try:
            focal_length_mm = float(defaults.get("focal_length_mm")) if defaults.get("focal_length_mm") is not None else None
        except Exception:
            focal_length_mm = None
    if focal_plane_x_resolution is None or focal_plane_y_resolution is None:
        px_um = None
        try:
            px_um = float(defaults.get("pixel_size_um")) if defaults.get("pixel_size_um") is not None else None
        except Exception:
            px_um = None
        if px_um and px_um > 0:
            fp_res = 10000.0 / px_um  # pixels per cm (EXIF unit=centimetre)
            if focal_plane_x_resolution is None:
                focal_plane_x_resolution = fp_res
            if focal_plane_y_resolution is None:
                focal_plane_y_resolution = fp_res

    if focal_length_mm is None:
        focal_length_mm = DEFAULT_FOCAL_LENGTH_MM
    if focal_plane_x_resolution is None:
        focal_plane_x_resolution = DEFAULT_FOCAL_PLANE_RESOLUTION
    if focal_plane_y_resolution is None:
        focal_plane_y_resolution = DEFAULT_FOCAL_PLANE_RESOLUTION

    latitude, longitude, altitude = _extract_gps_fields_from_csv_row(csv_row)

    exif_written = build_minimal_metashape_exif_from_fields(
        focal_length_mm=focal_length_mm,
        focal_plane_x_resolution=focal_plane_x_resolution,
        focal_plane_y_resolution=focal_plane_y_resolution,
        focal_plane_resolution_unit=focal_plane_resolution_unit,
        latitude=latitude,
        longitude=longitude,
        altitude=altitude,
    )

    if focal_length_in_35mm_film is not None:
        exif_written["FocalLengthIn35mmFilm"] = focal_length_in_35mm_film

    exif_bytes = _build_piexif_bytes_for_metashape(
        focal_length_mm=focal_length_mm,
        focal_plane_x_resolution=focal_plane_x_resolution,
        focal_plane_y_resolution=focal_plane_y_resolution,
        focal_plane_resolution_unit=focal_plane_resolution_unit,
        latitude=latitude,
        longitude=longitude,
        altitude=altitude,
    )

    buffer = io.BytesIO()
    image.save(
        buffer,
        format="JPEG",
        quality=95,
        exif=exif_bytes,
        optimize=False,
    )

    return buffer.getvalue(), exif_written, processing_info


# ============================================================
# Single-product processing
# ============================================================

def process_single_product(
    *,
    img_url: str,
    lbl_url: Optional[str] = None,
    output_dir: str | Path,
    rover_csv_url: str,
    rover_csv_local_path: str | Path,
    base_url: Optional[str] = None,
    session: Optional[requests.Session] = None,
    engine_version: str = "0.1.0",
    progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
) -> EngineResult:
    """
    Processes a single IMG or LBL product into:
    - a clean Metashape-ready JPG
    - a rich .meta.json file for the dashboard

    Processing steps:
    1. fetch LBL text
    2. build product metadata
    3. match rover CSV row, with refresh-on-miss
    4. fetch IMG bytes
    5. decode IMG to JPG bytes in memory
    6. write JPG
    7. build and write .meta.json

    This function performs no UI logic and is intended to be used by the
    future dashboard engine layer.
    """
    warnings: list[str] = []
    errors: list[str] = []

    own_session = session is None
    session = session or _session_with_retries()
    fallback_product_id = Path(img_url).stem
    output_dir_p = Path(output_dir)

    try:
        _emit_progress(
            progress_callback,
            stage="download_lbl",
            message="Downloading LBL",
            product_id=fallback_product_id,
            img_url=img_url,
            lbl_url=lbl_url,
            base_url=base_url,
        )

        lbl_path = output_dir_p / Path(lbl_url).name if lbl_url else None
        if lbl_path is not None and lbl_path.exists() and lbl_path.stat().st_size > 0:
            _emit_progress(
                progress_callback,
                stage="download_lbl",
                message="Using local cached LBL",
                product_id=fallback_product_id,
                img_url=img_url,
                lbl_url=lbl_url,
                base_url=base_url,
            )
            lbl_text = lbl_path.read_text(encoding="utf-8", errors="ignore")
        else:
            lbl_text = fetch_text(lbl_url, session=session) if lbl_url else ""

        product = build_product_from_lbl(
            lbl_text,
            img_url=img_url,
            lbl_url=lbl_url or "",
            base_url=base_url,
        )

        _emit_progress(
            progress_callback,
            stage="product_parsed",
            message=f"Parsed product metadata: {product.product_id}",
            product_id=product.product_id,
            img_url=img_url,
            lbl_url=lbl_url,
            base_url=base_url,
        )

        output_jpg_path, output_meta_path = derive_output_paths(output_dir, product)

        _emit_progress(
            progress_callback,
            stage="match_csv",
            message=f"Matching rover localisation for: {product.product_id}",
            product_id=product.product_id,
            img_url=img_url,
            lbl_url=lbl_url,
            base_url=base_url,
        )

        csv_row, match_info, _rows = match_rover_row_with_refresh(
            product=product,
            rover_csv_url=rover_csv_url,
            rover_csv_local_path=rover_csv_local_path,
            session=session,
        )

        if csv_row is None:
            warnings.append(
                "No rover localisation row found. JPG will be created without GPS fields."
            )
            _emit_progress(
                progress_callback,
                stage="match_csv_missing",
                message=f"No rover localisation found for: {product.product_id}",
                product_id=product.product_id,
                img_url=img_url,
                lbl_url=lbl_url,
                base_url=base_url,
            )
        else:
            _emit_progress(
                progress_callback,
                stage="match_csv_done",
                message=f"Matched rover localisation for: {product.product_id}",
                product_id=product.product_id,
                img_url=img_url,
                lbl_url=lbl_url,
                base_url=base_url,
            )

        _emit_progress(
            progress_callback,
            stage="download_img",
            message=f"Downloading IMG for: {product.product_id}",
            product_id=product.product_id,
            img_url=img_url,
            lbl_url=lbl_url,
            base_url=base_url,
        )

        img_path = output_dir_p / Path(img_url).name if img_url else None
        if img_path is not None and img_path.exists() and img_path.stat().st_size > 0:
            _emit_progress(
                progress_callback,
                stage="download_img",
                message=f"Using local cached IMG for: {product.product_id}",
                product_id=product.product_id,
                img_url=img_url,
                lbl_url=lbl_url,
                base_url=base_url,
            )
            img_bytes = img_path.read_bytes()
        else:
            img_bytes = fetch_bytes(img_url, session=session)

        _emit_progress(
            progress_callback,
            stage="decode_img",
            message=f"Decoding IMG for: {product.product_id}",
            product_id=product.product_id,
            img_url=img_url,
            lbl_url=lbl_url,
            base_url=base_url,
        )

        jpg_bytes, exif_written, processing_info = decode_img_bytes_to_jpg_bytes(
            img_bytes=img_bytes,
            lbl_text=lbl_text,
            csv_row=csv_row,
            product=product,
        )

        _emit_progress(
            progress_callback,
            stage="write_jpg",
            message=f"Writing JPG for: {product.product_id}",
            product_id=product.product_id,
            img_url=img_url,
            lbl_url=lbl_url,
            base_url=base_url,
        )

        _ensure_parent_dir(output_jpg_path)
        Path(output_jpg_path).write_bytes(jpg_bytes)

        _emit_progress(
            progress_callback,
            stage="write_meta",
            message=f"Writing meta.json for: {product.product_id}",
            product_id=product.product_id,
            img_url=img_url,
            lbl_url=lbl_url,
            base_url=base_url,
        )

        meta_payload = build_meta_payload(
            product=product,
            lbl_text=lbl_text,
            csv_row=csv_row,
            match_info=match_info,
            img_url=img_url,
            lbl_url=lbl_url,
            rover_csv_url=rover_csv_url,
            rover_csv_local_path=str(rover_csv_local_path),
            output_jpg=str(output_jpg_path),
            output_meta_json=str(output_meta_path),
            exif_written=exif_written,
            warnings=warnings,
            errors=errors,
            engine_version=engine_version,
        )
        meta_payload["post_processing"] = processing_info
        write_meta_json(meta_payload, output_meta_path)

        status = "ok" if csv_row is not None else "ok_with_missing_gps"

        _emit_progress(
            progress_callback,
            stage="done",
            message=f"Completed product: {product.product_id}",
            product_id=product.product_id,
            img_url=img_url,
            lbl_url=lbl_url,
            base_url=base_url,
        )

        return EngineResult(
            product=product,
            output_jpg=str(output_jpg_path),
            output_meta_json=str(output_meta_path),
            match_info=match_info,
            csv_row=csv_row,
            exif_written=exif_written,
            warnings=warnings,
            errors=errors,
            status=status,
        )

    except Exception as exc:
        fallback_product = PdsProduct(
            product_id=fallback_product_id,
            image_id=None,
            instrument_id=None,
            instrument_name=None,
            sol=None,
            site=None,
            drive=None,
            pose=None,
            sclk=None,
            start_time=None,
            image_time=None,
            img_url=img_url,
            lbl_url=lbl_url,
            base_url=base_url,
        )

        output_jpg_path, output_meta_path = derive_output_paths(output_dir, fallback_product)

        errors.append(str(exc))

        _emit_progress(
            progress_callback,
            stage="error",
            message=f"Failed product: {fallback_product_id} | {exc}",
            product_id=fallback_product_id,
            img_url=img_url,
            lbl_url=lbl_url,
            base_url=base_url,
        )

        meta_payload = {
            "product": {
                "product_id": fallback_product.product_id,
                "image_id": fallback_product.image_id,
                "instrument_id": fallback_product.instrument_id,
                "instrument_name": fallback_product.instrument_name,
                "sol": fallback_product.sol,
                "site": fallback_product.site,
                "drive": fallback_product.drive,
                "pose": fallback_product.pose,
                "sclk": fallback_product.sclk,
                "start_time": fallback_product.start_time,
                "image_time": fallback_product.image_time,
                "img_url": fallback_product.img_url,
                "lbl_url": fallback_product.lbl_url,
                "base_url": fallback_product.base_url,
            },
            "sources": {
                "base_url": base_url,
                "img_url": img_url,
                "lbl_url": lbl_url,
                "rover_csv_url": rover_csv_url,
                "rover_csv_local_path": str(rover_csv_local_path),
            },
            "outputs": {
                "jpg_path": str(output_jpg_path),
                "meta_json_path": str(output_meta_path),
            },
            "matching": {
                "strategy": "none",
                "gps_found": False,
                "csv_refreshed": False,
                "csv_match_count": 0,
                "frame": None,
            },
            "csv_row": None,
            "exif_written": {},
            "lbl_parsed": None,
            "lbl_fields": None,
            "lbl_raw": None,
            "provenance": {
                "engine_version": engine_version,
                "built_at_utc": _utc_now_iso(),
            },
            "warnings": warnings,
            "errors": errors,
        }
        write_meta_json(meta_payload, output_meta_path)

        return EngineResult(
            product=fallback_product,
            output_jpg=str(output_jpg_path),
            output_meta_json=str(output_meta_path),
            match_info=MatchInfo(
                strategy="none",
                gps_found=False,
                csv_refreshed=False,
                csv_match_count=0,
                frame=None,
            ),
            csv_row=None,
            exif_written={},
            warnings=warnings,
            errors=errors,
            status="error",
        )

    finally:
        if own_session:
            session.close()


# ============================================================
# Batch processing
# ============================================================

def process_products_from_catalog(
    *,
    catalog: list[dict[str, Any]],
    output_dir: str | Path,
    rover_csv_url: str,
    rover_csv_local_path: str | Path,
    engine_version: str = "0.1.0",
    progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
) -> list[EngineResult]:
    """
    Processes a list of catalog product records.

    Each catalog record is expected to contain:
    - img_url
    - lbl_url
    - base_url

    Returns:
    - a list of EngineResult objects, one for each product
    """
    results: list[EngineResult] = []
    total = len(catalog)

    session = _session_with_retries()
    try:
        _emit_progress(
            progress_callback,
            stage="batch_start",
            message=f"Starting batch processing of {total} products",
            current=0,
            total=total,
        )

        for idx, record in enumerate(catalog, start=1):
            _emit_progress(
                progress_callback,
                stage="batch_progress",
                message=f"Processing product {idx} of {total}",
                current=idx,
                total=total,
                product_id=Path(record["img_url"]).stem if record.get("img_url") else None,
                img_url=record.get("img_url"),
                lbl_url=record.get("lbl_url"),
                base_url=record.get("base_url"),
            )

            result = process_single_product(
                img_url=record["img_url"],
                lbl_url=record.get("lbl_url"),
                base_url=record.get("base_url"),
                output_dir=output_dir,
                rover_csv_url=rover_csv_url,
                rover_csv_local_path=rover_csv_local_path,
                session=session,
                engine_version=engine_version,
                progress_callback=progress_callback,
            )
            results.append(result)

        _emit_progress(
            progress_callback,
            stage="batch_done",
            message=f"Batch completed: {total} products processed",
            current=total,
            total=total,
        )

        return results
    finally:
        session.close()


def process_products_from_base_url(
    *,
    base_url: str,
    output_dir: str | Path,
    rover_csv_url: str,
    rover_csv_local_path: str | Path,
    engine_version: str = "0.1.0",
    progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
) -> list[EngineResult]:
    """
    Scans a PDS base URL recursively, builds a catalog of IMG or LBL products,
    and processes all of them.

    This is the highest-level batch entry point of the current engine.
    It is the most natural function for the future dashboard to call when
    the user wants to process a whole directory tree.
    """
    session = _session_with_retries()
    try:
        catalog = scan_pds_products_recursive(
            base_url,
            session=session,
            progress_callback=progress_callback,
        )
    finally:
        session.close()

    return process_products_from_catalog(
        catalog=catalog,
        output_dir=output_dir,
        rover_csv_url=rover_csv_url,
        rover_csv_local_path=rover_csv_local_path,
        engine_version=engine_version,
        progress_callback=progress_callback,
    )


# ============================================================
# Catalog helpers
# ============================================================

def build_catalog_from_base_url(
    base_url: str,
    session: Optional[requests.Session] = None,
    progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
) -> list[dict[str, Any]]:
    """
    Builds an in-memory catalog of PDS products from a base URL.

    This is a thin wrapper around the recursive scanner and exists to make the
    intent explicit at the API level.

    Each catalog record contains:
    - base_url
    - img_url
    - lbl_url
    """
    return scan_pds_products_recursive(
        base_url,
        session=session,
        progress_callback=progress_callback,
    )


def write_catalog_json(
    catalog: list[dict[str, Any]],
    output_path: str | Path,
) -> Path:
    """
    Writes a catalog of PDS products to a JSON file.

    The catalog is written as a JSON array, one object per product.
    This is useful for:
    - debugging
    - previewing what will be processed
    - future dashboard ingestion
    - reproducible batch runs
    """
    output_path = Path(output_path)
    _ensure_parent_dir(output_path)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return output_path


def build_and_write_catalog_from_base_url(
    *,
    base_url: str,
    output_path: str | Path,
    progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
) -> Path:
    """
    Scans a PDS base URL recursively, builds the product catalog,
    and writes it to disk as JSON.

    This function is intentionally separate from product processing.
    It allows the caller to inspect or persist the download plan before
    launching the full pipeline.
    """
    _emit_progress(
        progress_callback,
        stage="catalog_start",
        message=f"Starting catalog build from: {base_url}",
        base_url=base_url,
    )

    session = _session_with_retries()
    try:
        catalog = build_catalog_from_base_url(
            base_url,
            session=session,
            progress_callback=progress_callback,
        )
    finally:
        session.close()

    out = write_catalog_json(catalog, output_path)

    _emit_progress(
        progress_callback,
        stage="catalog_written",
        message=f"Catalog written to: {out}",
        current=len(catalog),
        total=len(catalog),
        base_url=base_url,
    )

    return out
