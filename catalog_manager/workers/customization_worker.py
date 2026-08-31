"""The `catalog_customization` worker: apply a per-camera product-type/processing-level
"shopping list" to the PDS catalog. Two phases per camera: a cheap local filter first
(drop products that don't match, always), then -- only if the selection asks for
combinations not already present locally -- one NASA scan per camera to fetch what's
missing, followed by re-applying the exact same local filter to the freshly scanned
data (since a scan's `--include-*` flags are necessarily broader than the exact
combination requested, to avoid one NASA request per combination). Supports resuming
an interrupted attempt from its own staging folder via `jobs.start_pds_customization_resume_job`.
Driven by `jobs.start_pds_customization_job`/`start_pds_customization_resume_job`.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from catalog_manager.catalog_install import install_catalog_pair
from catalog_manager.customization import filter_camera_selection, include_args_for_camera
from catalog_manager.jobs import JOBS_ROOT, PROJECT_ROOT, job_state_path
from core.make_msl_catalog import STOP_EVENT
from core.make_msl_pds_catalog import _canonical_frame, main as run_builder


def _watch_cancel_file(job_id: str, stop_watching: threading.Event) -> None:
    """Background thread: poll for `job_id`'s `.cancel` sentinel file once a second and set the shared `STOP_EVENT` if it appears, so the builder stops cooperatively between Sols."""
    cancel_path = JOBS_ROOT / "active" / f"{job_id}.cancel"
    while not stop_watching.wait(1.0):
        if cancel_path.exists():
            STOP_EVENT.set()
            return


def now() -> str:
    """Current UTC timestamp, ISO-8601 with second precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, payload: Any) -> None:
    """Write `payload` to `path` as JSON atomically (temp file + `os.replace`)."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def counts(payload: dict[str, Any]) -> dict[str, int]:
    """Return `{camera: product_count}` for a loaded catalog JSON payload."""
    return {
        str(camera): len(section.get("products", []))
        for camera, section in (payload.get("cameras") or {}).items() if isinstance(section, dict)
    }


def run(job_id: str) -> int:
    """Run the customization: local-filter every camera's selection, scan NASA for any camera whose selection needs data not already present, re-filter, then install atomically. Returns a process-style exit code (`0` completed, `1` failed, `2` cancelled)."""
    state_path = job_state_path(job_id)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    started = time.monotonic()
    state_lock = threading.Lock()

    def update(**values: Any) -> None:
        """Merge `values` into the job state, refresh the heartbeat/elapsed time, and persist (lock-protected: also called from the heartbeat thread)."""
        with state_lock:
            state.update(values)
            state["heartbeat_at_utc"] = now()
            state["elapsed_seconds"] = round(time.monotonic() - started, 2)
            write_json(state_path, state)

    source_json = PROJECT_ROOT / "data/catalog/Catalog_PDS.json"
    source_parquet = PROJECT_ROOT / "data/catalog/Catalog_PDS.parquet"
    # A resume job shares its ORIGINAL job's staging folder (not its own new
    # job_id) -- that folder is exactly what a "Riprendi" attempt needs to
    # find: the working copy already carries whatever an earlier interrupted
    # attempt had applied and scanned.
    resume_of = state.get("resume_of")
    staging_key = str(resume_of) if resume_of else job_id
    staging = JOBS_ROOT / "staging" / staging_key
    staged_json = staging / source_json.name
    staged_parquet = staging / source_parquet.name
    work_dir = staging / "unified_work"
    resuming = bool(resume_of) and staged_json.exists() and staged_parquet.exists()
    stop_watching = threading.Event()
    watcher = threading.Thread(target=_watch_cancel_file, args=(job_id, stop_watching), daemon=True)
    watcher.start()
    try:
        update(status="running", phase="preparing_working_copy", started_at_utc=now(), pid=os.getpid())
        staging.mkdir(parents=True, exist_ok=True)
        if not resuming:
            shutil.copy2(source_json, staged_json)
            shutil.copy2(source_parquet, staged_parquet)
        # The baseline for the added/removed counts reported at the end must
        # always be the real, untouched catalog -- not the staged copy, which
        # on a resumed attempt already carries earlier progress.
        before = counts(json.loads(source_json.read_text(encoding="utf-8")))
        payload = json.loads(staged_json.read_text(encoding="utf-8"))
        changes = state.get("changes") or {}

        update(phase="applying_local_filters")
        removed: dict[str, int] = {}
        missing_levels: dict[str, list[str]] = {}
        remote_changes: dict[str, dict[str, list[str]]] = {}
        for camera, combinations in changes.items():
            removed_count, existing = filter_camera_selection(payload, camera, combinations)
            missing_levels[camera] = sorted(
                f"{primary}:{secondary}"
                for primary, secondary_values in combinations.items()
                for secondary in secondary_values if str(secondary).upper() not in existing.get(primary, set())
            )
            if any(
                str(secondary).upper() not in existing.get(primary, set())
                for primary, secondary_values in combinations.items()
                for secondary in secondary_values
            ):
                # Only one NASA scan per camera. The exact filter is
                # reapplied after the builder to avoid cross-contaminated products.
                remote_changes[camera] = {
                    str(primary): list(secondary_values)
                    for primary, secondary_values in combinations.items()
                }
            removed[camera] = removed_count
        write_json(staged_json, payload)

        # Local-only changes still need a matching Parquet, but no NASA request.
        schema = PROJECT_ROOT / "config/pds_catalog_schema.json"
        _canonical_frame(payload, schema).to_parquet(staged_parquet, index=False)

        remote_items = list(remote_changes.items())
        # A camera whose scan already finished (and got merged + re-filtered
        # into staged_json) in an earlier attempt doesn't need repeating --
        # only the one that was actually interrupted, and whatever came
        # after it, do.
        resume_from = int(state.get("resume_cameras_done") or 0) if resuming else 0
        for index, (camera, combinations) in enumerate(remote_items, start=1):
            if index <= resume_from:
                continue
            update(phase="scanning_nasa", current_camera=camera, cameras_done=index - 1, cameras_total=len(remote_changes))
            argv = [
                "--output", str(staged_json), "--parquet-output", str(staged_parquet),
                "--sol-start", str(state["sol_start"]), "--sol-end", str(state["sol_end"]),
                "--cameras", camera,
                "--work-dir", str(work_dir),
            ]
            argv += include_args_for_camera(camera, combinations)
            if camera == "chemcam":
                raise ValueError("ChemCam currently exposes its only supported CR0/PRC combination and cannot be changed")
            heartbeat_stop = threading.Event()
            def heartbeat() -> None:
                """Keep the job's heartbeat fresh every 10s while the NASA scan runs (the scan itself may go a while between its own progress events)."""
                while not heartbeat_stop.wait(10.0):
                    update(current_camera=camera, heartbeat_note="NASA scan active")
            heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
            heartbeat_thread.start()

            def progress_callback(event: dict[str, Any], _camera: str = camera) -> None:
                """Forward the builder's LBL/geo-enrichment progress events into the job state."""
                if event.get("stage") in {"camera_geo_enrich", "lbl_progress"}:
                    update(
                        phase="enriching_metadata",
                        current_camera=_camera,
                        lbl_candidates_done=event.get("lbl_done"),
                        lbl_candidates_total=event.get("lbl_total"),
                    )

            try:
                code = run_builder(argv, progress_callback=progress_callback)
            finally:
                heartbeat_stop.set()
                heartbeat_thread.join(timeout=2.0)
            if code == 2:
                update(status="cancelled", phase="cancelled", cancelled_at_utc=now())
                os.replace(state_path, JOBS_ROOT / "completed" / state_path.name)
                return 2
            if code != 0:
                raise RuntimeError(f"PDS builder returned {code} for {camera}")

            # Merging the filters allows a single directory visit; this
            # second filter keeps exclusively the requested pairs.
            payload = json.loads(staged_json.read_text(encoding="utf-8"))
            filter_camera_selection(payload, camera, combinations)
            write_json(staged_json, payload)
            _canonical_frame(payload, schema).to_parquet(staged_parquet, index=False)
            update(cameras_done=index)

        update(phase="validating_working_copy")
        final_payload = json.loads(staged_json.read_text(encoding="utf-8"))
        after = counts(final_payload)
        added = {camera: max(0, after.get(camera, 0) - (before.get(camera, 0) - removed.get(camera, 0))) for camera in changes}
        update(phase="installing_catalog")
        install_catalog_pair(staged_json, staged_parquet, source_json, source_parquet, job_id)
        result = {
            "schema_version": 1, "job_id": job_id, "operation": "catalog_customization",
            "catalog": "pds", "changes": changes, "removed_by_camera": removed,
            "added_by_camera": added, "before_counts": before, "after_counts": after,
            "installed_at_utc": now(),
        }
        result_path = JOBS_ROOT / "results" / f"{job_id}.json"
        write_json(result_path, result)
        update(status="completed", phase="installed", completed_at_utc=now(), result_path=str(result_path.relative_to(PROJECT_ROOT)), removed_by_camera=removed, added_by_camera=added)
        os.replace(state_path, JOBS_ROOT / "completed" / state_path.name)
        # Everything is installed now; the working copy has served its
        # purpose and, unlike on a cancellation, there is nothing left to
        # resume.
        shutil.rmtree(staging, ignore_errors=True)
        return 0
    except Exception as exc:  # noqa: BLE001
        update(status="failed", phase="failed", error=f"{type(exc).__name__}: {exc}", failed_at_utc=now())
        os.replace(state_path, JOBS_ROOT / "completed" / state_path.name)
        return 1
    finally:
        stop_watching.set()


def main() -> int:
    """CLI entry point: parse `--job-id` and run the customization."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    return run(parser.parse_args().job_id)


if __name__ == "__main__":
    raise SystemExit(main())
