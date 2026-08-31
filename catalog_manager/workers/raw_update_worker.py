"""The `catalog_update` (RAW) worker: scan `[sol_start, sol_end]` for one or more
cameras in a single run (unlike the PDS update worker, which is restricted to one
camera at a time -- the RAW builder has no per-camera `--include-*` filter concept to
keep separate), and install the result atomically. Driven by
`jobs.start_raw_update_job`.
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
from catalog_manager.services import record_camera_checked
from core.make_msl_raw_catalog import STOP_EVENT, main as run_raw_builder


def _watch_cancel_file(job_id: str, stop_watching: threading.Event) -> None:
    """Background thread: poll for `job_id`'s `.cancel` sentinel file once a second and set the shared `STOP_EVENT` if it appears, so the RAW builder stops cooperatively between Sols."""
    cancel_path = JOBS_ROOT / "active" / f"{job_id}.cancel"
    while not stop_watching.wait(1.0):
        if cancel_path.exists():
            STOP_EVENT.set()
            return


def now() -> str:
    """Current UTC timestamp, ISO-8601 with second precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def counts(path: Path) -> dict[str, int]:
    """Return `{camera: product_count}` for a catalog JSON at `path`."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(camera): len(section.get("products", [])) for camera, section in payload["cameras"].items()}


def run(job_id: str) -> int:
    """Run the update: copy the catalog to a staging area, scan `state`'s cameras+Sol range, compare before/after counts, install atomically, and record each updated camera's new checked-up-to Sol via `record_camera_checked`. Returns a process-style exit code (`0` completed, `1` failed, `2` cancelled)."""
    path = job_state_path(job_id)
    state = json.loads(path.read_text(encoding="utf-8"))
    started = time.monotonic()
    def update(**values: Any) -> None:
        """Merge `values` into the job state, refresh the heartbeat/elapsed time, and persist."""
        state.update(values); state["heartbeat_at_utc"] = now(); state["elapsed_seconds"] = round(time.monotonic() - started, 2)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); os.replace(temp, path)
    staging = JOBS_ROOT / "staging" / job_id
    staged_json = staging / "Catalog_RawArch.json"
    staged_parquet = staging / "Catalog_RawArch.parquet"
    stop_watching = threading.Event()
    watcher = threading.Thread(target=_watch_cancel_file, args=(job_id, stop_watching), daemon=True)
    watcher.start()
    try:
        update(status="running", phase="preparing_working_copy", started_at_utc=now(), pid=os.getpid())
        staging.mkdir(parents=True, exist_ok=False)
        shutil.copy2(PROJECT_ROOT / "data/catalog/Catalog_RawArch.json", staged_json)
        shutil.copy2(PROJECT_ROOT / "data/catalog/Catalog_RawArch.parquet", staged_parquet)
        before = counts(staged_json); update(phase="scanning_nasa", baseline_counts=before)
        code = run_raw_builder([
            "--output", str(staged_json), "--parquet-output", str(staged_parquet),
            "--sol-start", str(state["sol_start"]), "--sol-end", str(state["sol_end"]),
            "--cameras", *state["cameras"], "--workers", "8",
        ])
        if code == 2:
            update(status="cancelled", phase="cancelled", cancelled_at_utc=now())
            os.replace(path, JOBS_ROOT / "completed" / path.name)
            return 2
        if code != 0:
            raise RuntimeError(f"Unified RAW builder returned {code}")
        update(phase="validating_working_copy")
        after = counts(staged_json)
        additions = {camera: max(0, after.get(camera, 0) - before.get(camera, 0)) for camera in sorted(after)}
        result = {
            "schema_version": 1, "job_id": job_id, "operation": "catalog_update", "catalog": "raw",
            "sol_start": state["sol_start"], "sol_end": state["sol_end"], "before_counts": before,
            "after_counts": after, "additions_by_camera": additions, "new_products": sum(additions.values()),
            "staged_json": str(staged_json.relative_to(PROJECT_ROOT)),
            "staged_parquet": str(staged_parquet.relative_to(PROJECT_ROOT)), "generated_at_utc": now(),
        }
        update(phase="installing_catalog")
        target_json = PROJECT_ROOT / "data/catalog/Catalog_RawArch.json"
        target_parquet = PROJECT_ROOT / "data/catalog/Catalog_RawArch.parquet"
        install_catalog_pair(staged_json, staged_parquet, target_json, target_parquet, job_id)
        # Same bookkeeping pds_update_worker.py does after its install: this
        # run scanned NASA for every requested camera through sol_end, so
        # each one's "last checked" watermark needs to move up to it --
        # otherwise these cameras silently fall back to the heuristic in
        # _fallback_camera_checked(), which wrongly assumes every camera is
        # as current as the single most-advanced one.
        for camera in state["cameras"]:
            record_camera_checked(PROJECT_ROOT, "raw", str(camera), int(state["sol_end"]), target_parquet)
        result["installed_at_utc"] = now()
        result["installed_json"] = str(target_json.relative_to(PROJECT_ROOT))
        result["installed_parquet"] = str(target_parquet.relative_to(PROJECT_ROOT))
        result.pop("staged_json", None); result.pop("staged_parquet", None)
        result_path = JOBS_ROOT / "results" / f"{job_id}.json"
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        update(status="completed", phase="installed", completed_at_utc=now(), result_path=str(result_path.relative_to(PROJECT_ROOT)), new_products=result["new_products"], additions_by_camera=additions)
        os.replace(path, JOBS_ROOT / "completed" / path.name)
        return 0
    except Exception as exc:  # noqa: BLE001
        update(status="failed", phase="failed", error=f"{type(exc).__name__}: {exc}", failed_at_utc=now())
        os.replace(path, JOBS_ROOT / "completed" / path.name)
        return 1
    finally:
        stop_watching.set()


def main() -> int:
    """CLI entry point: parse `--job-id` and run the update."""
    parser = argparse.ArgumentParser(); parser.add_argument("--job-id", required=True)
    return run(parser.parse_args().job_id)


if __name__ == "__main__":
    raise SystemExit(main())
