"""Atomic, validated install of a staged (JSON, Parquet) catalog pair into place.

Used by every worker that produces a new catalog version (update/repair/customization/
json-rebuild jobs): the worker writes its output to a staging area first, then calls
`install_catalog_pair` to swap it into `data/catalog/` only after `validate_catalog_pair`
confirms the JSON and Parquet actually agree with each other -- with automatic rollback
to the previous pair if anything about the swap or the post-swap re-validation fails.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pyarrow.parquet as pq


def validate_catalog_pair(json_path: Path, parquet_path: Path) -> dict[str, int]:
    """Verify that a staged JSON and Parquet describe the same catalog."""
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    cameras = payload.get("cameras")
    if not isinstance(cameras, dict) or not cameras:
        raise ValueError("Catalog JSON has no camera sections")

    json_counts: dict[str, int] = {}
    json_rows = 0
    for camera, section in cameras.items():
        if not isinstance(section, dict) or not isinstance(section.get("products"), list):
            raise ValueError(f"Invalid JSON camera section: {camera}")
        count = len(section["products"])
        declared = section.get("product_count")
        if declared is not None and int(declared) != count:
            raise ValueError(f"JSON product count mismatch for {camera}")
        json_counts[str(camera).casefold()] = count
        json_rows += count

    parquet_file = pq.ParquetFile(parquet_path)
    if parquet_file.metadata.num_rows != json_rows:
        raise ValueError(
            f"JSON/Parquet row mismatch: {json_rows} != {parquet_file.metadata.num_rows}"
        )
    columns = set(parquet_file.schema_arrow.names)
    if not {"camera", "img_url"}.issubset(columns):
        raise ValueError("Catalog Parquet is missing camera or img_url")

    table = pq.read_table(parquet_path, columns=["camera", "img_url"])
    frame = table.to_pandas()
    if frame["img_url"].isna().any() or frame["img_url"].duplicated().any():
        raise ValueError("Catalog Parquet contains missing or duplicate image URLs")
    parquet_counts = {
        str(camera).casefold(): int(count)
        for camera, count in frame.groupby("camera", dropna=False).size().items()
    }
    if parquet_counts != json_counts:
        raise ValueError("JSON/Parquet camera counts do not match")
    return json_counts


def install_catalog_pair(
    staged_json: Path,
    staged_parquet: Path,
    target_json: Path,
    target_parquet: Path,
    job_id: str,
) -> None:
    """Install a validated pair and restore the previous pair on any error."""
    validate_catalog_pair(staged_json, staged_parquet)
    rollback_json = target_json.with_name(f".{target_json.name}.{job_id}.rollback")
    rollback_parquet = target_parquet.with_name(f".{target_parquet.name}.{job_id}.rollback")
    for path in (rollback_json, rollback_parquet):
        path.unlink(missing_ok=True)

    moved_json = moved_parquet = False
    try:
        os.replace(target_json, rollback_json)
        moved_json = True
        os.replace(target_parquet, rollback_parquet)
        moved_parquet = True
        os.replace(staged_json, target_json)
        os.replace(staged_parquet, target_parquet)
        validate_catalog_pair(target_json, target_parquet)
    except Exception:
        target_json.unlink(missing_ok=True)
        target_parquet.unlink(missing_ok=True)
        if moved_json and rollback_json.exists():
            os.replace(rollback_json, target_json)
        if moved_parquet and rollback_parquet.exists():
            os.replace(rollback_parquet, target_parquet)
        raise
    else:
        rollback_json.unlink(missing_ok=True)
        rollback_parquet.unlink(missing_ok=True)
        shutil.rmtree(staged_json.parent, ignore_errors=True)
