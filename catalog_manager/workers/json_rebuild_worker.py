"""The `json_rebuild` worker (single catalog, on demand): regenerates one catalog's
JSON view (`Catalog_PDS.json` or `Catalog_RawArch.json`) from its parquet, driven by
`jobs.start_pds_json_rebuild_job`/`start_raw_json_rebuild_job` (the "Rebuild JSON"
dashboard action). Compare `bootstrap_worker.py`, which does both catalogs at once but
only on first run, skipping any file that already exists.
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

from core.pds_json_rebuild import rebuild_pds_json
from core.raw_json_rebuild import rebuild_raw_json_streaming


ROOT = Path(__file__).resolve().parent.parent.parent  # project root (this file lives in catalog_manager/workers/)
JOBS_ROOT = ROOT / "data" / "catalog" / "jobs"


def _replace_with_retry(source: Path, destination: Path, attempts: int = 40) -> None:
    """`os.replace` retrying briefly on Windows `PermissionError` (a concurrent reader holding a transient file lock)."""
    last_error: OSError | None = None
    for attempt in range(attempts):
        try:
            os.replace(source, destination)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(min(0.5, 0.025 * (attempt + 1)))
    if last_error is not None:
        raise last_error


def _write(path: Path, state: dict[str, Any]) -> None:
    """Write `state` to `path` atomically (temp file + `_replace_with_retry`)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        _replace_with_retry(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    """Entry point: load this job's state, rebuild `--catalog`'s JSON from its parquet with progress reporting, and move the state file to `completed/`."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--catalog", choices=("pds", "raw"), default="pds")
    args = parser.parse_args()
    active = JOBS_ROOT / "active" / f"{args.job_id}.json"
    completed_path = JOBS_ROOT / "completed" / f"{args.job_id}.json"
    state = json.loads(active.read_text(encoding="utf-8"))
    started = time.perf_counter()
    state.update({"status": "running", "started_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "pid": os.getpid()})
    _write(active, state)

    last_write = 0.0

    def progress(rows_done: int, rows_total: int, camera: str) -> None:
        """Progress callback passed to `rebuild_pds_json`/`rebuild_raw_json_streaming`: update and persist the job state, throttled to twice a second (always writes on the final call)."""
        nonlocal last_write
        now = time.monotonic()
        if rows_done < rows_total and now - last_write < 0.5:
            return
        elapsed = time.perf_counter() - started
        rate = rows_done / elapsed if elapsed else 0.0
        state.update(
            {
                "rows_done": rows_done,
                "rows_total": rows_total,
                "camera": camera,
                "elapsed_seconds": elapsed,
                "estimated_remaining_seconds": (rows_total - rows_done) / rate if rate else None,
            }
        )
        _write(active, state)
        last_write = now

    try:
        if args.catalog == "raw":
            result = rebuild_raw_json_streaming(
                ROOT / "data" / "catalog" / "Catalog_RawArch.parquet",
                ROOT / "data" / "catalog" / "Catalog_RawArch.json",
                ROOT / "config" / "raw_catalog_schema.json",
                progress=progress,
            )
        else:
            result = rebuild_pds_json(
                ROOT / "data" / "catalog" / "Catalog_PDS.parquet",
                ROOT / "data" / "catalog" / "Catalog_PDS.json",
                ROOT / "config" / "msl_catalog_config.json",
                progress,
            )
        state.update(result)
        state.update(
            {
                "status": "completed",
                "rows_done": result["rows"],
                "rows_total": result["rows"],
                "elapsed_seconds": time.perf_counter() - started,
                "completed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )
    except Exception as exc:  # noqa: BLE001
        state.update(
            {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_seconds": time.perf_counter() - started,
                "completed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )
    _write(active, state)
    completed_path.parent.mkdir(parents=True, exist_ok=True)
    _replace_with_retry(active, completed_path)


if __name__ == "__main__":
    main()
