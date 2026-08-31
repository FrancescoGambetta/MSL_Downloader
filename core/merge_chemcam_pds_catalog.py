#!/usr/bin/env python3
"""Merge the validated ChemCam PDS catalog into the application's PDS Parquet.

Run manually after `make_msl_chemcam_catalog.py` has built/refreshed
`chemcam_catalog.parquet` and it's confirmed error-free (refuses to merge
if any row still has a `lbl_parse_error`): stamps ChemCam-specific column
defaults (it isn't geo-enriched, unlike PDS rows for other cameras), aligns
dtypes with the base catalog's schema, then merges/backs up/validates the
same way `merge_chemcam_raw_catalog.py` does.
"""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd


def main() -> int:
    """Merge chemcam_catalog.parquet into Catalog_PDS.parquet, with dtype alignment, a pre-write backup, and post-write validation."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="data/catalog/Catalog_PDS.parquet")
    parser.add_argument("--chemcam", default="data/catalog/chemcam_catalog.parquet")
    args = parser.parse_args()

    base_path = Path(args.base).resolve()
    chemcam_path = Path(args.chemcam).resolve()
    base = pd.read_parquet(base_path)
    chemcam = pd.read_parquet(chemcam_path)

    if chemcam["lbl_parse_error"].fillna("").astype(str).str.len().gt(0).any():
        raise RuntimeError("ChemCam catalog still contains LBL parsing errors")
    if chemcam["img_url"].duplicated().any():
        raise RuntimeError("ChemCam catalog contains duplicate img_url values")

    overlap = set(base["img_url"].dropna()) & set(chemcam["img_url"].dropna())
    expected = len(base) + len(chemcam) - len(overlap)
    existing_chemcam_count = int(base["camera"].astype("string").str.casefold().eq("chemcam").sum())
    expected_chemcam_count = existing_chemcam_count + len(chemcam) - sum(
        url in overlap for url in chemcam["img_url"].dropna()
    )

    chemcam["collection"] = "MSLCCM_1XXX"
    chemcam["data_root"] = "DATA"
    chemcam["sol_dir_name"] = chemcam["sol"].map(lambda sol: f"{int(sol):05d}")
    chemcam["geo_match_strategy"] = "not_enriched"
    chemcam["geo_found"] = False
    chemcam["geo_parse_error"] = pd.NA
    chemcam["record_complete"] = False
    for column in ("geo_latitude", "geo_longitude", "geo_elevation", "geo_frame"):
        chemcam[column] = pd.NA

    all_columns = list(base.columns) + [column for column in chemcam.columns if column not in base.columns]
    for column in all_columns:
        if column not in base:
            base[column] = pd.NA
        if column not in chemcam:
            chemcam[column] = pd.NA

    # Match the stable catalog types before concatenation.
    string_columns = [column for column in all_columns if column not in {
        "sol", "site", "drive", "pose", "img_size_bytes", "tif_size_bytes",
        "geo_found", "record_complete",
    }]
    for frame in (base, chemcam):
        for column in string_columns:
            frame[column] = frame[column].astype("string")
        for column in ("site", "drive", "pose", "img_size_bytes", "tif_size_bytes"):
            if column in frame:
                frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Float64")
        frame["sol"] = pd.to_numeric(frame["sol"], errors="raise").astype("int64")
        frame["geo_found"] = frame["geo_found"].fillna(False).astype(bool)
        frame["record_complete"] = frame["record_complete"].fillna(False).astype(bool)

    merged = pd.concat([base[all_columns], chemcam[all_columns]], ignore_index=True)
    merged = merged.drop_duplicates(subset=["img_url"], keep="first")
    if len(merged) != expected:
        raise RuntimeError(f"Unexpected merged row count: {len(merged)} != {expected}")

    backup_dir = base_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"Catalog_PDS_before_chemcam_{stamp}.parquet"
    shutil.copy2(base_path, backup_path)

    temp_path = base_path.with_suffix(".parquet.tmp")
    merged.to_parquet(temp_path, index=False)
    check = pd.read_parquet(temp_path)
    chemcam_count = int(check["camera"].eq("chemcam").sum())
    if (
        len(check) != expected
        or check["img_url"].duplicated().any()
        or chemcam_count != expected_chemcam_count
    ):
        temp_path.unlink(missing_ok=True)
        raise RuntimeError("Post-write validation failed; original catalog was not replaced")
    temp_path.replace(base_path)

    print(f"base_rows={len(base)} chemcam_rows={len(chemcam)} overlap={len(overlap)}")
    print(f"merged_rows={len(check)} chemcam_in_merged={chemcam_count}")
    print(f"backup={backup_path}")
    print(f"output={base_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
