from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_CAMERAS = {"mastcam", "mahli", "navcam", "hazcam", "chemcam", "mardi"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _blank_count(series: pd.Series) -> int:
    return int((series.isna() | series.astype("string").str.strip().eq("")).sum())


def validate_release(parquet: Path, manifest_path: Path, schema_path: Path, data_schema_path: Path) -> list[str]:
    errors: list[str] = []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    data_schema = json.loads(data_schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(manifest_schema, format_checker=FormatChecker())
    for error in sorted(validator.iter_errors(manifest), key=lambda item: list(item.path)):
        location = ".".join(str(part) for part in error.path) or "$"
        errors.append(f"manifest schema [{location}]: {error.message}")

    artifact = manifest.get("parquet", {})
    expected_release_id = f"pds-sol{manifest.get('update_state_initialization', {}).get('checked_through_sol')}-{artifact.get('sha256', '')[:12]}"
    if manifest.get("release", {}).get("release_id") != expected_release_id:
        errors.append(f"release_id: expected {expected_release_id!r}")
    if parquet.name != artifact.get("filename"):
        errors.append(f"filename: expected {artifact.get('filename')!r}, found {parquet.name!r}")
    if parquet.stat().st_size != artifact.get("size_bytes"):
        errors.append(f"size: expected {artifact.get('size_bytes')}, found {parquet.stat().st_size}")
    digest = _sha256(parquet)
    if digest != artifact.get("sha256"):
        errors.append(f"sha256: expected {artifact.get('sha256')}, found {digest}")
        # Do not ask the Parquet engine to parse an artifact whose identity is
        # already known to be wrong; a damaged footer may crash before a clear
        # validation result can be returned.
        return errors

    frame = pd.read_parquet(parquet)
    schema_columns = data_schema["columns"]
    expected_columns = [entry["name"] for entry in schema_columns]
    expected_dtypes = {entry["name"]: entry["dtype"] for entry in schema_columns}
    if list(frame.columns) != expected_columns:
        errors.append("columns: Parquet column order/content differs from the canonical PDS schema")
    if list(frame.columns) != artifact.get("columns"):
        errors.append("columns: Parquet columns differ from the release manifest")
    if len(frame) != artifact.get("row_count"):
        errors.append(f"row_count: expected {artifact.get('row_count')}, found {len(frame)}")
    if len(frame.columns) != artifact.get("column_count"):
        errors.append(f"column_count: expected {artifact.get('column_count')}, found {len(frame.columns)}")

    for column, expected_dtype in expected_dtypes.items():
        if column in frame and str(frame[column].dtype) != expected_dtype:
            errors.append(f"dtype [{column}]: expected {expected_dtype}, found {frame[column].dtype}")

    for column in ("img_url", "product_id", "camera"):
        if column in frame and _blank_count(frame[column]):
            errors.append(f"required field [{column}]: contains {_blank_count(frame[column])} blank/null values")
    if frame["sol"].isna().any():
        errors.append(f"required field [sol]: contains {int(frame['sol'].isna().sum())} null values")
    duplicate_urls = int(frame["img_url"].duplicated().sum())
    if duplicate_urls:
        errors.append(f"identity [img_url]: contains {duplicate_urls} duplicates")
    exact_duplicates = int(frame.duplicated().sum())
    if exact_duplicates:
        errors.append(f"rows: contains {exact_duplicates} exact duplicates")

    cameras = set(frame["camera"].astype(str).unique())
    if cameras != EXPECTED_CAMERAS:
        errors.append(f"cameras: expected {sorted(EXPECTED_CAMERAS)}, found {sorted(cameras)}")
    coverage = manifest.get("coverage_by_camera", {})
    numeric_sol = pd.to_numeric(frame["sol"], errors="coerce")
    for camera in sorted(EXPECTED_CAMERAS):
        group = frame.loc[frame["camera"].astype(str).eq(camera)].assign(_sol=numeric_sol)
        valid_sols = group["_sol"].dropna().astype("int64")
        actual: dict[str, Any] = {
            "product_count": int(len(group)),
            "product_sol_count": int(valid_sols.nunique()),
            "first_product_sol": int(valid_sols.min()) if len(valid_sols) else None,
            "last_product_sol": int(valid_sols.max()) if len(valid_sols) else None,
        }
        for field, value in actual.items():
            expected = coverage.get(camera, {}).get(field)
            if value != expected:
                errors.append(f"coverage [{camera}.{field}]: expected {expected}, found {value}")
        checked = coverage.get(camera, {}).get("checked_through_sol")
        if actual["last_product_sol"] is not None and isinstance(checked, int) and checked < actual["last_product_sol"]:
            errors.append(f"coverage [{camera}]: checked_through_sol precedes last_product_sol")
    checked_values = {entry.get("checked_through_sol") for entry in coverage.values() if isinstance(entry, dict)}
    quick_start = manifest.get("update_state_initialization", {}).get("quick_update_start_sol")
    if len(checked_values) == 1 and quick_start != next(iter(checked_values)) + 1:
        errors.append("update state: quick_update_start_sol must equal checked_through_sol + 1")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a PDS Parquet release against its manifest.")
    parser.add_argument("--parquet", type=Path, default=ROOT / "data" / "catalog" / "Catalog_PDS.parquet")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data" / "catalog_json_rebuild" / "manifest_test" / "Catalog_PDS.manifest.json")
    parser.add_argument("--manifest-schema", type=Path, default=ROOT / "config" / "pds_release_manifest_schema.json")
    parser.add_argument("--data-schema", type=Path, default=ROOT / "config" / "pds_catalog_schema.json")
    args = parser.parse_args()
    errors = validate_release(args.parquet.resolve(), args.manifest.resolve(), args.manifest_schema.resolve(), args.data_schema.resolve())
    if errors:
        print(f"PDS release validation FAILED ({len(errors)} errors)")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print("PDS release validation PASSED")
    print(f"- Parquet: {args.parquet.resolve()}")
    print(f"- Manifest: {args.manifest.resolve()}")
    print("- Canonical identity: img_url")


if __name__ == "__main__":
    main()
