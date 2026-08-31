"""Regenerates Catalog_PDS.json from Catalog_PDS.parquet -- the parquet is authoritative; the JSON is a derived, streamable view Catalog Manager displays/exports.

Used by `catalog_manager/workers/json_rebuild_worker.py` (the "Rebuild JSON" action)
whenever the JSON needs regenerating from scratch (e.g. after it's deleted
or judged stale), since normal catalog updates/repairs only ever touch the
parquet directly.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd


ProgressCallback = Callable[[int, int, str], None]


def _normalize(value: Any) -> Any:
    """Recursively coerce a pandas/numpy value to a plain JSON-safe Python value (NaN/NaT -> None, numpy scalars/arrays -> native, Timestamps -> ISO string)."""
    if value is None:
        return None
    try:
        missing = pd.isna(value)
        if isinstance(missing, (bool, np.bool_)) and bool(missing):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, np.generic):
        return _normalize(value.item())
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_normalize(item) for item in value]
    return value


def rebuild_pds_json(
    parquet_path: Path,
    output_path: Path,
    config_path: Path,
    progress: ProgressCallback | None = None,
    *,
    chunk_size: int = 5000,
) -> dict[str, Any]:
    """Stream `parquet_path` out to `output_path` as the canonical PDS catalog JSON, grouped by camera, writing in `chunk_size`-row batches to bound memory.

    Writes to a `.incoming` sibling file first and only atomically renames
    it onto `output_path` once the written record count matches the
    source frame's row count exactly (`os.fsync` before the rename, so a
    crash mid-write can never leave a corrupt/truncated file at the real
    path). Returns a small stats dict (`rows`, `camera_counts`,
    `size_bytes`, `elapsed_seconds`, `output`).
    """
    started = time.perf_counter()
    frame = pd.read_parquet(parquet_path)
    required = {"camera", "img_url", "product_id", "sol"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"PDS Parquet missing required columns: {missing}")
    if frame["img_url"].isna().any() or frame["img_url"].duplicated().any():
        raise ValueError("PDS Parquet has invalid canonical identities")

    frame = frame.sort_values(["camera", "sol", "product_id", "img_url"], kind="stable").reset_index(drop=True)
    total = int(len(frame))
    config = json.loads(config_path.read_text(encoding="utf-8"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    incoming = output_path.with_suffix(output_path.suffix + ".incoming")
    completed = 0
    camera_counts: dict[str, int] = {}
    header = {
        "catalog_version": 2,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mission": "MSL",
        "base_url": config.get("base_url"),
        "coord_url": config.get("coord_url"),
        "coord_local_path": config.get("coord_local_path"),
        "coord_downloaded_now": False,
        "coord_updated_now": False,
        "coord_sync_reason": "reconstructed_from_official_parquet",
    }
    try:
        with incoming.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write("{\n")
            for index, (key, value) in enumerate(header.items()):
                handle.write(f"  {json.dumps(key)}: {json.dumps(value, ensure_ascii=False)}")
                handle.write(",\n")
            handle.write('  "cameras": {\n')
            camera_names = [str(value) for value in frame["camera"].drop_duplicates().tolist()]
            for camera_index, camera in enumerate(camera_names):
                camera_frame = frame.loc[frame["camera"].astype(str).eq(camera)]
                camera_count = int(len(camera_frame))
                camera_counts[camera] = camera_count
                handle.write(f"    {json.dumps(camera)}: {{\n")
                handle.write(f'      "product_count": {camera_count},\n')
                handle.write('      "products": [\n')
                first_record = True
                for start in range(0, camera_count, max(1, chunk_size)):
                    chunk = camera_frame.iloc[start : start + chunk_size].drop(columns=["camera"])
                    records = [_normalize(record) for record in chunk.to_dict(orient="records")]
                    encoded = json.dumps(records, ensure_ascii=False, allow_nan=False, separators=(",", ":"))[1:-1]
                    if encoded:
                        if not first_record:
                            handle.write(",\n")
                        handle.write("        " + encoded)
                        first_record = False
                    completed += len(records)
                    if progress:
                        progress(completed, total, camera)
                handle.write("\n      ]\n")
                handle.write("    }")
                handle.write(",\n" if camera_index < len(camera_names) - 1 else "\n")
            handle.write("  }\n}\n")
            handle.flush()
            os.fsync(handle.fileno())
        if completed != total or sum(camera_counts.values()) != total:
            raise RuntimeError(f"JSON record count mismatch: expected {total}, wrote {completed}")
        os.replace(incoming, output_path)
    except Exception:
        incoming.unlink(missing_ok=True)
        raise
    return {
        "rows": total,
        "camera_counts": camera_counts,
        "size_bytes": output_path.stat().st_size,
        "elapsed_seconds": time.perf_counter() - started,
        "output": str(output_path),
    }
