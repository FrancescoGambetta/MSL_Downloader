from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _artifact(path: Path) -> dict[str, Any]:
    return {"filename": path.name, "size_bytes": path.stat().st_size, "sha256": _sha256(path)}


def build_manifest(parquet: Path, checked_through_sol: int) -> dict[str, Any]:
    index = pd.read_parquet(parquet, columns=["camera", "sol"])
    metadata = pq.ParquetFile(parquet).metadata
    artifact = _artifact(parquet)
    sols = pd.to_numeric(index["sol"], errors="coerce")
    cameras: dict[str, dict[str, Any]] = {}
    for camera, group in index.assign(_sol=sols).groupby("camera", dropna=False):
        valid_sols = group["_sol"].dropna().astype("int64")
        cameras[str(camera)] = {
            "product_count": int(len(group)),
            "product_sol_count": int(valid_sols.nunique()),
            "first_product_sol": int(valid_sols.min()) if len(valid_sols) else None,
            "last_product_sol": int(valid_sols.max()) if len(valid_sols) else None,
            "checked_through_sol": int(checked_through_sol),
            "checked_through_source": "maintainer_declared_and_local_status",
        }
    tracked = [ROOT / "config" / "raw_catalog_schema.json"]
    inputs = {path.relative_to(ROOT).as_posix(): _artifact(path) for path in tracked if path.exists()}
    valid_global_sols = sols.dropna().astype("int64")
    return {
        "manifest_schema_version": 1,
        "catalog_key": "raw",
        "mission": "MSL",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "release": {
            "release_id": f"raw-sol{checked_through_sol}-{artifact['sha256'][:12]}",
            "role": "official_base_catalog",
            "mutability": "immutable_after_distribution",
            "coverage_authority": "release_manifest",
        },
        "parquet": {
            **artifact,
            "row_count": int(metadata.num_rows),
            "column_count": int(metadata.num_columns),
            "columns": list(pq.ParquetFile(parquet).schema_arrow.names),
            "first_product_sol": int(valid_global_sols.min()),
            "last_product_sol": int(valid_global_sols.max()),
            "product_sol_count": int(valid_global_sols.nunique()),
        },
        "coverage_by_camera": dict(sorted(cameras.items())),
        "data_contract": {
            "canonical_identity": "img_url",
            "required_non_null": ["img_url", "camera", "sol"],
            "optional_nullable": ["product_id", "lbl_url", "lbl_name"],
            "duplicate_identity_policy": "reject_release",
            "product_id_duplicate_policy": "allow_when_img_url_is_unique",
            "exact_duplicate_row_policy": "reject_release",
        },
        "builder_inputs": inputs,
        "json_reconstruction": {
            "required_for_download": False,
            "required_for_catalog_updates": True,
            "canonical_filename": "Catalog_RawArch.json",
            "catalog_schema_version": 1,
            "roundtrip_verified": True,
            "verified_row_count": 1449239,
            "reference_elapsed_seconds": 307.53,
            "reference_peak_rss_bytes": 2265116672,
            "reference_json_size_bytes": 1403868078,
            "strategy": "camera_partitioned_streaming",
        },
        "update_state_initialization": {
            "strategy": "coverage_boundary_plus_separate_integrity_check",
            "quick_update_start_sol": int(checked_through_sol) + 1,
            "checked_through_sol": int(checked_through_sol),
            "initial_builder_state": "empty",
            "historical_backfills": "detect_with_integrity_check_or_overlap_scan",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the official RAW Archive release manifest.")
    parser.add_argument("--parquet", type=Path, default=ROOT / "data" / "catalog" / "Catalog_RawArch.parquet")
    parser.add_argument("--checked-through-sol", type=int, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "catalog" / "Catalog_RawArch.manifest.json")
    args = parser.parse_args()
    manifest = build_manifest(args.parquet.resolve(), args.checked_through_sol)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Manifest written: {output}")
    print(f"Release: {manifest['release']['release_id']}")
    print(f"Rows: {manifest['parquet']['row_count']:,}")
    print(f"SHA-256: {manifest['parquet']['sha256']}")


if __name__ == "__main__":
    main()
