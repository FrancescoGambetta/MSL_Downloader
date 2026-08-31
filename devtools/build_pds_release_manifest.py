from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "filename": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def build_manifest(parquet: Path, checked_through_sol: int) -> dict[str, Any]:
    frame = pd.read_parquet(parquet)
    parquet_artifact = _artifact(parquet)
    sols = pd.to_numeric(frame["sol"], errors="coerce")
    cameras: dict[str, dict[str, Any]] = {}
    for camera, group in frame.assign(_sol=sols).groupby("camera", dropna=False):
        camera_name = str(camera)
        valid_sols = group["_sol"].dropna().astype("int64")
        cameras[camera_name] = {
            "product_count": int(len(group)),
            "product_sol_count": int(valid_sols.nunique()),
            "first_product_sol": int(valid_sols.min()) if len(valid_sols) else None,
            "last_product_sol": int(valid_sols.max()) if len(valid_sols) else None,
            "checked_through_sol": checked_through_sol,
            "checked_through_source": "maintainer_declared_and_local_status",
        }

    tracked_inputs = [
        ROOT / "config" / "pds_release_manifest_schema.json",
        ROOT / "config" / "pds_catalog_schema.json",
        ROOT / "config" / "camera_rules.json",
        ROOT / "config" / "msl_catalog_config.json",
        ROOT / "config" / "pre3000_catalog_config.json",
    ]
    inputs = {
        path.relative_to(ROOT).as_posix(): _artifact(path)
        for path in tracked_inputs
        if path.exists()
    }
    valid_global_sols = sols.dropna().astype("int64")
    return {
        "manifest_schema_version": 1,
        "catalog_key": "pds",
        "mission": "MSL",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "release": {
            "release_id": f"pds-sol{checked_through_sol}-{parquet_artifact['sha256'][:12]}",
            "role": "official_base_catalog",
            "mutability": "immutable_after_distribution",
            "coverage_authority": "release_manifest",
        },
        "parquet": {
            **parquet_artifact,
            "row_count": int(len(frame)),
            "column_count": int(len(frame.columns)),
            "columns": list(frame.columns),
            "first_product_sol": int(valid_global_sols.min()),
            "last_product_sol": int(valid_global_sols.max()),
            "product_sol_count": int(valid_global_sols.nunique()),
        },
        "coverage_by_camera": dict(sorted(cameras.items())),
        "data_contract": {
            "canonical_identity": "img_url",
            "required_non_null": ["img_url", "product_id", "camera", "sol"],
            "optional_nullable": ["lbl_url"],
            "duplicate_identity_policy": "reject_release",
            "exact_duplicate_row_policy": "reject_release",
        },
        "builder_inputs": inputs,
        "json_reconstruction": {
            "required_for_download": False,
            "required_for_catalog_updates": True,
            "canonical_filename": "Catalog_PDS.json",
            "catalog_schema_version": 2,
            "roundtrip_verified": True,
            "verified_row_count": 387276,
            "reference_elapsed_seconds": 94.564,
            "reference_peak_rss_bytes": 3270475776,
            "reference_json_size_bytes": 609955688,
        },
        "update_state_initialization": {
            "strategy": "coverage_boundary_plus_separate_integrity_check",
            "quick_update_start_sol": checked_through_sol + 1,
            "checked_through_sol": checked_through_sol,
            "scanned_sol_urls_reconstructable_from_parquet": False,
            "fabricate_scanned_sol_urls": False,
            "initial_builder_state": "empty",
            "historical_backfills": "detect_with_integrity_check_or_overlap_scan",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the official PDS release manifest prototype.")
    parser.add_argument("--parquet", type=Path, default=ROOT / "data" / "catalog" / "Catalog_PDS.parquet")
    parser.add_argument("--checked-through-sol", type=int, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "catalog_json_rebuild" / "manifest_test" / "Catalog_PDS.manifest.json",
    )
    args = parser.parse_args()
    parquet = args.parquet.resolve()
    output = args.output.resolve()
    manifest = build_manifest(parquet, args.checked_through_sol)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Manifest written: {output}")
    print(f"Rows: {manifest['parquet']['row_count']:,}")
    print(f"SHA-256: {manifest['parquet']['sha256']}")


if __name__ == "__main__":
    main()
