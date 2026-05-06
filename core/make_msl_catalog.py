#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import select
import signal
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup, SoupStrainer

try:
    import termios
    import tty
except Exception:  # pragma: no cover
    termios = None  # type: ignore[assignment]
    tty = None  # type: ignore[assignment]

try:
    from core.metashape_engine import build_product_from_lbl
except Exception:  # pragma: no cover
    from metashape_engine import build_product_from_lbl  # type: ignore

PDS_MSL_BASE_URL = "https://planetarydata.jpl.nasa.gov/img/data/msl/"
DEFAULT_TIMEOUT = 30
DEFAULT_RETRIES = 3
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "msl_catalog_config.json"

CAMERA_CONFIG_DEFAULT = {
    "mastcam": {
        "collection_token": "MSLMST_",
        "data_roots": ["DATA/RDR/SURFACE/"],
    },
    "mahli": {
        "collection_token": "MSLMHL_",
        "data_roots": ["DATA/RDR/SURFACE/"],
    },
    "navcam": {
        "collection_token": "MSLNAV_1",
        "data_roots": ["DATA/", "DATA_V1/"],
    },
    "mardi": {
        "collection_token": "MSLMRD",
        "data_roots": ["DATA/RDR/SURFACE/"],
    },
    "hazcam": {
        "collection_token": "MSLHAZ_1",
        "data_roots": ["DATA/"],
    },
}

SOL_PATTERNS = [
    re.compile(r"^SOL(\d{4,5})/?$", re.IGNORECASE),
    re.compile(r"^(\d{4,5})/?$"),
]

STOP_EVENT = threading.Event()
PAUSE_EVENT = threading.Event()


@dataclass(frozen=True)
class SolLocation:
    collection: str
    data_root: str
    sol: int
    sol_dir_name: str
    sol_url: str


class PDSClient:
    def __init__(self, timeout: int, retries: int) -> None:
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "msl-catalog-builder/3.0 "
                    "(+incremental scanner with geo enrichment and checkpoints)"
                )
            }
        )

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.retries + 1):
            try:
                resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
                resp.raise_for_status()
                return resp
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < self.retries:
                    time.sleep(min(2 * attempt, 4))
                else:
                    break
        raise RuntimeError(f"HTTP {method} failed for {url}: {last_exc}")

    def get_text(self, url: str) -> str:
        return self._request("GET", url).text

    def get_bytes(self, url: str) -> bytes:
        return self._request("GET", url).content

    def head(self, url: str) -> requests.Response:
        return self._request("HEAD", url, allow_redirects=True)


def _emit(stage: str, message: str) -> None:
    print(f"[{stage}] {message}")


def _resolve_path(project_root: Path, value: str | None, fallback: str) -> Path:
    raw = value if value else fallback
    p = Path(raw).expanduser()
    if p.is_absolute():
        return p
    return (project_root / p).resolve()


def _parse_sol_dir_name(name: str) -> Optional[int]:
    clean = name.strip().rstrip("/")
    for pat in SOL_PATTERNS:
        m = pat.match(clean)
        if m:
            return int(m.group(1))
    return None


def _normalise_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path
    while "//" in path:
        path = path.replace("//", "/")
    return parsed._replace(path=path).geturl()


def _is_under_base(url: str, base: str) -> bool:
    u = urlparse(_normalise_url(url))
    b = urlparse(_normalise_url(base))
    if u.scheme != b.scheme or u.netloc != b.netloc:
        return False
    base_path = b.path if b.path.endswith("/") else f"{b.path}/"
    return u.path.startswith(base_path)


def _extract_links_with_sizes(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml", parse_only=SoupStrainer("a"))
    full = BeautifulSoup(html, "lxml")

    hrefs: list[dict[str, Any]] = []
    seen: set[str] = set()

    table = full.find("table", id="indexlist")
    if table is not None:
        for tr in table.find_all("tr"):
            a = tr.find("a", href=True)
            if not a:
                continue
            href = str(a.get("href", "")).strip()
            if not href or href in seen:
                continue
            seen.add(href)
            size_human = None
            size_bytes = None
            size_cell = tr.find("td", class_="indexcolsize")
            if size_cell is not None:
                raw = size_cell.get_text(" ", strip=True)
                if raw and raw != "-":
                    size_human = raw
                    size_bytes = _size_text_to_bytes(raw)
            hrefs.append({"href": href, "size_human": size_human, "size_bytes": size_bytes})
        return hrefs

    for a in soup.find_all("a", href=True):
        href = str(a.get("href", "")).strip()
        if not href or href in seen:
            continue
        seen.add(href)
        hrefs.append({"href": href, "size_human": None, "size_bytes": None})
    return hrefs


def _size_text_to_bytes(size_text: str) -> Optional[int]:
    s = (size_text or "").strip().upper()
    if not s or s == "-":
        return None
    m = re.match(r"^(\d+(?:\.\d+)?)([KMGTP]?)$", s)
    if not m:
        return None
    value = float(m.group(1))
    unit = m.group(2)
    mul = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4, "P": 1024**5}[unit]
    return int(round(value * mul))


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _camera_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    raw = cfg.get("camera_config")
    if isinstance(raw, dict) and raw:
        return raw
    return CAMERA_CONFIG_DEFAULT


def discover_collections_for_camera(client: PDSClient, base_url: str, token: str) -> list[str]:
    html = client.get_text(base_url)
    items = _extract_links_with_sizes(html)
    out: list[str] = []
    for item in items:
        href = str(item.get("href", "")).strip()
        if not href.endswith("/"):
            continue
        if href in {"../", "./", "/"}:
            continue
        if token in href:
            out.append(href)
    return sorted(set(out))


def discover_sol_locations(client: PDSClient, base_url: str, collection: str, data_roots: Iterable[str]) -> list[SolLocation]:
    out: list[SolLocation] = []
    for data_root in data_roots:
        data_url = urljoin(base_url, f"{collection}{data_root}")
        try:
            html = client.get_text(data_url)
        except Exception:
            continue
        for item in _extract_links_with_sizes(html):
            href = str(item.get("href", "")).strip()
            if not href.endswith("/"):
                continue
            if href in {"../", "./", "/"}:
                continue
            sol = _parse_sol_dir_name(href)
            if sol is None:
                continue
            out.append(
                SolLocation(
                    collection=collection.rstrip("/"),
                    data_root=data_root.rstrip("/"),
                    sol=sol,
                    sol_dir_name=href.rstrip("/"),
                    sol_url=urljoin(data_url, href),
                )
            )
    return out


def scan_products_in_sol(client: PDSClient, loc: SolLocation, base_url: str) -> list[dict[str, Any]]:
    if STOP_EVENT.is_set():
        return []

    while PAUSE_EVENT.is_set() and not STOP_EVENT.is_set():
        time.sleep(0.15)

    try:
        html = client.get_text(loc.sol_url)
    except Exception as exc:  # noqa: BLE001
        _emit("scan_sol_error", f"{loc.sol_url} | {exc}")
        return []

    products: list[dict[str, Any]] = []
    for entry in _extract_links_with_sizes(html):
        href = str(entry.get("href", "")).strip()
        if not href or href in {"../", "./", "/"}:
            continue
        if href.endswith("/"):
            full = _normalise_url(urljoin(loc.sol_url, href))
            if not _is_under_base(full, base_url):
                _emit("scan_skip_parent_or_external", f"Skipping parent/external directory: {full}")
            continue
        if not href.upper().endswith(".IMG"):
            continue

        full_img = _normalise_url(urljoin(loc.sol_url, href))
        if not _is_under_base(full_img, base_url):
            continue

        stem = Path(href).stem
        lbl_name = f"{stem}.LBL"
        rec = {
            "product_id": stem,
            "sol": loc.sol,
            "collection": loc.collection,
            "data_root": loc.data_root,
            "sol_dir_name": loc.sol_dir_name,
            "sol_url": loc.sol_url,
            "img_url": full_img,
            "lbl_url": _normalise_url(urljoin(loc.sol_url, lbl_name)),
            "img_name": Path(href).name,
            "lbl_name": lbl_name,
            "img_size_bytes": entry.get("size_bytes"),
            "image_id": None,
            "instrument_id": None,
            "instrument_name": None,
            "start_time": None,
            "image_time": None,
            "site": None,
            "drive": None,
            "pose": None,
            "sclk": None,
            "geo_match_strategy": None,
            "geo_found": False,
            "geo_parse_error": None,
            "record_complete": False,
            "geo_latitude": None,
            "geo_longitude": None,
            "geo_elevation": None,
            "geo_frame": None,
        }
        products.append(rec)
        _emit("scan_found_product", f"Found product: {full_img}")
    return products


def _family_key(product_id: str) -> str:
    if "_" in product_id:
        return product_id.rsplit("_", 1)[0]
    return product_id


def _select_lbl_candidates(products: list[dict[str, Any]], min_size_bytes: int) -> set[str]:
    grouped: dict[str, dict[str, Any]] = {}
    for p in products:
        size = p.get("img_size_bytes")
        if not isinstance(size, int):
            continue
        if size < min_size_bytes:
            continue
        key = _family_key(str(p.get("product_id", "")))
        prev = grouped.get(key)
        if prev is None or int(size) > int(prev.get("img_size_bytes") or -1):
            grouped[key] = p
    return {str(v.get("img_url")) for v in grouped.values() if v.get("img_url")}


def _load_geo_table(csv_path: Path) -> dict[tuple[int, int], dict[str, Any]]:
    table: dict[tuple[int, int], dict[str, Any]] = {}
    if not csv_path.exists():
        return table
    df = pd.read_csv(csv_path, low_memory=False)
    required = {"site", "drive", "planetocentric_latitude", "longitude", "elevation"}
    if not required.issubset(set(df.columns.tolist())):
        return table
    for row in df.to_dict(orient="records"):
        site = row.get("site")
        drive = row.get("drive")
        if site is None or drive is None:
            continue
        try:
            site_i = int(site)
            drive_i = int(drive)
        except Exception:
            continue
        table[(site_i, drive_i)] = row
    return table


def _enrich_with_lbl_and_geo(
    client: PDSClient,
    products: list[dict[str, Any]],
    candidates: set[str],
    geo_table: dict[tuple[int, int], dict[str, Any]],
) -> None:
    for p in products:
        if STOP_EVENT.is_set():
            return
        img_url = str(p.get("img_url", ""))
        if img_url not in candidates:
            p["geo_parse_error"] = "lbl_skipped_by_policy"
            continue

        lbl_url = str(p.get("lbl_url", ""))
        try:
            lbl_text = client.get_text(lbl_url)
            parsed = build_product_from_lbl(
                lbl_text=lbl_text,
                img_url=img_url,
                lbl_url=lbl_url,
                base_url=str(p.get("sol_url") or ""),
            )
            p["image_id"] = parsed.image_id
            p["instrument_id"] = parsed.instrument_id
            p["instrument_name"] = parsed.instrument_name
            p["start_time"] = parsed.start_time
            p["image_time"] = parsed.image_time
            p["site"] = parsed.site
            p["drive"] = parsed.drive
            p["pose"] = parsed.pose
            p["sclk"] = parsed.sclk

            if parsed.site is not None and parsed.drive is not None:
                row = geo_table.get((int(parsed.site), int(parsed.drive)))
                strategy = "site_drive"
                if row is None:
                    row = geo_table.get((int(parsed.site), -1))
                    strategy = "site_fallback_drive_minus_1"
                if row is not None:
                    p["geo_latitude"] = row.get("planetocentric_latitude")
                    p["geo_longitude"] = row.get("longitude")
                    p["geo_elevation"] = row.get("elevation")
                    p["geo_frame"] = row.get("frame")
                    p["geo_found"] = True
                    p["geo_match_strategy"] = strategy
                else:
                    p["geo_found"] = False
                    p["geo_match_strategy"] = "no_geo_row"
            p["record_complete"] = bool(p.get("geo_found"))
            p["geo_parse_error"] = None
        except Exception as exc:  # noqa: BLE001
            p["geo_parse_error"] = f"{type(exc).__name__}: {exc}"
            p["record_complete"] = False


def _build_fingerprint(base_url: str, cameras: list[str], sol_start: Optional[int], sol_end: Optional[int]) -> str:
    return json.dumps(
        {
            "base_url": base_url,
            "cameras": sorted(cameras),
            "sol_start": sol_start,
            "sol_end": sol_end,
        },
        sort_keys=True,
    )


def _ensure_geo_csv_and_parquet(
    client: PDSClient,
    project_root: Path,
    coord_url: str,
    coord_local_path: Path,
    coord_parquet_path: Path,
) -> tuple[bool, bool, str]:
    meta_path = coord_local_path.with_suffix(coord_local_path.suffix + ".meta.json")
    prev_meta = _load_json(meta_path, {}) if meta_path.exists() else {}

    coord_local_path.parent.mkdir(parents=True, exist_ok=True)
    coord_parquet_path.parent.mkdir(parents=True, exist_ok=True)

    remote_len = None
    remote_lastmod = None
    try:
        h = client.head(coord_url)
        remote_len = h.headers.get("Content-Length")
        remote_lastmod = h.headers.get("Last-Modified")
    except Exception:
        pass

    download_now = False
    updated_now = False
    reason = "unchanged"

    if not coord_local_path.exists():
        download_now = True
        reason = "missing_local"
    else:
        local_size = coord_local_path.stat().st_size
        if remote_len and str(local_size) != str(remote_len):
            download_now = True
            updated_now = True
            reason = "size_changed"
        elif remote_lastmod and prev_meta.get("remote_last_modified") != remote_lastmod:
            download_now = True
            updated_now = True
            reason = "last_modified_changed"

    if download_now:
        _emit("geo_csv_sync", f"Downloading geography CSV: {coord_url}")
        data = client.get_bytes(coord_url)
        coord_local_path.write_bytes(data)

    build_geo_parquet = (not coord_parquet_path.exists()) or download_now
    if build_geo_parquet:
        _emit("geo_parquet_build", "Converting geography CSV to parquet")
        df = pd.read_csv(coord_local_path, low_memory=False)
        df.to_parquet(coord_parquet_path, index=False)

    meta_payload = {
        "coord_url": coord_url,
        "local_path": str(coord_local_path),
        "remote_content_length": remote_len,
        "remote_last_modified": remote_lastmod,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(meta_path, meta_payload)

    return download_now, updated_now, reason


def _catalog_to_rows(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cameras = catalog.get("cameras", {})
    for camera, payload in cameras.items():
        for p in payload.get("products", []):
            row = dict(p)
            row["camera"] = camera
            rows.append(row)
    return rows


def _write_parquet(catalog: dict[str, Any], parquet_path: Path) -> int:
    rows = _catalog_to_rows(catalog)
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_parquet(parquet_path, index=False)
    return len(rows)


def _install_controls() -> None:
    def _on_sigint(signum: int, frame: Any) -> None:  # noqa: ARG001
        if not STOP_EVENT.is_set():
            _emit("interrupt_requested", "Ctrl+C ricevuto: stop richiesto, salvataggio in corso...")
            STOP_EVENT.set()

    signal.signal(signal.SIGINT, _on_sigint)

    if not sys.stdin.isatty() or os.name != "posix" or termios is None or tty is None:
        return

    def _monitor() -> None:
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while not STOP_EVENT.is_set():
                r, _, _ = select.select([fd], [], [], 0.1)
                if not r:
                    continue
                ch = os.read(fd, 1)
                if ch == b"\x10":  # Ctrl+P
                    if PAUSE_EVENT.is_set():
                        PAUSE_EVENT.clear()
                        _emit("pause", "Ripresa scansione")
                    else:
                        PAUSE_EVENT.set()
                        _emit("pause", "Scansione in pausa (Ctrl+P per riprendere)")
        except Exception:
            return
        finally:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
            except Exception:
                pass

    th = threading.Thread(target=_monitor, daemon=True)
    th.start()
    _emit("controls", "Controlli attivi: Ctrl+P pausa/riprendi, Ctrl+C salva+stop")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Build/update local MSL catalog with incremental checkpoints.")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Config JSON path")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--cameras", nargs="+", default=None)
    ap.add_argument("--output", default=None)
    ap.add_argument("--parquet-output", default=None)
    ap.add_argument("--coord-url", default=None)
    ap.add_argument("--coord-local-path", default=None)
    ap.add_argument("--coord-parquet-path", default=None)
    ap.add_argument("--timeout", type=int, default=None)
    ap.add_argument("--retries", type=int, default=None)
    ap.add_argument("--sol-start", type=int, default=None)
    ap.add_argument("--sol-end", type=int, default=None)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--min-img-size-bytes-for-lbl", type=int, default=None)
    ap.add_argument("--checkpoint-every-products", type=int, default=None)
    ap.add_argument("--checkpoint-write-parquet", action="store_true")
    ap.add_argument("--refresh-sol-index", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    return ap.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    _install_controls()

    cfg_path = Path(args.config).expanduser().resolve()
    cfg: dict[str, Any] = _load_json(cfg_path, {}) if cfg_path.exists() else {}

    project_root = Path(__file__).resolve().parent.parent

    base_url = args.base_url or cfg.get("base_url") or PDS_MSL_BASE_URL
    timeout = int(args.timeout if args.timeout is not None else cfg.get("timeout", DEFAULT_TIMEOUT))
    retries = int(args.retries if args.retries is not None else cfg.get("retries", DEFAULT_RETRIES))
    cameras = args.cameras or cfg.get("default_cameras") or list(_camera_cfg(cfg).keys())

    output_path = _resolve_path(project_root, args.output or cfg.get("output"), "data/catalog/catalog.json")
    parquet_output_path = _resolve_path(
        project_root,
        args.parquet_output or cfg.get("parquet_output"),
        "data/catalog/catalog.parquet",
    )

    coord_url = args.coord_url or cfg.get("coord_url")
    coord_local_path = _resolve_path(project_root, args.coord_local_path or cfg.get("coord_local_path"), "data/reference/geo/localized_interp_demv2.csv")
    coord_parquet_path = _resolve_path(project_root, args.coord_parquet_path or cfg.get("coord_parquet_path"), "data/reference/geo/localized_interp_demv2.parquet")

    sol_start = args.sol_start if args.sol_start is not None else cfg.get("sol_start")
    sol_end = args.sol_end if args.sol_end is not None else cfg.get("sol_end")
    min_img_size = int(
        args.min_img_size_bytes_for_lbl
        if args.min_img_size_bytes_for_lbl is not None
        else cfg.get("min_img_size_bytes_for_lbl", 0)
    )
    checkpoint_every = int(
        args.checkpoint_every_products
        if args.checkpoint_every_products is not None
        else cfg.get("checkpoint_every_products", 1000)
    )
    checkpoint_write_parquet = bool(args.checkpoint_write_parquet or cfg.get("checkpoint_write_parquet", False))

    cam_cfg = _camera_cfg(cfg)
    unknown = [c for c in cameras if c not in cam_cfg]
    if unknown:
        _emit("error", f"Unknown cameras requested: {unknown}. Allowed: {sorted(cam_cfg)}")
        return 1

    client = PDSClient(timeout=timeout, retries=retries)

    coord_downloaded_now = False
    coord_updated_now = False
    coord_sync_reason = "disabled"
    geo_table: dict[tuple[int, int], dict[str, Any]] = {}

    if coord_url:
        coord_downloaded_now, coord_updated_now, coord_sync_reason = _ensure_geo_csv_and_parquet(
            client=client,
            project_root=project_root,
            coord_url=coord_url,
            coord_local_path=coord_local_path,
            coord_parquet_path=coord_parquet_path,
        )
        geo_table = _load_geo_table(coord_local_path)

    existing_catalog = _load_json(output_path, {}) if output_path.exists() else {}

    catalog: dict[str, Any] = {
        "catalog_version": 2,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mission": "MSL",
        "base_url": base_url,
        "coord_url": coord_url,
        "coord_local_path": str(coord_local_path.relative_to(project_root)) if coord_local_path.is_relative_to(project_root) else str(coord_local_path),
        "coord_downloaded_now": coord_downloaded_now,
        "coord_updated_now": coord_updated_now,
        "coord_sync_reason": coord_sync_reason,
        "cameras": {},
    }

    if isinstance(existing_catalog, dict) and isinstance(existing_catalog.get("cameras"), dict):
        for cam, payload in existing_catalog["cameras"].items():
            if cam in cameras and isinstance(payload, dict):
                products = payload.get("products", [])
                if isinstance(products, list):
                    catalog["cameras"][cam] = {
                        "product_count": len(products),
                        "products": products,
                    }

    for cam in cameras:
        if cam not in catalog["cameras"]:
            catalog["cameras"][cam] = {"product_count": 0, "products": []}

    existing_img_urls: set[str] = set()
    for cam in cameras:
        for p in catalog["cameras"][cam]["products"]:
            img_url = p.get("img_url")
            if img_url:
                existing_img_urls.add(str(img_url))

    state_path = output_path.with_suffix(output_path.suffix + ".state.json")
    fp = _build_fingerprint(base_url, list(cameras), sol_start, sol_end)
    state = _load_json(state_path, {}) if state_path.exists() else {}
    if not isinstance(state, dict) or state.get("fingerprint") != fp or args.refresh_sol_index:
        state = {"fingerprint": fp, "scanned_sol_urls": []}
    scanned_sol_urls: set[str] = set(state.get("scanned_sol_urls") or [])

    def checkpoint(reason: str, write_parquet: bool) -> None:
        for cam in cameras:
            catalog["cameras"][cam]["product_count"] = len(catalog["cameras"][cam]["products"])
        catalog["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
        _write_json(output_path, catalog)
        state_payload = {
            "fingerprint": fp,
            "scanned_sol_urls": sorted(scanned_sol_urls),
            "saved_at_utc": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
        }
        _write_json(state_path, state_payload)
        if write_parquet:
            rows = _write_parquet(catalog, parquet_output_path)
            _emit("checkpoint", f"reason={reason} | parquet_rows={rows}")
        else:
            _emit("checkpoint", f"reason={reason} | json_saved")

    new_items_total = 0

    for camera in cameras:
        if STOP_EVENT.is_set():
            _emit("stop", "Interruzione richiesta: stop build catalog")
            break

        cconf = cam_cfg[camera]
        token = cconf.get("collection_token")
        data_roots = cconf.get("data_roots", [])

        _emit("camera_discover_start", f"{camera}: discovering collections matching {token}")
        collections = discover_collections_for_camera(client, base_url, str(token))
        _emit("camera_discover_done", f"{camera}: found {len(collections)} collections")

        all_sols: list[SolLocation] = []
        for idx, coll in enumerate(collections, start=1):
            if STOP_EVENT.is_set():
                break
            _emit("camera_sol_scan", f"{camera}: [{idx}/{len(collections)}] scanning SOL directories in {coll}")
            all_sols.extend(discover_sol_locations(client, base_url, coll, data_roots))

        unique_sols = sorted(
            {
                (s.collection, s.data_root, s.sol, s.sol_dir_name, s.sol_url): s
                for s in all_sols
            }.values(),
            key=lambda s: (s.sol, s.collection, s.data_root, s.sol_url),
        )

        if sol_start is not None:
            unique_sols = [s for s in unique_sols if s.sol >= int(sol_start)]
        if sol_end is not None:
            unique_sols = [s for s in unique_sols if s.sol <= int(sol_end)]

        products_new_camera: list[dict[str, Any]] = []

        total_sols = len(unique_sols)
        for i, loc in enumerate(unique_sols, start=1):
            if STOP_EVENT.is_set():
                _emit("stop", f"{camera}: stop richiesto durante scan prodotti")
                break

            if loc.sol_url in scanned_sol_urls:
                continue

            _emit(
                "camera_product_scan",
                f"{camera}: [{i}/{total_sols}] indexing SOL {loc.sol} ({loc.collection})",
            )

            found = scan_products_in_sol(client, loc, base_url)
            added_now = 0
            for rec in found:
                img_url = str(rec.get("img_url", ""))
                if not img_url or img_url in existing_img_urls:
                    continue
                existing_img_urls.add(img_url)
                catalog["cameras"][camera]["products"].append(rec)
                products_new_camera.append(rec)
                new_items_total += 1
                added_now += 1

                if checkpoint_every > 0 and (new_items_total % checkpoint_every == 0):
                    checkpoint(reason=f"every_{checkpoint_every}", write_parquet=checkpoint_write_parquet)
                    _emit("catalog_live", f"items={new_items_total} -> {output_path}")

            scanned_sol_urls.add(loc.sol_url)
            if added_now:
                _emit("catalog_live", f"items={new_items_total} -> {output_path}")

        if STOP_EVENT.is_set():
            _emit("stop", "Interruzione richiesta: stop arricchimento geografico")
            continue

        _emit("camera_geo_enrich", f"{camera}: enriching products with geography")
        candidates = _select_lbl_candidates(products_new_camera, min_img_size)
        _enrich_with_lbl_and_geo(client, products_new_camera, candidates, geo_table)

    checkpoint(reason="final", write_parquet=True)

    if STOP_EVENT.is_set():
        _emit("stop", "Interruzione richiesta: stop build catalog")

    final_rows = _write_parquet(catalog, parquet_output_path)

    _emit("done", f"catalog written to: {output_path}")
    _emit("done", f"new items added: {new_items_total}")
    _emit("done", f"parquet written to: {parquet_output_path}")
    _emit("done", f"dataframe rows: {final_rows}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
