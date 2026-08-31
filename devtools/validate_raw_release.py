from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


EXPECTED_CAMERAS = {"mastcam", "mahli", "navcam", "hazcam", "chemcam", "mardi"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_raw_release(parquet: Path, manifest_path: Path, data_schema_path: Path) -> list[str]:
    errors: list[str] = []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = json.loads(data_schema_path.read_text(encoding="utf-8"))
    if manifest.get("manifest_schema_version") != 1 or manifest.get("catalog_key") != "raw":
        errors.append("manifest: expected a RAW release manifest with schema version 1")
        return errors
    artifact = manifest.get("parquet", {})
    checked = manifest.get("update_state_initialization", {}).get("checked_through_sol")
    expected_id = f"raw-sol{checked}-{str(artifact.get('sha256', ''))[:12]}"
    if manifest.get("release", {}).get("release_id") != expected_id:
        errors.append(f"release_id: expected {expected_id!r}")
    if parquet.name != artifact.get("filename"):
        errors.append(f"filename: expected {artifact.get('filename')!r}, found {parquet.name!r}")
    if parquet.stat().st_size != artifact.get("size_bytes"):
        errors.append(f"size: expected {artifact.get('size_bytes')}, found {parquet.stat().st_size}")
    digest = _sha256(parquet)
    if digest != artifact.get("sha256"):
        errors.append(f"sha256: expected {artifact.get('sha256')}, found {digest}")
        return errors

    parquet_file = pq.ParquetFile(parquet)
    columns = parquet_file.schema_arrow.names
    expected_columns = [entry["name"] for entry in schema["columns"]]
    if columns != expected_columns or columns != artifact.get("columns"):
        errors.append("columns: Parquet columns differ from the RAW schema or manifest")
    if parquet_file.metadata.num_rows != artifact.get("row_count"):
        errors.append(f"row_count: expected {artifact.get('row_count')}, found {parquet_file.metadata.num_rows}")
    if parquet_file.metadata.num_columns != artifact.get("column_count"):
        errors.append(f"column_count: expected {artifact.get('column_count')}, found {parquet_file.metadata.num_columns}")

    frame = pd.read_parquet(parquet, columns=["camera", "sol", "img_url"])
    for column in ("camera", "img_url"):
        blanks = int((frame[column].isna() | frame[column].astype("string").str.strip().eq("")).sum())
        if blanks:
            errors.append(f"required field [{column}]: contains {blanks} blank/null values")
    if frame["sol"].isna().any():
        errors.append(f"required field [sol]: contains {int(frame['sol'].isna().sum())} null values")
    duplicate_urls = int(frame["img_url"].duplicated().sum())
    if duplicate_urls:
        errors.append(f"identity [img_url]: contains {duplicate_urls} duplicates")
    cameras = set(frame["camera"].astype(str).unique())
    if cameras != EXPECTED_CAMERAS:
        errors.append(f"cameras: expected {sorted(EXPECTED_CAMERAS)}, found {sorted(cameras)}")
    numeric_sol = pd.to_numeric(frame["sol"], errors="coerce")
    coverage: dict[str, Any] = manifest.get("coverage_by_camera", {})
    for camera in sorted(EXPECTED_CAMERAS):
        group = frame.loc[frame["camera"].astype(str).eq(camera)].assign(_sol=numeric_sol)
        sols = group["_sol"].dropna().astype("int64")
        actual = {
            "product_count": int(len(group)),
            "product_sol_count": int(sols.nunique()),
            "first_product_sol": int(sols.min()),
            "last_product_sol": int(sols.max()),
        }
        for field, value in actual.items():
            if coverage.get(camera, {}).get(field) != value:
                errors.append(f"coverage [{camera}.{field}]: expected {coverage.get(camera, {}).get(field)}, found {value}")
    return errors
