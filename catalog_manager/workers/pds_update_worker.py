"""The `catalog_update` (PDS) worker: scan `[sol_start, sol_end]` for exactly one
camera, filtered by that camera's saved `config/camera_rules.json` rule
(`current_include_args`), and install the result atomically. One camera per run is
deliberate (see `jobs.start_pds_update_job`'s docstring). Driven by
`jobs.start_pds_update_job`. See `raw_update_worker.py` for the RAW-catalog
counterpart (which updates several cameras in one run instead of just one).
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

from catalog_manager.jobs import JOBS_ROOT, PROJECT_ROOT, job_state_path
from catalog_manager.catalog_install import install_catalog_pair
from catalog_manager.customization import current_include_args
from catalog_manager.services import record_camera_checked
from core.make_msl_catalog import STOP_EVENT
from core.make_msl_pds_catalog import main as run_unified_builder


def _watch_cancel_file(job_id: str, stop_watching: threading.Event) -> None:
    """Poll for the UI's cancel marker and translate it into STOP_EVENT.

    core/make_msl_catalog.py already checks STOP_EVENT cooperatively at many
    points (per Sol directory, per LBL candidate); this just gives the file
    dropped by jobs.request_cancel() a way to reach it from inside this
    separate worker process.
    """
    cancel_path = JOBS_ROOT / "active" / f"{job_id}.cancel"
    while not stop_watching.wait(1.0):
        if cancel_path.exists():
            STOP_EVENT.set()
            return


def utc_now() -> str:
    """Current UTC timestamp, ISO-8601 with second precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_state(path: Path, state: dict[str, Any]) -> None:
    """Write `state` to `path` as JSON atomically (temp file + `os.replace`)."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def camera_counts(path: Path) -> dict[str, int]:
    """Return `{camera: product_count}` for a catalog JSON at `path`."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(camera): len(section.get("products", []))
        for camera, section in (payload.get("cameras") or {}).items()
        if isinstance(section, dict)
    }


def run(job_id: str) -> int:
    """Run the update: copy the catalog to a staging area, scan `state`'s camera+Sol range filtered by its saved rule, compare before/after counts, install atomically, and record the new checked-up-to Sol via `record_camera_checked`. Returns a process-style exit code (`0` completed, `1` failed, `2` cancelled)."""
    state_path = job_state_path(job_id)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    started = time.monotonic()

    def update(**values: Any) -> None:
        """Merge `values` into the job state, refresh the heartbeat/elapsed time, and persist."""
        state.update(values)
        state["heartbeat_at_utc"] = utc_now()
        state["elapsed_seconds"] = round(time.monotonic() - started, 2)
        write_state(state_path, state)

    staging = JOBS_ROOT / "staging" / job_id
    source_json = PROJECT_ROOT / "data" / "catalog" / "Catalog_PDS.json"
    source_parquet = PROJECT_ROOT / "data" / "catalog" / "Catalog_PDS.parquet"
    staged_json = staging / "Catalog_PDS.json"
    staged_parquet = staging / "Catalog_PDS.parquet"
    stop_watching = threading.Event()
    watcher = threading.Thread(target=_watch_cancel_file, args=(job_id, stop_watching), daemon=True)
    watcher.start()
    try:
        update(status="running", phase="preparing_working_copy", started_at_utc=utc_now(), pid=os.getpid())
        staging.mkdir(parents=True, exist_ok=False)
        shutil.copy2(source_json, staged_json)
        shutil.copy2(source_parquet, staged_parquet)
        before = camera_counts(staged_json)
        camera = str(state["camera"])

        # The scanner applies config/camera_rules.json's PDS rule directly
        # (--use-camera-rules, reusing the exact _record_is_allowed()
        # function the integrity check verifies against) -- so widening or
        # narrowing a camera's rule there takes effect on the very next
        # update, with no separate translation to keep in sync. ChemCam has
        # no filterable dimensions in this scheme (its own builder already
        # restricts to CR0/PRC), so it legitimately has no rule here.
        if camera != "chemcam" and not current_include_args(camera):
            raise RuntimeError(
                f"No PDS rule found for '{camera}' in config/camera_rules.json. Refusing to run an "
                "unfiltered update; define what this camera should contain there first."
            )

        update(phase="scanning_nasa", baseline_counts=before, current_camera=camera)
        argv = [
            "--output", str(staged_json), "--parquet-output", str(staged_parquet),
            "--sol-start", str(state["sol_start"]), "--sol-end", str(state["sol_end"]),
            "--cameras", camera,
        ]
        if camera != "chemcam":
            argv.append("--use-camera-rules")

        def progress_callback(event: dict[str, Any]) -> None:
            """Forward the unified builder's LBL/geo-enrichment progress events into the job state."""
            stage = event.get("stage")
            if stage == "camera_geo_enrich":
                update(
                    phase="enriching_metadata",
                    current_camera=event.get("camera"),
                    lbl_candidates_done=event.get("lbl_done"),
                    lbl_candidates_total=event.get("lbl_total"),
                )
            elif stage == "lbl_progress":
                update(
                    phase="enriching_metadata",
                    current_camera=event.get("camera"),
                    lbl_candidates_done=event.get("lbl_done"),
                    lbl_candidates_total=event.get("lbl_total"),
                )

        result = run_unified_builder(argv, progress_callback=progress_callback)
        if result == 2:
            update(status="cancelled", phase="cancelled", cancelled_at_utc=utc_now())
            completed = JOBS_ROOT / "completed" / state_path.name
            os.replace(state_path, completed)
            return 2
        if result != 0:
            raise RuntimeError(f"Unified PDS builder returned {result}")
        update(phase="validating_working_copy")
        after = camera_counts(staged_json)
        additions = {camera: max(0, after.get(camera, 0) - before.get(camera, 0)) for camera in sorted(after)}
        result_payload = {
            "schema_version": 1, "job_id": job_id, "operation": "catalog_update",
            "catalog": "pds", "sol_start": state["sol_start"], "sol_end": state["sol_end"],
            "before_counts": before, "after_counts": after, "additions_by_camera": additions,
            "new_products": sum(additions.values()),
            "staged_json": str(staged_json.relative_to(PROJECT_ROOT)),
            "staged_parquet": str(staged_parquet.relative_to(PROJECT_ROOT)),
            "generated_at_utc": utc_now(),
        }
        update(phase="installing_catalog")
        install_catalog_pair(staged_json, staged_parquet, source_json, source_parquet, job_id)
        record_camera_checked(PROJECT_ROOT, "pds", camera, int(state["sol_end"]), source_parquet)
        result_payload["installed_at_utc"] = utc_now()
        result_payload["installed_json"] = str(source_json.relative_to(PROJECT_ROOT))
        result_payload["installed_parquet"] = str(source_parquet.relative_to(PROJECT_ROOT))
        result_payload.pop("staged_json", None)
        result_payload.pop("staged_parquet", None)
        result_path = JOBS_ROOT / "results" / f"{job_id}.json"
        result_path.write_text(json.dumps(result_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        update(
            status="completed", phase="installed", completed_at_utc=utc_now(),
            result_path=str(result_path.relative_to(PROJECT_ROOT)), new_products=result_payload["new_products"],
            additions_by_camera=additions,
        )
        completed = JOBS_ROOT / "completed" / state_path.name
        os.replace(state_path, completed)
        return 0
    except Exception as exc:  # noqa: BLE001
        update(status="failed", phase="failed", error=f"{type(exc).__name__}: {exc}", failed_at_utc=utc_now())
        completed = JOBS_ROOT / "completed" / state_path.name
        os.replace(state_path, completed)
        return 1
    finally:
        stop_watching.set()


def main() -> int:
    """CLI entry point: parse `--job-id` and run the update."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    return run(parser.parse_args().job_id)


if __name__ == "__main__":
    raise SystemExit(main())
