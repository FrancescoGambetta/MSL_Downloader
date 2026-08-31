"""Job orchestration: launches every Catalog Manager background operation (integrity
checks, updates, repairs, customization, JSON rebuilds, bootstrap) as a detached
subprocess under `catalog_manager/workers/`, and tracks each job's state as a JSON file
under `data/catalog/jobs/{active,completed}/`.

State-file lifecycle: a job is created under `active/` (queued -> running ->
[cancelling] -> done), then moved to `completed/` once it finishes, fails, or is
cancelled. `_job_is_stale`/`_reap_stale_job` cover the case where a worker process died
without updating its own state (crash, killed externally): the next read of an `active/`
job whose pid is gone or whose heartbeat is too old gets marked failed and moved out, so
it stops blocking new jobs on the same catalog forever. Per-catalog exclusivity is
enforced primarily by `active_job_for_catalog` (every `start_*_job` refuses to launch a
second live job on the same catalog); `integrity_check_worker.py` additionally takes its
own `JOBS_ROOT / "locks" / "{catalog}.lock"` file, which `_reap_stale_job` also releases
if a killed worker never reached its own cleanup. Cancellation is cooperative via a
`{job_id}.cancel` sentinel file (`request_cancel`) that each worker polls for.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from statistics import median
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq


PROJECT_ROOT = Path(__file__).resolve().parent.parent
JOBS_ROOT = PROJECT_ROOT / "data" / "catalog" / "jobs"

# A job in a "live" status with no heartbeat for longer than this, and whose
# recorded pid can't be confirmed alive, is treated as dead (its worker
# process crashed or was killed outside the app) instead of blocking new
# jobs on the same catalog forever.
_STALE_HEARTBEAT_SECONDS = 600
_LIVE_STATUSES = {"queued", "running", "cancelling"}


def _read_json(path: Path) -> dict[str, Any]:
    """Read and parse `path` as a JSON object, returning `{}` if missing, invalid, or not an object."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _pid_alive(pid: int) -> bool:
    """Best-effort liveness check. Fails safe: returns True (assume alive)
    whenever it cannot determine the answer, so a working job is never
    reaped by mistake."""
    if not isinstance(pid, int) or pid <= 0:
        return True
    if os.name == "nt":
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return True
                return exit_code.value == STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except Exception:
        return True
    return True


def _job_is_stale(state: dict[str, Any]) -> bool:
    """Decide whether a job claiming a live status is actually dead: its recorded pid is gone (preferred check), or -- for older job types with no pid -- its heartbeat is older than `_STALE_HEARTBEAT_SECONDS`."""
    if str(state.get("status") or "") not in _LIVE_STATUSES:
        return False
    pid = state.get("pid")
    if isinstance(pid, int) and pid > 0:
        return not _pid_alive(pid)
    # Older/other job types that don't record a pid: fall back to heartbeat
    # age so they don't block forever either, just more conservatively.
    heartbeat_text = str(state.get("heartbeat_at_utc") or state.get("started_at_utc") or state.get("created_at_utc") or "")
    if not heartbeat_text:
        return False
    try:
        heartbeat = datetime.fromisoformat(heartbeat_text.replace("Z", "+00:00"))
        if heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    age = (datetime.now(timezone.utc) - heartbeat).total_seconds()
    return age > _STALE_HEARTBEAT_SECONDS


def _reap_stale_job(path: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Mark a dead job as failed and move it out of active/ so it stops
    blocking new jobs on the same catalog."""
    state = dict(state)
    state["status"] = "failed"
    state["phase"] = "failed"
    state["error"] = (
        "The process running this job is no longer active "
        "(detected automatically, likely terminated abnormally)."
    )
    state["stale_reaped_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
        completed_path = JOBS_ROOT / "completed" / path.name
        completed_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(path, completed_path)
    except OSError:
        # If another process/thread already reaped or moved it, that's fine.
        pass

    # A killed process may never reach its own `finally: lock_path.unlink()`
    # (workers/integrity_check_worker.py). Release the lock too, but only if
    # it still names this exact job, so a lock legitimately held by a
    # different, live job is never touched.
    catalog = str(state.get("catalog") or "")
    job_id = str(state.get("job_id") or "")
    if catalog and job_id:
        lock_path = JOBS_ROOT / "locks" / f"{catalog}.lock"
        try:
            if lock_path.read_text(encoding="utf-8").strip() == job_id:
                lock_path.unlink(missing_ok=True)
        except OSError:
            pass
    return state


def _read_job_state(path: Path) -> dict[str, Any]:
    state = _read_json(path)
    if state and path.parent.name == "active" and _job_is_stale(state):
        return _reap_stale_job(path, state)
    return state


def job_state_path(job_id: str) -> Path:
    """Return where `job_id`'s state file lives while active (workers write here; it's moved to `completed/` on finish)."""
    return JOBS_ROOT / "active" / f"{job_id}.json"


def load_job(job_id: str) -> dict[str, Any]:
    """Load `job_id`'s state, checking `active/` first, then `completed/`; `{}` if not found either place."""
    active = job_state_path(job_id)
    if active.exists():
        return _read_job_state(active)
    return _read_json(JOBS_ROOT / "completed" / f"{job_id}.json")


def active_job_for_catalog(catalog: str) -> dict[str, Any] | None:
    """Return the currently-live job for `catalog`, if any -- the exclusivity check every `start_*_job` function runs before launching a new subprocess."""
    # Materialize the listing first: _read_job_state() may reap a stale entry
    # and move it out of active/ while we would otherwise still be iterating
    # that same directory.
    for path in list((JOBS_ROOT / "active").glob("*.json")):
        state = _read_job_state(path)
        if state.get("catalog") == catalog and state.get("status") in _LIVE_STATUSES:
            return state
    return None


def latest_job(catalog: str, operation: str = "integrity_check") -> dict[str, Any] | None:
    """Return the most recently modified job matching `catalog`+`operation`, across both `active/` and `completed/`."""
    candidates: list[tuple[float, dict[str, Any]]] = []
    for directory in (JOBS_ROOT / "active", JOBS_ROOT / "completed"):
        for path in list(directory.glob("*.json")):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            state = _read_job_state(path)
            if state.get("catalog") == catalog and state.get("operation") == operation:
                candidates.append((mtime, state))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def last_integrity_sol(catalog: str, camera: str) -> int | None:
    """Highest Sol actually covered by a finished (completed/partial)
    integrity check for this camera, so the next check can default to
    picking up where the last one left off instead of always starting from
    Sol 0. Cancelled/failed runs don't count -- their sol_end is only the
    requested target, not what was actually verified."""
    best: int | None = None
    for directory in (JOBS_ROOT / "active", JOBS_ROOT / "completed"):
        for path in list(directory.glob("*.json")):
            state = _read_job_state(path)
            if (
                state.get("catalog") == catalog
                and state.get("operation") == "integrity_check"
                and str(state.get("camera", "")).casefold() == camera.casefold()
                and state.get("status") in {"completed", "partial"}
            ):
                sol_end = state.get("sol_end")
                if sol_end is not None:
                    best = int(sol_end) if best is None else max(best, int(sol_end))
    return best


def recent_jobs(catalog: str, limit: int = 8) -> list[dict[str, Any]]:
    """Return `catalog`'s most recent integrity-check jobs (newest first, across `active/` and `completed/`), for the dashboard's job-history list."""
    candidates: list[tuple[float, dict[str, Any]]] = []
    for directory in (JOBS_ROOT / "active", JOBS_ROOT / "completed"):
        for path in list(directory.glob("*.json")):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            state = _read_job_state(path)
            if state.get("catalog") == catalog and state.get("operation") == "integrity_check":
                candidates.append((mtime, state))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [state for _mtime, state in candidates[: max(1, int(limit))]]


def resumable_job(job_id: str) -> bool:
    """Whether `job_id` left behind a checkpoint file it could be resumed from."""
    return (JOBS_ROOT / "checkpoints" / f"{job_id}.json").exists()


def estimate_integrity_seconds(catalog: str, camera: str, sol_start: int, sol_end: int) -> tuple[int, int]:
    """Estimate a `(low, high)` seconds range for an integrity check over `sol_end - sol_start` Sols, from the median per-Sol rate of past completed checks on the same catalog+camera (falls back to 6s/Sol with no history)."""
    span = max(1, abs(int(sol_end) - int(sol_start)) + 1)
    rates: list[float] = []
    for path in (JOBS_ROOT / "completed").glob("*.json"):
        state = _read_json(path)
        if state.get("operation") != "integrity_check" or state.get("camera") != camera:
            continue
        # PDS crawls per-collection HTML directory listings while RAW does a
        # single manifest fetch plus small per-Sol JSON requests -- the two
        # have very different throughput, so past runs of one must not skew
        # the time estimate shown for the other.
        if state.get("catalog") != catalog:
            continue
        if state.get("status") != "completed":
            continue
        try:
            sample_span = abs(int(state["sol_end"]) - int(state["sol_start"])) + 1
            rates.append(float(state["elapsed_seconds"]) / max(1, sample_span))
        except (KeyError, TypeError, ValueError):
            continue
    seconds_per_sol = median(rates) if rates else 6.0
    estimate = max(30.0, seconds_per_sol * span)
    return max(20, int(estimate * 0.75)), max(60, int(estimate * 1.5))


def start_pds_integrity_job(camera: str, sol_start: int, sol_end: int) -> dict[str, Any]:
    """Launch a PDS integrity-check job for `camera` over `[sol_start, sol_end]` as a detached `integrity_check_worker` subprocess; writes the initial `queued` state and returns it. Raises if a PDS job is already active."""
    existing = active_job_for_catalog("pds")
    if existing:
        raise RuntimeError(f"A PDS job is already active: {existing.get('job_id')}")

    job_id = f"pds-integrity-{camera}-{uuid.uuid4().hex[:10]}"
    for name in ("active", "completed", "results", "logs", "locks"):
        (JOBS_ROOT / name).mkdir(parents=True, exist_ok=True)

    state = {
        "schema_version": 1,
        "job_id": job_id,
        "operation": "integrity_check",
        "catalog": "pds",
        "camera": camera,
        "sol_start": int(min(sol_start, sol_end)),
        "sol_end": int(max(sol_start, sol_end)),
        "status": "queued",
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    path = job_state_path(job_id)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    command = [
        sys.executable,
        "-m",
        "catalog_manager.workers.integrity_check_worker",
        "--job-id",
        job_id,
        "--catalog",
        "pds",
        "--camera",
        camera,
        "--sol-start",
        str(state["sol_start"]),
        "--sol-end",
        str(state["sol_end"]),
    ]
    log_handle = (JOBS_ROOT / "logs" / f"{job_id}.log").open("a", encoding="utf-8")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen(  # noqa: S603
        command,
        cwd=PROJECT_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
        close_fds=True,
    )
    log_handle.close()
    return state


def start_raw_integrity_job(camera: str, sol_start: int, sol_end: int) -> dict[str, Any]:
    """RAW-catalog counterpart of `start_pds_integrity_job`; also checks the RAW catalog files actually exist first."""
    existing = active_job_for_catalog("raw")
    if existing:
        raise RuntimeError(f"A RAW job is already active: {existing.get('job_id')}")
    for filename in ("Catalog_RawArch.json", "Catalog_RawArch.parquet"):
        if not (PROJECT_ROOT / "data/catalog" / filename).exists():
            raise FileNotFoundError(f"Required RAW catalog file not found: {filename}")

    job_id = f"raw-integrity-{camera}-{uuid.uuid4().hex[:10]}"
    for name in ("active", "completed", "results", "logs", "locks"):
        (JOBS_ROOT / name).mkdir(parents=True, exist_ok=True)

    state = {
        "schema_version": 1,
        "job_id": job_id,
        "operation": "integrity_check",
        "catalog": "raw",
        "camera": camera,
        "sol_start": int(min(sol_start, sol_end)),
        "sol_end": int(max(sol_start, sol_end)),
        "status": "queued",
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    path = job_state_path(job_id)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    command = [
        sys.executable,
        "-m",
        "catalog_manager.workers.integrity_check_worker",
        "--job-id",
        job_id,
        "--catalog",
        "raw",
        "--camera",
        camera,
        "--sol-start",
        str(state["sol_start"]),
        "--sol-end",
        str(state["sol_end"]),
    ]
    log_handle = (JOBS_ROOT / "logs" / f"{job_id}.log").open("a", encoding="utf-8")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen(  # noqa: S603
        command,
        cwd=PROJECT_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
        close_fds=True,
    )
    log_handle.close()
    return state


def start_pds_update_job(sol_start: int, sol_end: int, camera: str) -> dict[str, Any]:
    """Start a safe PDS update for exactly one camera.

    One camera at a time is deliberate, not a limitation to work around: the
    scanner's --include-* filters are a single global set per run (see
    core/make_msl_catalog.py), and different cameras need different filters
    (Navcam and Hazcam use different prefixes/markers entirely). Bundling
    cameras together previously meant no filter could be applied at all,
    which silently captured every product variant NASA publishes instead of
    the curated set the catalog is supposed to contain.
    """
    existing = active_job_for_catalog("pds")
    if existing:
        raise RuntimeError(f"A PDS job is already active: {existing.get('job_id')}")
    source_json = PROJECT_ROOT / "data" / "catalog" / "Catalog_PDS.json"
    source_parquet = PROJECT_ROOT / "data" / "catalog" / "Catalog_PDS.parquet"
    if not source_json.exists():
        raise FileNotFoundError(f"Editable PDS JSON not found: {source_json}")
    if not source_parquet.exists():
        raise FileNotFoundError(f"PDS Parquet not found: {source_parquet}")

    allowed = {"mastcam", "mahli", "navcam", "hazcam", "mardi", "chemcam"}
    camera_key = str(camera).casefold()
    if camera_key not in allowed:
        raise ValueError(f"Unknown PDS camera for update: {camera}")
    job_id = f"pds-update-{uuid.uuid4().hex[:10]}"
    for name in ("active", "completed", "results", "logs", "locks", "staging"):
        (JOBS_ROOT / name).mkdir(parents=True, exist_ok=True)
    state = {
        "schema_version": 1, "job_id": job_id, "operation": "catalog_update",
        "catalog": "pds", "status": "queued", "phase": "queued",
        "sol_start": int(sol_start), "sol_end": int(sol_end), "camera": camera_key,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    job_state_path(job_id).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    command = [sys.executable, "-u", "-m", "catalog_manager.workers.pds_update_worker", "--job-id", job_id]
    log_handle = (JOBS_ROOT / "logs" / f"{job_id}.log").open("a", encoding="utf-8")
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS if os.name == "nt" else 0
    subprocess.Popen(
        command, cwd=str(PROJECT_ROOT), stdout=log_handle, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, close_fds=True, creationflags=creationflags,
    )
    log_handle.close()
    return state


def start_pds_repair_job(integrity_job_id: str) -> dict[str, Any]:
    """Repair the gaps a finished integrity check found: re-scan only the
    exact Sol locations that had missing products (not the whole range that
    check covered), applying config/camera_rules.json the same way a normal
    update does, and install atomically on success."""
    existing = active_job_for_catalog("pds")
    if existing:
        raise RuntimeError(f"A PDS job is already active: {existing.get('job_id')}")

    integrity_job = load_job(integrity_job_id)
    if not integrity_job:
        raise RuntimeError(f"Integrity check job not found: {integrity_job_id}")
    camera = str(integrity_job.get("camera") or "").casefold()
    if not camera:
        raise RuntimeError(f"Integrity check job {integrity_job_id} has no camera recorded")
    if integrity_job.get("status") not in {"completed", "partial"}:
        raise RuntimeError(
            f"Integrity check {integrity_job_id} did not finish successfully "
            f"(status={integrity_job.get('status')})"
        )

    result_path = JOBS_ROOT / "results" / f"{integrity_job_id}.json"
    if not result_path.exists():
        raise RuntimeError(f"Integrity check result not found for job {integrity_job_id}")
    missing = (_read_json(result_path).get("missing_products")) or []
    if not missing:
        raise RuntimeError("Nothing to repair: the referenced integrity check found no missing products.")

    job_id = f"pds-repair-{camera}-{uuid.uuid4().hex[:10]}"
    for name in ("active", "completed", "results", "logs", "locks", "staging"):
        (JOBS_ROOT / name).mkdir(parents=True, exist_ok=True)
    state = {
        "schema_version": 1, "job_id": job_id, "operation": "repair",
        "catalog": "pds", "status": "queued", "phase": "queued",
        "camera": camera, "integrity_job_id": integrity_job_id,
        "missing_requested": len(missing),
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    job_state_path(job_id).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    command = [sys.executable, "-u", "-m", "catalog_manager.workers.pds_repair_worker", "--job-id", job_id]
    log_handle = (JOBS_ROOT / "logs" / f"{job_id}.log").open("a", encoding="utf-8")
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS if os.name == "nt" else 0
    subprocess.Popen(
        command, cwd=str(PROJECT_ROOT), stdout=log_handle, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, close_fds=True, creationflags=creationflags,
    )
    log_handle.close()
    return state


def start_raw_repair_job(integrity_job_id: str) -> dict[str, Any]:
    """Repair the gaps a finished RAW integrity check found: re-scan only the
    exact Sol manifest locations that had missing products (not the whole
    range that check covered), and install atomically on success."""
    existing = active_job_for_catalog("raw")
    if existing:
        raise RuntimeError(f"A RAW job is already active: {existing.get('job_id')}")

    integrity_job = load_job(integrity_job_id)
    if not integrity_job:
        raise RuntimeError(f"Integrity check job not found: {integrity_job_id}")
    camera = str(integrity_job.get("camera") or "").casefold()
    if not camera:
        raise RuntimeError(f"Integrity check job {integrity_job_id} has no camera recorded")
    if integrity_job.get("status") not in {"completed", "partial"}:
        raise RuntimeError(
            f"Integrity check {integrity_job_id} did not finish successfully "
            f"(status={integrity_job.get('status')})"
        )

    result_path = JOBS_ROOT / "results" / f"{integrity_job_id}.json"
    if not result_path.exists():
        raise RuntimeError(f"Integrity check result not found for job {integrity_job_id}")
    missing = (_read_json(result_path).get("missing_products")) or []
    if not missing:
        raise RuntimeError("Nothing to repair: the referenced integrity check found no missing products.")

    job_id = f"raw-repair-{camera}-{uuid.uuid4().hex[:10]}"
    for name in ("active", "completed", "results", "logs", "locks", "staging"):
        (JOBS_ROOT / name).mkdir(parents=True, exist_ok=True)
    state = {
        "schema_version": 1, "job_id": job_id, "operation": "repair",
        "catalog": "raw", "status": "queued", "phase": "queued",
        "camera": camera, "integrity_job_id": integrity_job_id,
        "missing_requested": len(missing),
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    job_state_path(job_id).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    command = [sys.executable, "-u", "-m", "catalog_manager.workers.raw_repair_worker", "--job-id", job_id]
    log_handle = (JOBS_ROOT / "logs" / f"{job_id}.log").open("a", encoding="utf-8")
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS if os.name == "nt" else 0
    subprocess.Popen(
        command, cwd=str(PROJECT_ROOT), stdout=log_handle, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, close_fds=True, creationflags=creationflags,
    )
    log_handle.close()
    return state


def start_raw_update_job(sol_start: int, sol_end: int, cameras: list[str]) -> dict[str, Any]:
    """Start a safe RAW update that writes only to a job staging directory."""
    existing = active_job_for_catalog("raw")
    if existing:
        raise RuntimeError(f"A RAW job is already active: {existing.get('job_id')}")
    for filename in ("Catalog_RawArch.json", "Catalog_RawArch.parquet"):
        if not (PROJECT_ROOT / "data/catalog" / filename).exists():
            raise FileNotFoundError(f"Required RAW catalog file not found: {filename}")
    allowed = {"mastcam", "mahli", "navcam", "hazcam", "mardi", "chemcam"}
    selected = list(dict.fromkeys(str(camera).casefold() for camera in cameras if str(camera).casefold() in allowed))
    if not selected:
        raise ValueError("No RAW cameras selected for update")
    job_id = f"raw-update-{uuid.uuid4().hex[:10]}"
    for name in ("active", "completed", "results", "logs", "locks", "staging"):
        (JOBS_ROOT / name).mkdir(parents=True, exist_ok=True)
    state = {
        "schema_version": 1, "job_id": job_id, "operation": "catalog_update",
        "catalog": "raw", "status": "queued", "phase": "queued",
        "sol_start": int(sol_start), "sol_end": int(sol_end), "cameras": selected,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    job_state_path(job_id).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    command = [sys.executable, "-u", "-m", "catalog_manager.workers.raw_update_worker", "--job-id", job_id]
    log_handle = (JOBS_ROOT / "logs" / f"{job_id}.log").open("a", encoding="utf-8")
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS if os.name == "nt" else 0
    subprocess.Popen(
        command, cwd=str(PROJECT_ROOT), stdout=log_handle, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, close_fds=True, creationflags=creationflags,
    )
    log_handle.close()
    return state


def start_pds_customization_job(changes: dict[str, dict[str, list[str]]], sol_start: int, sol_end: int) -> dict[str, Any]:
    """Apply a processing-level shopping list to a safe PDS working copy."""
    existing = active_job_for_catalog("pds")
    if existing:
        raise RuntimeError(f"A PDS job is already active: {existing.get('job_id')}")
    for filename in ("Catalog_PDS.json", "Catalog_PDS.parquet"):
        if not (PROJECT_ROOT / "data/catalog" / filename).exists():
            raise FileNotFoundError(f"Required PDS catalog file not found: {filename}")
    from catalog_manager.customization import CAMERA_OPTIONS
    clean: dict[str, dict[str, list[str]]] = {}
    for camera, selection in changes.items():
        camera_key = str(camera).casefold()
        if camera_key not in CAMERA_OPTIONS or not isinstance(selection, dict):
            continue
        config = CAMERA_OPTIONS[camera_key]
        clean_selection: dict[str, list[str]] = {}
        for primary in config["primary"]:
            requested = {str(value).upper() for value in selection.get(primary, [])}
            selected = [value for value in config["secondary"] if value in requested]
            if selected:
                clean_selection[primary] = selected
        if not clean_selection:
            raise ValueError(f"At least one product combination must remain for {camera_key}")
        clean[camera_key] = clean_selection
    if not clean:
        raise ValueError("No catalog changes were selected")
    job_id = f"pds-customize-{uuid.uuid4().hex[:10]}"
    for name in ("active", "completed", "results", "logs", "staging"):
        (JOBS_ROOT / name).mkdir(parents=True, exist_ok=True)
    state = {
        "schema_version": 1, "job_id": job_id, "operation": "catalog_customization",
        "catalog": "pds", "status": "queued", "phase": "queued", "changes": clean,
        "sol_start": int(min(sol_start, sol_end)), "sol_end": int(max(sol_start, sol_end)),
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    job_state_path(job_id).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    command = [sys.executable, "-u", "-m", "catalog_manager.workers.customization_worker", "--job-id", job_id]
    log_handle = (JOBS_ROOT / "logs" / f"{job_id}.log").open("a", encoding="utf-8")
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS if os.name == "nt" else 0
    subprocess.Popen(command, cwd=str(PROJECT_ROOT), stdout=log_handle, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, close_fds=True, creationflags=creationflags)
    log_handle.close()
    return state


def customization_resumable(job_id: str) -> bool:
    """True if a working copy from this (or a chained resume of this)
    customization attempt is still on disk and can be continued instead of
    starting over."""
    source = load_job(job_id)
    if not source:
        return False
    staging_key = str(source.get("resume_of") or job_id)
    staged = JOBS_ROOT / "staging" / staging_key / "Catalog_PDS.json"
    return staged.exists()


def start_pds_customization_resume_job(source_job_id: str) -> dict[str, Any]:
    """Continue an interrupted customization from its own working copy,
    instead of re-scanning everything from scratch."""
    existing = active_job_for_catalog("pds")
    if existing:
        raise RuntimeError(f"A PDS job is already active: {existing.get('job_id')}")
    source = load_job(source_job_id)
    if (
        not source
        or source.get("operation") != "catalog_customization"
        or source.get("status") not in {"cancelled", "failed"}
    ):
        raise RuntimeError(f"Customization job not resumable: {source_job_id}")
    # A chained resume (resuming a resume of a resume, ...) always points
    # back at the one original staging folder, never at an intermediate one.
    staging_key = str(source.get("resume_of") or source_job_id)
    if not customization_resumable(source_job_id):
        raise RuntimeError("No resumable working copy is available for this customization")

    job_id = f"pds-customize-resume-{uuid.uuid4().hex[:10]}"
    for name in ("active", "completed", "results", "logs", "staging"):
        (JOBS_ROOT / name).mkdir(parents=True, exist_ok=True)
    state = {
        "schema_version": 1, "job_id": job_id, "operation": "catalog_customization",
        "catalog": "pds", "status": "queued", "phase": "queued",
        "changes": source.get("changes") or {},
        "sol_start": int(source.get("sol_start") or 0), "sol_end": int(source.get("sol_end") or 0),
        "resume_of": staging_key,
        "resume_cameras_done": int(source.get("cameras_done") or 0),
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    job_state_path(job_id).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    command = [sys.executable, "-u", "-m", "catalog_manager.workers.customization_worker", "--job-id", job_id]
    log_handle = (JOBS_ROOT / "logs" / f"{job_id}.log").open("a", encoding="utf-8")
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS if os.name == "nt" else 0
    subprocess.Popen(
        command, cwd=str(PROJECT_ROOT), stdout=log_handle, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, close_fds=True, creationflags=creationflags,
    )
    log_handle.close()
    return state


def start_pds_json_rebuild_job() -> dict[str, Any]:
    """Launch a job that regenerates `Catalog_PDS.json` from the current `Catalog_PDS.parquet` (parquet is authoritative; see `core/pds_json_rebuild.py`)."""
    existing = active_job_for_catalog("pds")
    if existing:
        raise RuntimeError(f"A PDS job is already active: {existing.get('job_id')}")
    parquet = PROJECT_ROOT / "data" / "catalog" / "Catalog_PDS.parquet"
    if not parquet.exists():
        raise FileNotFoundError(f"PDS Parquet not found: {parquet}")
    job_id = f"pds-json-rebuild-{uuid.uuid4().hex[:10]}"
    for name in ("active", "completed", "logs"):
        (JOBS_ROOT / name).mkdir(parents=True, exist_ok=True)
    state = {
        "schema_version": 1,
        "job_id": job_id,
        "operation": "json_rebuild",
        "catalog": "pds",
        "status": "queued",
        "rows_done": 0,
        "rows_total": 0,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    path = job_state_path(job_id)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    command = [sys.executable, "-u", "-m", "catalog_manager.workers.json_rebuild_worker", "--job-id", job_id]
    log_handle = (JOBS_ROOT / "logs" / f"{job_id}.log").open("a", encoding="utf-8")
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS if os.name == "nt" else 0
    subprocess.Popen(
        command,
        cwd=str(PROJECT_ROOT),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creationflags,
    )
    log_handle.close()
    return state


def start_raw_json_rebuild_job() -> dict[str, Any]:
    """RAW-catalog counterpart of `start_pds_json_rebuild_job`."""
    existing = active_job_for_catalog("raw")
    if existing:
        raise RuntimeError(f"A RAW job is already active: {existing.get('job_id')}")
    parquet = PROJECT_ROOT / "data" / "catalog" / "Catalog_RawArch.parquet"
    if not parquet.exists():
        raise FileNotFoundError(f"RAW Parquet not found: {parquet}")
    job_id = f"raw-json-rebuild-{uuid.uuid4().hex[:10]}"
    for name in ("active", "completed", "logs"):
        (JOBS_ROOT / name).mkdir(parents=True, exist_ok=True)
    state = {
        "schema_version": 1,
        "job_id": job_id,
        "operation": "json_rebuild",
        "catalog": "raw",
        "status": "queued",
        "rows_done": 0,
        "rows_total": 0,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    job_state_path(job_id).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    command = [
        sys.executable, "-u", "-m", "catalog_manager.workers.json_rebuild_worker",
        "--job-id", job_id, "--catalog", "raw",
    ]
    log_handle = (JOBS_ROOT / "logs" / f"{job_id}.log").open("a", encoding="utf-8")
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS if os.name == "nt" else 0
    subprocess.Popen(
        command,
        cwd=str(PROJECT_ROOT),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creationflags,
    )
    log_handle.close()
    return state


def start_bootstrap_json_job() -> dict[str, Any]:
    """Launch the first-run job that generates both `Catalog_PDS.json` and `Catalog_RawArch.json` from their parquet files in one go (the "generate" choice from `bootstrap.py`'s onboarding prompt)."""
    existing = active_job_for_catalog("bootstrap")
    if existing:
        raise RuntimeError(f"A bootstrap job is already active: {existing.get('job_id')}")
    for filename in ("Catalog_PDS.parquet", "Catalog_RawArch.parquet"):
        path = PROJECT_ROOT / "data" / "catalog" / filename
        if not path.exists():
            raise FileNotFoundError(f"Required Parquet not found: {path}")
    job_id = f"bootstrap-json-{uuid.uuid4().hex[:10]}"
    for name in ("active", "completed", "logs"):
        (JOBS_ROOT / name).mkdir(parents=True, exist_ok=True)
    pds_rows = int(pq.ParquetFile(PROJECT_ROOT / "data" / "catalog" / "Catalog_PDS.parquet").metadata.num_rows)
    raw_rows = int(pq.ParquetFile(PROJECT_ROOT / "data" / "catalog" / "Catalog_RawArch.parquet").metadata.num_rows)
    state = {
        "schema_version": 1, "job_id": job_id, "operation": "bootstrap_json",
        "catalog": "bootstrap", "status": "queued", "phase": "pds",
        "rows_done": 0, "rows_total": pds_rows + raw_rows,
        "pds_rows": pds_rows, "raw_rows": raw_rows,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    job_state_path(job_id).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    command = [sys.executable, "-u", "-m", "catalog_manager.workers.bootstrap_worker", "--job-id", job_id]
    log_handle = (JOBS_ROOT / "logs" / f"{job_id}.log").open("a", encoding="utf-8")
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS if os.name == "nt" else 0
    subprocess.Popen(
        command, cwd=str(PROJECT_ROOT), stdout=log_handle, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, close_fds=True, creationflags=creationflags,
    )
    log_handle.close()
    return state


def start_pds_failed_retry(source_job_id: str) -> dict[str, Any]:
    """Re-run only the directories a `partial` PDS integrity check couldn't reach (network errors etc., recorded as `failed_locations`) -- narrower than re-running the whole Sol range."""
    existing = active_job_for_catalog("pds")
    if existing:
        raise RuntimeError(f"A PDS job is already active: {existing.get('job_id')}")

    source = load_job(source_job_id)
    if not source or source.get("status") != "partial" or not source.get("result_path"):
        raise RuntimeError("The selected check has no retryable partial result")
    result = _read_json(PROJECT_ROOT / str(source["result_path"]))
    failed = result.get("failed_locations") or []
    if not failed:
        raise RuntimeError("The selected check has no unchecked directories")

    camera = str(source["camera"])
    job_id = f"pds-integrity-retry-{camera}-{uuid.uuid4().hex[:10]}"
    for name in ("active", "completed", "results", "logs", "locks"):
        (JOBS_ROOT / name).mkdir(parents=True, exist_ok=True)
    state = {
        "schema_version": 1,
        "job_id": job_id,
        "operation": "integrity_check",
        "catalog": "pds",
        "camera": camera,
        "sol_start": int(source["sol_start"]),
        "sol_end": int(source["sol_end"]),
        "status": "queued",
        "retry_of": source_job_id,
        "retry_target_count": len(failed),
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    job_state_path(job_id).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    command = [
        sys.executable, "-u", "-m", "catalog_manager.workers.integrity_check_worker",
        "--job-id", job_id, "--catalog", "pds", "--camera", camera,
        "--sol-start", str(state["sol_start"]), "--sol-end", str(state["sol_end"]),
        "--retry-of", source_job_id,
    ]
    log_handle = (JOBS_ROOT / "logs" / f"{job_id}.log").open("a", encoding="utf-8")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen(
        command, cwd=PROJECT_ROOT, stdin=subprocess.DEVNULL,
        stdout=log_handle, stderr=subprocess.STDOUT,
        creationflags=creationflags, close_fds=True,
    )
    log_handle.close()
    return state


def start_pds_resume_job(source_job_id: str) -> dict[str, Any]:
    """Continue a `cancelled`/`failed` PDS integrity check from its saved checkpoint instead of re-scanning the whole Sol range from scratch."""
    existing = active_job_for_catalog("pds")
    if existing:
        raise RuntimeError(f"A PDS job is already active: {existing.get('job_id')}")
    source = load_job(source_job_id)
    checkpoint = JOBS_ROOT / "checkpoints" / f"{source_job_id}.json"
    if not source or source.get("status") not in {"cancelled", "failed"} or not checkpoint.exists():
        raise RuntimeError("No resumable checkpoint is available for this check")

    camera = str(source["camera"])
    job_id = f"pds-integrity-resume-{camera}-{uuid.uuid4().hex[:10]}"
    for name in ("active", "completed", "results", "logs", "locks", "checkpoints"):
        (JOBS_ROOT / name).mkdir(parents=True, exist_ok=True)
    state = {
        "schema_version": 1, "job_id": job_id, "operation": "integrity_check",
        "catalog": "pds", "camera": camera,
        "sol_start": int(source["sol_start"]), "sol_end": int(source["sol_end"]),
        "status": "queued", "resume_of": source_job_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    job_state_path(job_id).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    command = [
        sys.executable, "-u", "-m", "catalog_manager.workers.integrity_check_worker",
        "--job-id", job_id, "--catalog", "pds", "--camera", camera,
        "--sol-start", str(state["sol_start"]), "--sol-end", str(state["sol_end"]),
        "--resume-of", source_job_id,
    ]
    log_handle = (JOBS_ROOT / "logs" / f"{job_id}.log").open("a", encoding="utf-8")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen(
        command, cwd=PROJECT_ROOT, stdin=subprocess.DEVNULL,
        stdout=log_handle, stderr=subprocess.STDOUT,
        creationflags=creationflags, close_fds=True,
    )
    log_handle.close()
    return state


def start_raw_failed_retry(source_job_id: str) -> dict[str, Any]:
    """RAW-catalog counterpart of `start_pds_failed_retry`."""
    existing = active_job_for_catalog("raw")
    if existing:
        raise RuntimeError(f"A RAW job is already active: {existing.get('job_id')}")

    source = load_job(source_job_id)
    if not source or source.get("status") != "partial" or not source.get("result_path"):
        raise RuntimeError("The selected check has no retryable partial result")
    result = _read_json(PROJECT_ROOT / str(source["result_path"]))
    failed = result.get("failed_locations") or []
    if not failed:
        raise RuntimeError("The selected check has no unchecked directories")

    camera = str(source["camera"])
    job_id = f"raw-integrity-retry-{camera}-{uuid.uuid4().hex[:10]}"
    for name in ("active", "completed", "results", "logs", "locks"):
        (JOBS_ROOT / name).mkdir(parents=True, exist_ok=True)
    state = {
        "schema_version": 1,
        "job_id": job_id,
        "operation": "integrity_check",
        "catalog": "raw",
        "camera": camera,
        "sol_start": int(source["sol_start"]),
        "sol_end": int(source["sol_end"]),
        "status": "queued",
        "retry_of": source_job_id,
        "retry_target_count": len(failed),
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    job_state_path(job_id).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    command = [
        sys.executable, "-u", "-m", "catalog_manager.workers.integrity_check_worker",
        "--job-id", job_id, "--catalog", "raw", "--camera", camera,
        "--sol-start", str(state["sol_start"]), "--sol-end", str(state["sol_end"]),
        "--retry-of", source_job_id,
    ]
    log_handle = (JOBS_ROOT / "logs" / f"{job_id}.log").open("a", encoding="utf-8")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen(
        command, cwd=PROJECT_ROOT, stdin=subprocess.DEVNULL,
        stdout=log_handle, stderr=subprocess.STDOUT,
        creationflags=creationflags, close_fds=True,
    )
    log_handle.close()
    return state


def start_raw_resume_job(source_job_id: str) -> dict[str, Any]:
    """RAW-catalog counterpart of `start_pds_resume_job`."""
    existing = active_job_for_catalog("raw")
    if existing:
        raise RuntimeError(f"A RAW job is already active: {existing.get('job_id')}")
    source = load_job(source_job_id)
    checkpoint = JOBS_ROOT / "checkpoints" / f"{source_job_id}.json"
    if not source or source.get("status") not in {"cancelled", "failed"} or not checkpoint.exists():
        raise RuntimeError("No resumable checkpoint is available for this check")

    camera = str(source["camera"])
    job_id = f"raw-integrity-resume-{camera}-{uuid.uuid4().hex[:10]}"
    for name in ("active", "completed", "results", "logs", "locks", "checkpoints"):
        (JOBS_ROOT / name).mkdir(parents=True, exist_ok=True)
    state = {
        "schema_version": 1, "job_id": job_id, "operation": "integrity_check",
        "catalog": "raw", "camera": camera,
        "sol_start": int(source["sol_start"]), "sol_end": int(source["sol_end"]),
        "status": "queued", "resume_of": source_job_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    job_state_path(job_id).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    command = [
        sys.executable, "-u", "-m", "catalog_manager.workers.integrity_check_worker",
        "--job-id", job_id, "--catalog", "raw", "--camera", camera,
        "--sol-start", str(state["sol_start"]), "--sol-end", str(state["sol_end"]),
        "--resume-of", source_job_id,
    ]
    log_handle = (JOBS_ROOT / "logs" / f"{job_id}.log").open("a", encoding="utf-8")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen(
        command, cwd=PROJECT_ROOT, stdin=subprocess.DEVNULL,
        stdout=log_handle, stderr=subprocess.STDOUT,
        creationflags=creationflags, close_fds=True,
    )
    log_handle.close()
    return state


def request_cancel(job_id: str) -> None:
    """Ask `job_id`'s worker to stop cooperatively by dropping a `.cancel` sentinel file next to its state file (the worker polls for this between units of work)."""
    state = load_job(job_id)
    if not state:
        raise FileNotFoundError(job_id)
    cancel_path = JOBS_ROOT / "active" / f"{job_id}.cancel"
    cancel_path.write_text("cancel requested\n", encoding="utf-8")
