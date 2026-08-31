"""The `repair` (PDS) worker: re-scans only the exact Sol locations a finished PDS
integrity check flagged as having missing products (via `--repair-locations-file`,
which skips the unified builder's normal discovery phase entirely), then installs the
repaired catalog atomically. Driven by `jobs.start_pds_repair_job`. See
`raw_repair_worker.py` for the RAW-catalog counterpart.
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
from core.make_msl_catalog import STOP_EVENT
from core.make_msl_pds_catalog import main as run_unified_builder


def _watch_cancel_file(job_id: str, stop_watching: threading.Event) -> None:
    """Background thread: poll for `job_id`'s `.cancel` sentinel file once a second and set the shared `STOP_EVENT` if it appears, so the unified builder stops cooperatively between Sols."""
    cancel_path = JOBS_ROOT / "active" / f"{job_id}.cancel"
    while not stop_watching.wait(1.0):
        if cancel_path.exists():
            STOP_EVENT.set()
            return


def utc_now() -> str:
    """Current UTC timestamp, ISO-8601 with second precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json_atomic(path: Path, payload: Any) -> None:
    """Write `payload` to `path` as JSON atomically (temp file + `os.replace`)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def camera_counts(path: Path) -> dict[str, int]:
    """Return `{camera: product_count}` for a catalog JSON at `path`."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(camera): len(section.get("products", []))
        for camera, section in (payload.get("cameras") or {}).items()
        if isinstance(section, dict)
    }


def camera_product_ids(path: Path, camera: str) -> set[str]:
    """Return the set of `product_id`s `camera` currently has in the catalog JSON at `path`."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    section = (payload.get("cameras") or {}).get(camera) or {}
    return {str(row.get("product_id")) for row in section.get("products", []) if row.get("product_id")}


def run(job_id: str) -> int:
    """Run the repair: build the exact list of Sol locations to re-scan from the integrity check's `missing_products`, re-scan just those via the unified builder, compare before/after product counts and IDs, and install atomically. Returns a process-style exit code (`0` completed, `1` failed, `2` cancelled)."""
    state_path = job_state_path(job_id)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    started = time.monotonic()

    def update(**values: Any) -> None:
        """Merge `values` into the job state, refresh the heartbeat/elapsed time, and persist."""
        state.update(values)
        state["heartbeat_at_utc"] = utc_now()
        state["elapsed_seconds"] = round(time.monotonic() - started, 2)
        write_json_atomic(state_path, state)

    staging = JOBS_ROOT / "staging" / job_id
    source_json = PROJECT_ROOT / "data" / "catalog" / "Catalog_PDS.json"
    source_parquet = PROJECT_ROOT / "data" / "catalog" / "Catalog_PDS.parquet"
    staged_json = staging / "Catalog_PDS.json"
    staged_parquet = staging / "Catalog_PDS.parquet"
    stop_watching = threading.Event()
    watcher = threading.Thread(target=_watch_cancel_file, args=(job_id, stop_watching), daemon=True)
    watcher.start()
    try:
        update(status="running", phase="loading_integrity_result", started_at_utc=utc_now(), pid=os.getpid())
        camera = str(state["camera"])

        integrity_job_id = str(state["integrity_job_id"])
        integrity_result_path = JOBS_ROOT / "results" / f"{integrity_job_id}.json"
        if not integrity_result_path.exists():
            raise RuntimeError(
                f"Integrity check result not found for job {integrity_job_id} (it may have been cleaned up)."
            )
        integrity_result = json.loads(integrity_result_path.read_text(encoding="utf-8"))
        missing_products = integrity_result.get("missing_products") or []
        if not missing_products:
            raise RuntimeError("The referenced integrity check has no missing products to repair.")

        # Multiple missing products often share the same Sol directory; only
        # each distinct location needs to be (re-)visited, not one request
        # per product.
        locations_by_url: dict[str, dict[str, Any]] = {}
        for item in missing_products:
            sol_url = str(item.get("sol_url") or "")
            if not sol_url or sol_url in locations_by_url:
                continue
            locations_by_url[sol_url] = {
                "sol": int(item.get("sol") or 0),
                "collection": str(item.get("collection") or ""),
                "data_root": "",
                "sol_dir_name": str(item.get("sol") or ""),
                "sol_url": sol_url,
            }
        target_locations = list(locations_by_url.values())
        sols = [loc["sol"] for loc in target_locations]
        sol_start, sol_end = min(sols), max(sols)

        staging.mkdir(parents=True, exist_ok=False)
        shutil.copy2(source_json, staged_json)
        shutil.copy2(source_parquet, staged_parquet)
        before = camera_counts(staged_json)

        repair_locations_path = staging / "repair_locations.json"
        write_json_atomic(repair_locations_path, {camera: target_locations})

        update(
            phase="scanning_nasa",
            baseline_counts=before,
            current_camera=camera,
            missing_requested=len(missing_products),
            locations_to_repair=len(target_locations),
            sol_start=sol_start,
            sol_end=sol_end,
        )
        argv = [
            "--output", str(staged_json), "--parquet-output", str(staged_parquet),
            "--sol-start", str(sol_start), "--sol-end", str(sol_end),
            "--cameras", camera,
            "--use-camera-rules",
            "--repair-locations-file", str(repair_locations_path),
        ]

        def progress_callback(event: dict[str, Any]) -> None:
            """Forward the unified builder's LBL/geo-enrichment progress events into the job state."""
            stage = event.get("stage")
            if stage in {"camera_geo_enrich", "lbl_progress"}:
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
        additions = {cam: max(0, after.get(cam, 0) - before.get(cam, 0)) for cam in sorted(after)}
        added_for_camera = additions.get(camera, 0)
        # Check the exact originally-missing product IDs against what's
        # actually in the repaired copy now, rather than inferring from a
        # count -- correct even if some were already resolved by something
        # else in the meantime, or legitimately don't match camera_rules.json.
        missing_ids = {str(item.get("product_id")) for item in missing_products if item.get("product_id")}
        present_ids = camera_product_ids(staged_json, camera)
        still_missing_ids = sorted(missing_ids - present_ids)
        result_payload = {
            "schema_version": 1, "job_id": job_id, "operation": "repair",
            "catalog": "pds", "camera": camera, "integrity_job_id": integrity_job_id,
            "sol_start": sol_start, "sol_end": sol_end,
            "locations_repaired": len(target_locations),
            "missing_requested": len(missing_products),
            "before_counts": before, "after_counts": after, "additions_by_camera": additions,
            "new_products": added_for_camera,
            "still_missing": len(still_missing_ids),
            "still_missing_product_ids": still_missing_ids,
            "generated_at_utc": utc_now(),
        }
        update(phase="installing_catalog")
        install_catalog_pair(staged_json, staged_parquet, source_json, source_parquet, job_id)
        result_payload["installed_at_utc"] = utc_now()
        result_path = JOBS_ROOT / "results" / f"{job_id}.json"
        write_json_atomic(result_path, result_payload)
        update(
            status="completed", phase="installed", completed_at_utc=utc_now(),
            result_path=str(result_path.relative_to(PROJECT_ROOT)), new_products=added_for_camera,
            still_missing=result_payload["still_missing"], additions_by_camera=additions,
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
    """CLI entry point: parse `--job-id` and run the repair."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    return run(parser.parse_args().job_id)


if __name__ == "__main__":
    raise SystemExit(main())
