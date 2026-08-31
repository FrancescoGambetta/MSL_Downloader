"""The `bootstrap_json` worker: first-run job that generates both `Catalog_PDS.json`
and `Catalog_RawArch.json` from their parquet files in one pass, driven by
`jobs.start_bootstrap_json_job` when the user chooses "generate" on
`bootstrap.py`'s first-run prompt. Only runs the pds/raw JSON rebuild for whichever
file doesn't already exist -- reruns are cheap no-ops for a file already generated.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from core.pds_json_rebuild import rebuild_pds_json
from core.raw_json_rebuild import rebuild_raw_json_streaming


ROOT = Path(__file__).resolve().parent.parent.parent  # project root (this file lives in catalog_manager/workers/)
JOBS = ROOT / "data" / "catalog" / "jobs"


def _write(path: Path, state: dict[str, Any]) -> None:
    """Write `state` to `path` atomically (temp file + `os.replace`), retrying briefly on Windows `PermissionError` (a concurrent reader holding a transient file lock)."""
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for attempt in range(40):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            time.sleep(min(0.5, 0.025 * (attempt + 1)))
    os.replace(temporary, path)


def main() -> None:
    """Entry point: load this job's state, rebuild whichever of the PDS/RAW JSON files is missing (reporting combined-rows progress across both), and move the state file to `completed/`."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    active = JOBS / "active" / f"{args.job_id}.json"
    completed = JOBS / "completed" / f"{args.job_id}.json"
    state = json.loads(active.read_text(encoding="utf-8"))
    pds_parquet = ROOT / "data" / "catalog" / "Catalog_PDS.parquet"
    raw_parquet = ROOT / "data" / "catalog" / "Catalog_RawArch.parquet"
    pds_rows = int(state.get("pds_rows") or pq.ParquetFile(pds_parquet).metadata.num_rows)
    raw_rows = int(state.get("raw_rows") or pq.ParquetFile(raw_parquet).metadata.num_rows)
    total_rows = pds_rows + raw_rows
    started = time.perf_counter()
    state.update({"status": "running", "started_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "pid": os.getpid()})
    _write(active, state)
    last_write = 0.0

    def update(phase: str, offset: int, rows: int, _total: int, camera: str) -> None:
        """Progress callback passed to `rebuild_pds_json`/`rebuild_raw_json_streaming`: update and persist the job state, throttled to twice a second (always writes on the final call)."""
        nonlocal last_write
        now = time.monotonic()
        overall = offset + rows
        if overall < total_rows and now - last_write < 0.5:
            return
        elapsed = time.perf_counter() - started
        rate = overall / elapsed if elapsed else 0.0
        state.update({
            "phase": phase, "camera": camera, "rows_done": overall,
            "rows_total": total_rows, "elapsed_seconds": elapsed,
            "estimated_remaining_seconds": (total_rows - overall) / rate if rate else None,
        })
        _write(active, state)
        last_write = now

    try:
        pds_path = ROOT / "data" / "catalog" / "Catalog_PDS.json"
        if not pds_path.exists():
            rebuild_pds_json(
                pds_parquet, pds_path,
                ROOT / "config" / "msl_catalog_config.json",
                lambda rows, total, camera: update("pds", 0, rows, total, camera),
            )
        update("raw", pds_rows, 0, raw_rows, "")
        raw_path = ROOT / "data" / "catalog" / "Catalog_RawArch.json"
        if not raw_path.exists():
            rebuild_raw_json_streaming(
                raw_parquet, raw_path,
                ROOT / "config" / "raw_catalog_schema.json",
                progress=lambda rows, total, camera: update("raw", pds_rows, rows, total, camera),
            )
        state.update({
            "status": "completed", "phase": "complete", "rows_done": total_rows,
            "elapsed_seconds": time.perf_counter() - started,
            "estimated_remaining_seconds": 0.0,
            "completed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
    except Exception as exc:  # noqa: BLE001
        state.update({
            "status": "failed", "error": f"{type(exc).__name__}: {exc}",
            "elapsed_seconds": time.perf_counter() - started,
            "completed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
    _write(active, state)
    completed.parent.mkdir(parents=True, exist_ok=True)
    os.replace(active, completed)


if __name__ == "__main__":
    main()
