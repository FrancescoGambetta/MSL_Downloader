"""Catalog Manager backend bridge: thin wrappers around `catalog_manager/`'s
already Streamlit-free modules (`services.py`, `jobs.py`, `distribution.py`,
`bootstrap.py`, `customization.py`, `product_composition.py`), reused
directly -- no reimplementation, mirroring `webapi/catalog_service.py`'s
approach for the downloader side.

Two different job models exist here, both already established by
`catalog_manager/` itself (not introduced by this bridge):
- `catalog_manager.jobs.start_*_job()`: launches a DETACHED SUBPROCESS per
  job, tracked via JSON state files under `data/catalog/jobs/{active,completed}/`.
  These need no in-process job tracking at all -- `load_job()`/`request_cancel()`
  read/write the same files the Streamlit UI already polls, so this API and
  the Streamlit dashboard can watch/cancel the very same job.
- `catalog_manager.distribution.install_remote_*_release()`: a synchronous,
  in-process call with a progress callback (no subprocess of its own) -- used
  by the first-run "Download & Install" wizard. This module runs it in a
  background thread (like `webapi/download_service.py` does for downloads),
  tracked in the in-memory `_INSTALL_JOBS` dict below.
"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent

from catalog_manager import bootstrap as cm_bootstrap  # noqa: E402
from catalog_manager import distribution as cm_distribution  # noqa: E402
from catalog_manager import jobs as cm_jobs  # noqa: E402
from catalog_manager import product_composition as cm_composition  # noqa: E402
from catalog_manager import segment_explain as cm_segment_explain  # noqa: E402
from catalog_manager import services as cm_services  # noqa: E402
from catalog_manager.customization import CAMERA_OPTIONS, current_camera_options  # noqa: E402

_CATALOG_PATHS = {
    "pds": PROJECT_ROOT / "data" / "catalog" / "Catalog_PDS.parquet",
    "raw": PROJECT_ROOT / "data" / "catalog" / "Catalog_RawArch.parquet",
}


# ---------------------------------------------------------------------------
# Local/remote status (services.py, read-only)
# ---------------------------------------------------------------------------


def local_status(catalog: str) -> dict[str, Any]:
    """`catalog`'s local-only inspection (no network) -- row/Sol/camera counts, data-quality checks."""
    status = cm_services.inspect_catalog(_CATALOG_PATHS[catalog], catalog)
    return status.to_dict()


def status_with_cached_remote(catalog: str) -> dict[str, Any]:
    """Local status merged with the last saved remote-comparison report (from a
    previous `check_updates` run), if one exists -- lets the Overview screen
    show a "last known" freshness comparison without a slow live NASA check on
    every page load (the Updates tab's Check button is what refreshes it)."""
    status = cm_services.inspect_catalog(_CATALOG_PATHS[catalog], catalog)
    report_path = PROJECT_ROOT / "data" / "catalog" / "catalog_status_report.json"
    if report_path.exists():
        try:
            import json

            report = json.loads(report_path.read_text(encoding="utf-8"))
            cached = (report.get("catalogs") or {}).get(catalog)
            if cached:
                # Re-derive `update_available` against the CURRENT local status
                # rather than copying the cached report's own boolean verbatim:
                # that boolean was computed against local state as of the last
                # check, and a catalog update since then (installed straight
                # from a job, no fresh NASA check involved) can leave it stale
                # -- "Sol 4983 -> 4983, +0 nuovi Sol" but still flagged as
                # "update available" because the flag itself was never redone.
                cm_services.attach_remote_status(
                    status,
                    cached.get("remote_latest_sol"),
                    cached.get("remote_error") or "",
                    by_camera=cached.get("remote_by_camera"),
                )
                if cached.get("remote_checked_at"):
                    status.remote_checked_at = cached["remote_checked_at"]
        except Exception:  # noqa: BLE001
            pass
    return status.to_dict()


def check_updates(catalog: str) -> dict[str, Any]:
    """Cross-check `catalog`'s local state against NASA (blocking network call -- several seconds for RAW, up to a couple minutes for PDS)."""
    status = cm_services.inspect_catalog(_CATALOG_PATHS[catalog], catalog)
    if catalog == "pds":
        latest, by_camera, error = cm_services.fetch_pds_remote_status(
            PROJECT_ROOT, checked_by_camera=status.camera_last_checked or {}
        )
    else:
        latest, by_camera, error = cm_services.fetch_raw_remote_status(status)
    cm_services.attach_remote_status(status, latest, error, by_camera=by_camera)
    cm_services.save_status_report(PROJECT_ROOT / "data" / "catalog" / "catalog_status_report.json", [status])
    return status.to_dict()


# ---------------------------------------------------------------------------
# Jobs (jobs.py -- detached subprocess workers, JSON state files)
# ---------------------------------------------------------------------------


def load_job(job_id: str) -> dict[str, Any] | None:
    job = cm_jobs.load_job(job_id)
    return job or None


def active_job(catalog: str) -> dict[str, Any] | None:
    return cm_jobs.active_job_for_catalog(catalog)


def latest_job(catalog: str, operation: str = "integrity_check") -> dict[str, Any] | None:
    return cm_jobs.latest_job(catalog, operation=operation)


def recent_jobs(catalog: str, limit: int = 8) -> list[dict[str, Any]]:
    return cm_jobs.recent_jobs(catalog, limit=limit)


def get_job_log(job_id: str, max_bytes: int = 20_000) -> str:
    """Tail of `job_id`'s worker log file, mirroring `catalog_manager/app.py::_job_log_snapshot`
    (the Streamlit dashboard's own live-log expander) -- workers are detached
    subprocesses that write plain text here as they run, not the structured
    per-entry log the downloader's in-process jobs use."""
    path = PROJECT_ROOT / "data" / "catalog" / "jobs" / "logs" / f"{job_id}.log"
    if not path.is_file():
        return ""
    with path.open("rb") as stream:
        size = stream.seek(0, 2)
        stream.seek(max(0, size - max_bytes))
        return stream.read().decode("utf-8", errors="replace")


def job_lineage(job: dict[str, Any]) -> list[dict[str, Any]]:
    """Walk `job`'s `retry_of`/`resume_of` chain back to the original attempt (oldest-first) -- ported from `catalog_manager/app.py::job_lineage`, which lives in the UI module rather than `jobs.py` itself."""
    chain = [job]
    seen = {str(job.get("job_id", ""))}
    current = job
    while current.get("retry_of") or current.get("resume_of"):
        parent_id = str(current.get("retry_of") or current.get("resume_of"))
        if not parent_id or parent_id in seen:
            break
        parent = cm_jobs.load_job(parent_id)
        if not parent:
            break
        chain.append(parent)
        seen.add(parent_id)
        current = parent
    return list(reversed(chain))


def estimate_integrity_seconds(catalog: str, camera: str, sol_start: int, sol_end: int) -> tuple[int, int]:
    return cm_jobs.estimate_integrity_seconds(catalog, camera, sol_start, sol_end)


def last_integrity_sol(catalog: str, camera: str) -> int | None:
    return cm_jobs.last_integrity_sol(catalog, camera)


def resumable_job(job_id: str) -> bool:
    return cm_jobs.resumable_job(job_id)


def request_cancel(job_id: str) -> None:
    cm_jobs.request_cancel(job_id)


def start_integrity_job(catalog: str, camera: str, sol_start: int, sol_end: int) -> dict[str, Any]:
    fn = cm_jobs.start_pds_integrity_job if catalog == "pds" else cm_jobs.start_raw_integrity_job
    return fn(camera, sol_start, sol_end)


def start_failed_retry(catalog: str, source_job_id: str) -> dict[str, Any]:
    fn = cm_jobs.start_pds_failed_retry if catalog == "pds" else cm_jobs.start_raw_failed_retry
    return fn(source_job_id)


def start_resume_job(catalog: str, source_job_id: str) -> dict[str, Any]:
    fn = cm_jobs.start_pds_resume_job if catalog == "pds" else cm_jobs.start_raw_resume_job
    return fn(source_job_id)


def start_repair_job(catalog: str, integrity_job_id: str) -> dict[str, Any]:
    fn = cm_jobs.start_pds_repair_job if catalog == "pds" else cm_jobs.start_raw_repair_job
    return fn(integrity_job_id)


def start_update_job(catalog: str, sol_start: int, sol_end: int, cameras: list[str]) -> dict[str, Any]:
    """PDS updates exactly one camera per run (see `jobs.start_pds_update_job`'s docstring); RAW accepts several at once."""
    if catalog == "pds":
        if not cameras:
            raise ValueError("PDS update requires exactly one camera")
        return cm_jobs.start_pds_update_job(sol_start, sol_end, cameras[0])
    return cm_jobs.start_raw_update_job(sol_start, sol_end, cameras)


def start_json_rebuild_job(catalog: str) -> dict[str, Any]:
    fn = cm_jobs.start_pds_json_rebuild_job if catalog == "pds" else cm_jobs.start_raw_json_rebuild_job
    return fn()


def start_bootstrap_json_job() -> dict[str, Any]:
    return cm_jobs.start_bootstrap_json_job()


def start_customization_job(changes: dict[str, dict[str, list[str]]], sol_start: int, sol_end: int) -> dict[str, Any]:
    return cm_jobs.start_pds_customization_job(changes, sol_start, sol_end)


def customization_resumable(job_id: str) -> bool:
    return cm_jobs.customization_resumable(job_id)


def start_customization_resume_job(source_job_id: str) -> dict[str, Any]:
    return cm_jobs.start_pds_customization_resume_job(source_job_id)


def json_status(catalog: str) -> dict[str, Any]:
    name = "Catalog_PDS.json" if catalog == "pds" else "Catalog_RawArch.json"
    path = PROJECT_ROOT / "data" / "catalog" / name
    return {"exists": path.exists(), "size_bytes": path.stat().st_size if path.exists() else 0}


# ---------------------------------------------------------------------------
# Bootstrap choice (bootstrap.py)
# ---------------------------------------------------------------------------


def bootstrap_state() -> dict[str, Any]:
    return cm_bootstrap.load_bootstrap_state(PROJECT_ROOT)


def save_bootstrap_choice(choice: str) -> dict[str, Any]:
    return cm_bootstrap.save_bootstrap_choice(PROJECT_ROOT, choice)


# ---------------------------------------------------------------------------
# Distribution install (distribution.py -- in-process, background-threaded here)
# ---------------------------------------------------------------------------

_INSTALL_JOBS: dict[str, dict[str, Any]] = {}
_install_lock = threading.Lock()


def distribution_status(catalog: str) -> dict[str, Any]:
    local = (
        cm_distribution.local_pds_release(PROJECT_ROOT)
        if catalog == "pds"
        else cm_distribution.local_raw_release(PROJECT_ROOT)
    )
    try:
        remote = (
            cm_distribution.fetch_remote_pds_manifest(PROJECT_ROOT)
            if catalog == "pds"
            else cm_distribution.fetch_remote_raw_manifest(PROJECT_ROOT)
        )
        remote_error = None
    except Exception as exc:  # noqa: BLE001
        remote = None
        remote_error = f"{type(exc).__name__}: {exc}"
    return {"local": local, "remote": remote, "remote_error": remote_error}


def start_distribution_install(catalog: str) -> str:
    """Launch the official-release download+install as a background thread; poll via `get_install_job`."""
    job_id = f"install-{catalog}-{uuid.uuid4().hex[:10]}"
    with _install_lock:
        _INSTALL_JOBS[job_id] = {
            "job_id": job_id,
            "catalog": catalog,
            "status": "running",
            "downloaded": 0,
            "total": None,
            "result": None,
            "error": None,
        }

    def progress(downloaded: int, total: int | None) -> None:
        with _install_lock:
            if job_id in _INSTALL_JOBS:
                _INSTALL_JOBS[job_id]["downloaded"] = downloaded
                _INSTALL_JOBS[job_id]["total"] = total

    def run() -> None:
        try:
            fn = (
                cm_distribution.install_remote_pds_release
                if catalog == "pds"
                else cm_distribution.install_remote_raw_release
            )
            result = fn(PROJECT_ROOT, progress=progress)
            with _install_lock:
                _INSTALL_JOBS[job_id]["status"] = "completed"
                _INSTALL_JOBS[job_id]["result"] = result
        except Exception as exc:  # noqa: BLE001
            with _install_lock:
                _INSTALL_JOBS[job_id]["status"] = "failed"
                _INSTALL_JOBS[job_id]["error"] = f"{type(exc).__name__}: {exc}"

    threading.Thread(target=run, daemon=True).start()
    return job_id


def get_install_job(job_id: str) -> dict[str, Any] | None:
    with _install_lock:
        job = _INSTALL_JOBS.get(job_id)
        return dict(job) if job else None


# ---------------------------------------------------------------------------
# Composition (product_composition.py, read-only)
# ---------------------------------------------------------------------------


def composition(catalog: str) -> dict[str, Any]:
    path = _CATALOG_PATHS[catalog]
    if not path.exists():
        return {}
    return cm_composition.build_inventory(path, catalog=catalog)


def explain_segment(dimension: str, code: str, lang: str, camera: str = "") -> dict[str, str]:
    """Human-readable role/explanation for one composition() segment code, reusing the legacy Streamlit "Spiega" dialog's own translated text (see segment_explain.py)."""
    return cm_segment_explain.explain_segment(dimension, code, lang, camera)


# ---------------------------------------------------------------------------
# Customization (customization.py -- PDS only, matches the Streamlit app:
# only `start_pds_customization_job` exists in jobs.py, no RAW counterpart)
# ---------------------------------------------------------------------------


def customization_options() -> dict[str, Any]:
    """Every customizable camera's available primary/secondary values (static, from `data/pds_camera_compatibility.json` etc.)."""
    return {
        camera: {
            "primary_dimension": config["primary_dimension"],
            "secondary_dimension": config["secondary_dimension"],
            "primary": list(config["primary"]),
            "secondary": list(config["secondary"]),
        }
        for camera, config in CAMERA_OPTIONS.items()
    }


def customization_current() -> dict[str, Any]:
    """What primary/secondary combinations are actually present today in the PDS catalog, per camera."""
    path = _CATALOG_PATHS["pds"]
    if not path.exists():
        return {}
    current = current_camera_options(path)
    return {camera: {primary: sorted(values) for primary, values in by_primary.items()} for camera, by_primary in current.items()}
