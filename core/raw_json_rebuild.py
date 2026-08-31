"""Streaming, memory-bounded conversion between Catalog_RawArch.parquet and its JSON view, in both directions.

`rebuild_raw_json_streaming` (parquet -> JSON) is the RAW counterpart to
`pds_json_rebuild.rebuild_pds_json`, with the same "write to `.incoming`,
fsync, atomic rename" safety pattern -- used by `json_rebuild_worker.py`'s
"Rebuild JSON" action. `raw_json_to_parquet_streaming` (JSON -> parquet) is
the one place in this codebase that goes the other way; its line-by-line
reader (`iter_raw_json_records`) depends on the JSON having exactly the
formatting `rebuild_raw_json_streaming` writes (one `"camera": {` header
line per section, one compact record object per line) -- it's not a
general JSON parser.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


ProgressCallback = Callable[[int, int, str], None]
CAMERA_ORDER = ("chemcam", "hazcam", "mahli", "mardi", "mastcam", "navcam")
RAW_MANIFEST_URL = "https://mars.jpl.nasa.gov/msl-raw-images/image/image_manifest.json"


def _normalize(value: Any) -> Any:
    """Recursively coerce a pandas/numpy value to a plain JSON-safe Python value (NaN/NaT -> None, numpy scalars -> native, Timestamps -> ISO string)."""
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
    return value


def load_schema(schema_path: Path) -> tuple[list[str], dict[str, str]]:
    """Load `raw_catalog_schema.json`'s column list and their dtypes as `(columns, {column: dtype})`."""
    payload = json.loads(schema_path.read_text(encoding="utf-8"))
    definitions = payload["columns"]
    return [str(item["name"]) for item in definitions], {str(item["name"]): str(item["dtype"]) for item in definitions}


def apply_schema(frame: pd.DataFrame, columns: list[str], dtypes: dict[str, str]) -> pd.DataFrame:
    """Reorder/cast `frame` to exactly `columns` with their declared `dtypes`; raises if any column is missing or unexpected."""
    missing = [column for column in columns if column not in frame]
    extra = [column for column in frame if column not in columns]
    if missing or extra:
        raise ValueError(f"RAW schema mismatch: missing={missing}, extra={extra}")
    frame = frame.copy()
    for column in columns:
        frame[column] = frame[column].astype(dtypes[column])
    return frame[columns]


def _encoded_record(record: dict[str, Any]) -> str:
    """Serialize one product record as a single-line, sorted-keys compact JSON object (deterministic, so its hash is stable across rebuilds)."""
    return json.dumps(_normalize(record), ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)


def rebuild_raw_json_streaming(
    parquet_path: Path,
    output_path: Path,
    schema_path: Path,
    progress: ProgressCallback | None = None,
    *,
    sol_start: int | None = None,
    sol_end: int | None = None,
    chunk_size: int = 5000,
) -> dict[str, Any]:
    """Stream `parquet_path` out to `output_path` as the canonical RAW Archive catalog JSON, grouped by camera (optionally restricted to a Sol range), writing in `chunk_size`-row batches.

    Same atomic-write pattern as `pds_json_rebuild.rebuild_pds_json` (write
    to `.incoming`, fsync, rename only after the written count matches).
    Also accumulates a SHA-256 of every encoded record line, so callers can
    detect whether a rebuild actually changed anything. Returns a stats
    dict (`rows`, `camera_counts`, `record_sha256`, `size_bytes`,
    `elapsed_seconds`, `output`).
    """
    started = time.perf_counter()
    columns, dtypes = load_schema(schema_path)
    index = pd.read_parquet(parquet_path, columns=["camera", "sol"])
    numeric_sol = pd.to_numeric(index["sol"], errors="coerce")
    mask = pd.Series(True, index=index.index)
    if sol_start is not None:
        mask &= numeric_sol.ge(sol_start)
    if sol_end is not None:
        mask &= numeric_sol.le(sol_end)
    selected_index = index.loc[mask]
    counts = {str(camera): int(count) for camera, count in selected_index["camera"].value_counts().items()}
    total = int(sum(counts.values()))
    del index, numeric_sol, mask, selected_index

    output_path.parent.mkdir(parents=True, exist_ok=True)
    incoming = output_path.with_suffix(output_path.suffix + ".incoming")
    digest = hashlib.sha256()
    completed = 0
    cameras = [camera for camera in CAMERA_ORDER if counts.get(camera, 0)]
    try:
        with incoming.open("w", encoding="utf-8", newline="\n") as handle:
            header = {
                "catalog_version": 2,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "mission": "MSL",
                "base_url": RAW_MANIFEST_URL,
                "catalog_kind": "raw_archive_reconstructed_from_official_parquet",
            }
            handle.write("{\n")
            for key, value in header.items():
                handle.write(f"  {json.dumps(key)}: {json.dumps(value, ensure_ascii=False)},\n")
            handle.write('  "cameras": {\n')
            for camera_index, camera in enumerate(cameras):
                filters: list[tuple[str, str, Any]] = [("camera", "=", camera)]
                camera_frame = pd.read_parquet(parquet_path, filters=filters)
                sols = pd.to_numeric(camera_frame["sol"], errors="coerce")
                camera_mask = pd.Series(True, index=camera_frame.index)
                if sol_start is not None:
                    camera_mask &= sols.ge(sol_start)
                if sol_end is not None:
                    camera_mask &= sols.le(sol_end)
                camera_frame = camera_frame.loc[camera_mask]
                camera_frame = apply_schema(camera_frame, columns, dtypes)
                camera_frame = camera_frame.sort_values(["sol", "product_id", "img_url"], kind="stable").reset_index(drop=True)
                expected = counts[camera]
                if len(camera_frame) != expected:
                    raise RuntimeError(f"RAW camera count mismatch for {camera}: {len(camera_frame)} != {expected}")
                handle.write(f"    {json.dumps(camera)}: {{\n")
                handle.write(f'      "product_count": {expected},\n')
                handle.write('      "products": [\n')
                for start in range(0, expected, max(1, chunk_size)):
                    chunk = camera_frame.iloc[start : start + chunk_size].drop(columns=["camera"])
                    records = chunk.to_dict(orient="records")
                    for offset, record in enumerate(records):
                        encoded = _encoded_record(record)
                        is_last = start + offset + 1 == expected
                        handle.write(f"        {encoded}{'' if is_last else ','}\n")
                        digest.update(encoded.encode("utf-8"))
                        digest.update(b"\n")
                    completed += len(records)
                    if progress:
                        progress(completed, total, camera)
                handle.write("      ]\n")
                handle.write("    }")
                handle.write(",\n" if camera_index < len(cameras) - 1 else "\n")
                del camera_frame
            handle.write("  }\n}\n")
            handle.flush()
            os.fsync(handle.fileno())
        if completed != total:
            raise RuntimeError(f"RAW JSON count mismatch: {completed} != {total}")
        os.replace(incoming, output_path)
    except Exception:
        incoming.unlink(missing_ok=True)
        raise
    return {
        "rows": total,
        "camera_counts": counts,
        "record_sha256": digest.hexdigest(),
        "size_bytes": output_path.stat().st_size,
        "elapsed_seconds": time.perf_counter() - started,
        "output": str(output_path),
    }


def iter_raw_json_records(json_path: Path) -> Iterator[tuple[str, dict[str, Any], str]]:
    """Yield `(camera, record_dict, raw_encoded_line)` for every product in a RAW catalog JSON written by `rebuild_raw_json_streaming`.

    Line-based, not a real JSON parser -- relies on that function's exact
    output formatting (one `"<camera>": {` line per section header, one
    compact record object per subsequent line) to read the file without
    ever holding the whole multi-GB JSON in memory.
    """
    current_camera = ""
    with json_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("    ") and not line.startswith("        ") and '": {' in line:
                key_text = line.strip().split(":", 1)[0]
                current_camera = str(json.loads(key_text))
                continue
            if not line.startswith("        {"):
                continue
            encoded = line.strip()
            if encoded.endswith(","):
                encoded = encoded[:-1]
            record = json.loads(encoded)
            yield current_camera, record, encoded


def raw_json_to_parquet_streaming(
    json_path: Path,
    parquet_path: Path,
    schema_path: Path,
    *,
    chunk_size: int = 10000,
) -> dict[str, Any]:
    """Stream-convert a RAW catalog JSON (written by `rebuild_raw_json_streaming`) back into a parquet file, buffering `chunk_size` records at a time between `ParquetWriter.write_table` calls.

    Same atomic-write pattern as the other functions here. Raises if the
    JSON has zero products, or a product line appears before any camera
    header.
    """
    columns, dtypes = load_schema(schema_path)
    digest = hashlib.sha256()
    camera_counts: dict[str, int] = {}
    buffer: list[dict[str, Any]] = []
    writer: pq.ParquetWriter | None = None
    rows = 0
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    incoming = parquet_path.with_suffix(parquet_path.suffix + ".incoming")

    def flush() -> None:
        nonlocal writer, buffer
        if not buffer:
            return
        frame = apply_schema(pd.DataFrame(buffer), columns, dtypes)
        table = pa.Table.from_pandas(frame, preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(incoming, table.schema, compression="snappy")
        writer.write_table(table)
        buffer = []

    try:
        for camera, record, encoded in iter_raw_json_records(json_path):
            if not camera:
                raise ValueError("RAW JSON product found outside a camera section")
            digest.update(encoded.encode("utf-8"))
            digest.update(b"\n")
            camera_counts[camera] = camera_counts.get(camera, 0) + 1
            buffer.append({**record, "camera": camera})
            rows += 1
            if len(buffer) >= chunk_size:
                flush()
        flush()
        if writer is None:
            raise ValueError("RAW JSON contains no products")
        writer.close()
        writer = None
        os.replace(incoming, parquet_path)
    except Exception:
        if writer is not None:
            writer.close()
        incoming.unlink(missing_ok=True)
        raise
    return {
        "rows": rows,
        "camera_counts": camera_counts,
        "record_sha256": digest.hexdigest(),
        "size_bytes": parquet_path.stat().st_size,
        "output": str(parquet_path),
    }
