"""Catalog health/freshness inspection: read a local Parquet catalog's shape (row counts,
Sol range, per-camera coverage, data-quality checks), then optionally cross-check it
against what's actually published remotely (PDS directory listings / the RAW Archive
manifest) to decide whether an update is worth running. This is the read-only backend
for Catalog Manager's dashboard status cards -- it never writes to the catalogs
themselves (see `catalog_install.py`/`workers/*.py` for that).
"""

from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests


RAW_MANIFEST_URLS = (
    "https://mars.jpl.nasa.gov/msl-raw-images/image/image_manifest.json",
    "http://mars.jpl.nasa.gov/msl-raw-images/image/image_manifest.json",
)


@dataclass
class CatalogStatus:
    """One catalog's (pds/raw) inspected local state plus, once `attach_remote_status` runs, its remote-comparison result. Built by `inspect_catalog`; serialised via `to_dict`/`save_status_report`."""

    key: str
    path: str
    exists: bool = False
    valid: bool = False
    rows: int = 0
    sol_min: int | None = None
    sol_max: int | None = None
    product_sols: int = 0
    last_checked_sol: int | None = None
    cameras: dict[str, int] | None = None
    camera_sol_max: dict[str, int] | None = None
    camera_last_checked: dict[str, int] | None = None
    duplicate_urls: int = 0
    null_urls: int = 0
    null_product_ids: int = 0
    size_bytes: int = 0
    modified_at: str = ""
    remote_latest_sol: int | None = None
    remote_by_camera: dict[str, int] | None = None
    remote_checked_at: str = ""
    remote_error: str = ""
    update_available: bool | None = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to a plain JSON-serialisable dict."""
        return asdict(self)


def _load_json(path: Path) -> dict[str, Any]:
    """Read and parse `path` as a JSON object, returning `{}` if missing, invalid, or not an object."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _fallback_camera_checked(
    path: Path,
    key: str,
    camera_sol_max: dict[str, int],
) -> dict[str, int]:
    """Determine each camera's "last verified Sol" when `record_camera_checked`'s tracking state is missing or incomplete for it.

    Prefers `catalog_manager_state.json`'s saved `camera_last_checked` map;
    falls back to a heuristic for catalogs imported before that tracking
    existed: ChemCam (scanned separately) reads its own component's
    `scanned_sols` state file, while every other camera is assumed checked up
    to whatever the single most-advanced camera in the Parquet reached (see
    `record_camera_checked`'s docstring for why this heuristic alone isn't
    reliable going forward).
    """
    manager_state = _load_json(path.parent / "catalog_manager_state.json")
    saved = (manager_state.get("catalogs", {}).get(key, {}) or {}).get("camera_last_checked")
    if isinstance(saved, dict) and saved:
        return {str(camera): int(sol) for camera, sol in saved.items()}
    companion = "chemcam_catalog.json.state.json" if key == "pds" else "chemcam_raw_catalog.json.state.json"
    scanned = _load_json(path.parent / companion).get("scanned_sols", [])
    try:
        chemcam_checked = max(int(sol) for sol in scanned)
    except (TypeError, ValueError):
        chemcam_checked = camera_sol_max.get("chemcam", -1)
    if key == "pds":
        # The imported PDS catalog was manually built with a common Sol limit.
        common_checked = max(camera_sol_max.values(), default=-1)
    else:
        # The imported RAW main catalog predates the separately refreshed ChemCam component.
        common_checked = max((sol for camera, sol in camera_sol_max.items() if camera != "chemcam"), default=-1)
    return {
        camera: (chemcam_checked if camera == "chemcam" else common_checked)
        for camera in camera_sol_max
    }


def record_camera_checked(project_root: Path, catalog_key: str, camera: str, sol: int, parquet_path: Path) -> None:
    """Persist that `camera` in `catalog_key` (pds/raw) has been verified up
    to `sol`. This is what _fallback_camera_checked() prefers when present.

    Without this, a camera updated on its own (the normal case now that
    updates run one camera at a time) would be judged by a heuristic that
    assumes every camera is always exactly as current as the single
    most-advanced one — which silently marks untouched cameras as "up to
    date" the moment any other camera gets updated.
    """
    state_path = project_root / "data" / "catalog" / "catalog_manager_state.json"
    state = _load_json(state_path)
    catalogs = state.setdefault("catalogs", {})
    entry = catalogs.setdefault(catalog_key, {})
    checked = entry.setdefault("camera_last_checked", {})

    # First time this file is used for this catalog: seed every other camera
    # with what the Parquet already shows, so they don't silently vanish from
    # tracking (and fall back to "-1 = never checked") the moment we start
    # recording just the one camera that was actually updated.
    if not checked:
        try:
            frame = pd.read_parquet(parquet_path, columns=["camera", "sol"])
            numeric_sol = pd.to_numeric(frame["sol"], errors="coerce")
            frame = frame.assign(_sol_numeric=numeric_sol).dropna(subset=["_sol_numeric"])
            for cam, sol_max in frame.groupby(frame["camera"].astype(str).str.lower())["_sol_numeric"].max().items():
                checked.setdefault(str(cam), int(sol_max))
        except Exception:  # noqa: BLE001
            pass

    checked[str(camera).lower()] = int(sol)
    entry["camera_last_checked"] = checked

    temp = state_path.with_suffix(state_path.suffix + ".tmp")
    temp.parent.mkdir(parents=True, exist_ok=True)
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, state_path)


# path (resolved, as str) -> ((mtime_ns, size_bytes), CatalogStatus). Keyed on
# the Parquet's own mtime/size, not an explicit invalidation call: any real
# update (worker install, manual copy) changes one of those, so a stale entry
# can never be served -- see inspect_catalog() below.
_INSPECT_CACHE_LOCK = threading.Lock()
_INSPECT_CACHE: dict[str, tuple[tuple[int, int], CatalogStatus]] = {}


def inspect_catalog(path: Path, key: str) -> CatalogStatus:
    """Read `path` (a catalog Parquet) and build its full `CatalogStatus`: row/Sol/camera counts, per-camera coverage, and data-quality checks (duplicate/null URLs, null product ids). Purely local -- no network calls; see `attach_remote_status` for the remote-comparison half.

    Cached in memory per (resolved path, mtime, size): this is called on
    every Overview/Updates load and re-parsing 300k+ rows from Parquet each
    time is real, avoidable latency -- worse still when the catalog lives on
    a slow external drive. Returns a shallow copy on every call (cheap: the
    dict-valued fields are never mutated in place downstream, only
    reassigned wholesale by `attach_remote_status`) so callers can't corrupt
    the cached entry.
    """
    if not path.exists():
        return CatalogStatus(key=key, path=str(path.resolve()), exists=False, error="catalog_missing")

    stat = path.stat()
    fingerprint = (stat.st_mtime_ns, stat.st_size)
    cache_key = str(path.resolve())

    with _INSPECT_CACHE_LOCK:
        cached = _INSPECT_CACHE.get(cache_key)
        if cached is not None and cached[0] == fingerprint:
            return replace(cached[1])

    status = _inspect_catalog_uncached(path, key, stat)
    if not status.error:
        with _INSPECT_CACHE_LOCK:
            _INSPECT_CACHE[cache_key] = (fingerprint, status)
    return replace(status)


def _inspect_catalog_uncached(path: Path, key: str, stat: os.stat_result) -> CatalogStatus:
    """Actual Parquet parse + stats computation behind `inspect_catalog`'s cache -- see its docstring."""
    status = CatalogStatus(key=key, path=str(path.resolve()), exists=True)
    try:
        status.size_bytes = int(stat.st_size)
        status.modified_at = datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds")
        frame = pd.read_parquet(path, columns=["product_id", "sol", "camera", "img_url"])
        status.rows = len(frame)
        numeric_sol = pd.to_numeric(frame["sol"], errors="coerce").dropna()
        if len(numeric_sol):
            status.sol_min = int(numeric_sol.min())
            status.sol_max = int(numeric_sol.max())
            status.product_sols = int(numeric_sol.nunique())
        status.cameras = {
            str(camera): int(count)
            for camera, count in frame["camera"].fillna("unknown").astype(str).value_counts().items()
        }
        camera_max = frame.assign(_sol_numeric=pd.to_numeric(frame["sol"], errors="coerce")).dropna(subset=["_sol_numeric"])
        status.camera_sol_max = {
            str(camera): int(sol)
            for camera, sol in camera_max.groupby("camera")["_sol_numeric"].max().items()
        }
        status.camera_last_checked = _fallback_camera_checked(path, key, status.camera_sol_max)
        status.last_checked_sol = min(status.camera_last_checked.values(), default=status.sol_max)
        status.duplicate_urls = int(frame["img_url"].duplicated().sum())
        status.null_urls = int(frame["img_url"].fillna("").astype(str).str.strip().eq("").sum())
        status.null_product_ids = int(frame["product_id"].fillna("").astype(str).str.strip().eq("").sum())
        status.valid = status.duplicate_urls == 0 and status.null_urls == 0 and status.null_product_ids == 0
    except Exception as exc:  # noqa: BLE001
        status.error = f"{type(exc).__name__}: {exc}"
    return status


def _raw_camera(item: dict[str, Any]) -> str | None:
    """Map one RAW manifest image entry to this app's camera key (`mastcam`/`mahli`/`navcam`/`mardi`/`hazcam`/`chemcam`), or `None` if it's a thumbnail/EDR-T or an instrument this app doesn't track."""
    instrument = str(item.get("instrument") or item.get("instrument_id") or "").upper()
    sample_type = str(item.get("sampleType") or item.get("sample_type") or "").casefold()
    url = str(item.get("urlList") or item.get("url") or item.get("img_url") or "").upper()
    if sample_type == "thumbnail" or "THUMBNAIL" in url or "EDR_T" in url:
        return None
    if "CHEMCAM" in instrument:
        return "chemcam" if sample_type == "chemcam prc" else None
    if "MARDI" in instrument:
        return "mardi"
    if "MAHLI" in instrument:
        return "mahli"
    if "MAST" in instrument:
        return "mastcam"
    if "NAV" in instrument:
        return "navcam"
    if "FHAZ" in instrument or "RHAZ" in instrument or "HAZ" in instrument:
        return "hazcam"
    return None


def fetch_raw_remote_status(
    status: CatalogStatus,
    timeout: int = 30,
    overlap_sols: int = 20,
) -> tuple[int | None, dict[str, int], str]:
    """Inspect new/recent RAW Sol catalogs and update per-camera remote maxima."""
    errors: list[str] = []
    manifest: dict[str, Any] | None = None
    with requests.Session() as session:
        session.headers.update({"User-Agent": "MSL-Catalog-Manager/1.0"})
        for url in RAW_MANIFEST_URLS:
            try:
                response = session.get(url, timeout=timeout)
                response.raise_for_status()
                candidate = response.json()
                if isinstance(candidate, dict):
                    manifest = candidate
                    break
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{url}: {type(exc).__name__}: {exc}")
    if manifest is None:
        return None, dict(status.camera_sol_max or {}), " | ".join(errors)

    sol_entries: dict[int, str] = {}
    for entry in manifest.get("sols", []):
        if not isinstance(entry, dict):
            continue
        try:
            sol = int(entry.get("sol"))
        except (TypeError, ValueError):
            continue
        catalog_url = str(entry.get("catalog_url") or "").strip()
        if catalog_url:
            sol_entries[sol] = catalog_url
    values = [int(manifest["latest_sol"])] if manifest.get("latest_sol") is not None else []
    values.extend(sol_entries)
    latest = max(values) if values else None
    if latest is None:
        return None, dict(status.camera_sol_max or {}), "RAW manifest contains no Sol"

    checked = status.last_checked_sol if status.last_checked_sol is not None else status.sol_max
    start = max(0, int(checked or 0) - max(0, int(overlap_sols)))
    selected = [(sol, url) for sol, url in sol_entries.items() if start <= sol <= latest]
    maxima = dict(status.camera_sol_max or {})

    def inspect_sol(sol: int, url: str) -> tuple[int, set[str], str]:
        try:
            response = requests.get(url, timeout=timeout, headers={"User-Agent": "MSL-Catalog-Manager/1.0"})
            response.raise_for_status()
            payload = response.json()
            cameras = {
                camera
                for item in payload.get("images", [])
                if isinstance(item, dict) and (camera := _raw_camera(item)) is not None
            }
            return sol, cameras, ""
        except Exception as exc:  # noqa: BLE001
            return sol, set(), f"sol {sol}: {type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(inspect_sol, sol, url) for sol, url in selected]
        for future in as_completed(futures):
            sol, cameras, error = future.result()
            if error:
                errors.append(error)
            for camera in cameras:
                maxima[camera] = max(int(maxima.get(camera, -1)), sol)
    return latest, maxima, " | ".join(errors)


def fetch_pds_remote_status(
    project_root: Path, timeout: int = 30, checked_by_camera: dict[str, int] | None = None,
) -> tuple[int | None, dict[str, int], str]:
    """Discover the latest directory actually published for each PDS camera.

    A Sol directory existing on the server does not mean it contains
    anything this camera actually curates: NASA sometimes publishes a new
    Sol with only product types outside the established scope (observed for
    Mastcam -- a fresh Sol can contain only "I01"-type products while the
    catalog curates C00/E01/DRCL per camera_rules.json). Reporting raw
    directory existence there permanently flags the camera as "needs
    update" even though the real filtered update job will always find 0
    products for it. So for cameras with an established curated filter, a
    Sol beyond what's already checked is only reported once it's confirmed
    to contain a matching product.
    """
    try:
        from core.make_msl_catalog import (
            PDSClient, discover_collections_for_camera, discover_sol_locations, scan_products_in_sol,
        )
        from core.make_msl_chemcam_catalog import CHEMCAM_RDR_DATA_URL, discover_sol_urls
        from catalog_manager.customization import CUSTOMIZABLE_CAMERAS, current_include_args
    except Exception as exc:  # noqa: BLE001
        return None, {}, f"PDS modules unavailable: {type(exc).__name__}: {exc}"

    cfg = _load_json(project_root / "config" / "msl_catalog_config.json")
    base_url = str(cfg.get("base_url") or "https://planetarydata.jpl.nasa.gov/img/data/msl/")
    camera_cfg = cfg.get("camera_config") if isinstance(cfg.get("camera_config"), dict) else {}
    camera_names = [name for name in ("mastcam", "mahli", "navcam", "mardi", "hazcam") if name in camera_cfg]
    checked_by_camera = checked_by_camera or {}
    # Same rule, same matching function as the update job and the integrity
    # check (_record_is_allowed) -- no separate --include-* translation to
    # keep in sync (that translation is exactly what missed camera_rules.json's
    # min_img_size_bytes constraint for Mahli).
    rules_cfg = _load_json(project_root / "config" / "camera_rules.json")

    def discover_standard(camera: str) -> tuple[str, int | None, str]:
        """Find `camera`'s highest remote Sol that actually contains a curated product (not just any Sol directory); returns `(camera, latest_sol_or_None, error_message)`."""
        try:
            # The PDS directory server occasionally answers with a temporary
            # 503. Five spaced attempts make a status check much less likely
            # to become partial because of a short server-side interruption.
            client = PDSClient(timeout=timeout, retries=5)
            item = camera_cfg[camera]
            collections = discover_collections_for_camera(client, base_url, str(item.get("collection_token", "")))
            locations = []
            # Collection names are release ordered. The newest Sol must be in
            # the newest collection; include the previous one for release-boundary safety.
            for collection in collections[-2:]:
                locations.extend(discover_sol_locations(client, base_url, collection, item.get("data_roots") or []))
            if not locations:
                return camera, None, ""
            raw_max = max(loc.sol for loc in locations)

            checked_sol = int(checked_by_camera.get(camera, -1))
            has_rule = camera in CUSTOMIZABLE_CAMERAS and bool(current_include_args(camera))
            if not has_rule or raw_max <= checked_sol:
                return camera, raw_max, ""

            # Only the Sols beyond what's already checked matter here; scan
            # from the newest down and stop at the first one that actually
            # contains a matching product.
            new_locations = sorted(
                (loc for loc in locations if loc.sol > checked_sol),
                key=lambda loc: loc.sol,
                reverse=True,
            )
            for loc in new_locations:
                if scan_products_in_sol(client, loc, base_url, camera=camera, camera_rules_cfg=rules_cfg):
                    return camera, loc.sol, ""
            # New directories exist, but none contain a curated product yet
            # -- report no change so this camera doesn't look permanently
            # "behind" for content NASA hasn't actually published.
            return camera, checked_sol if checked_sol >= 0 else None, ""
        except Exception as exc:  # noqa: BLE001
            return camera, None, f"{type(exc).__name__}: {exc}"

    results: dict[str, int] = {}
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(discover_standard, camera) for camera in camera_names]
        futures.append(executor.submit(lambda: ("chemcam", max(discover_sol_urls(PDSClient(timeout=timeout, retries=5), CHEMCAM_RDR_DATA_URL)), "")))
        for future in as_completed(futures):
            try:
                camera, latest, error = future.result()
                if latest is not None:
                    results[camera] = int(latest)
                if error:
                    errors.append(f"{camera}: {error}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{type(exc).__name__}: {exc}")
    return (max(results.values()) if results else None), results, " | ".join(errors)


def attach_remote_status(
    status: CatalogStatus,
    latest_sol: int | None,
    error: str,
    *,
    by_camera: dict[str, int] | None = None,
) -> None:
    """Merge a remote-status check's result into `status` in place, and decide `status.update_available`: `None` if the check errored or there's nothing to compare against, per-camera comparison against `camera_last_checked` when `by_camera` is given, otherwise a single last-checked-Sol comparison."""
    checked = datetime.now(timezone.utc).isoformat(timespec="seconds")
    status.remote_latest_sol = latest_sol
    status.remote_by_camera = by_camera or None
    status.remote_checked_at = checked
    status.remote_error = error
    if error:
        # Partial results remain visible, but are never considered sufficient
        # to authorize a catalog update.
        status.update_available = None
    elif latest_sol is None or status.last_checked_sol is None:
        status.update_available = None
    elif by_camera:
        checked = status.camera_last_checked or {}
        status.update_available = any(int(remote_sol) > int(checked.get(camera, -1)) for camera, remote_sol in by_camera.items())
    else:
        status.update_available = status.last_checked_sol < latest_sol


def save_status_report(path: Path, statuses: list[CatalogStatus]) -> None:
    """Write `statuses` to `path` as a JSON report (`{catalog_key: status_dict}`), atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "catalogs": {status.key: status.to_dict() for status in statuses},
    }
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def format_bytes(value: int) -> str:
    """Format a byte count as a human-readable string (`"12.3 MB"`), capping at GB."""
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
