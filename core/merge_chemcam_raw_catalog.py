#!/usr/bin/env python3
"""Merge the validated ChemCam RAW catalog into the application's RAW Parquet.

Run manually after `make_msl_chemcam_raw_catalog.py` has built/refreshed
`chemcam_raw_catalog.parquet` and it's been spot-checked: dedupes by
`img_url` (the base catalog's row wins on overlap, since it's concatenated
first and `drop_duplicates(keep="first")` follows), backs up the current
`Catalog_RawArch.parquet` before writing, and validates row counts/
duplicate-url invariants both before AND after the write (re-reading the
just-written parquet) before committing -- if anything looks off, the
original file is left untouched.
"""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd


def main() -> int:
    """Merge chemcam_raw_catalog.parquet into Catalog_RawArch.parquet, with a pre-write backup and a post-write re-read validation."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="data/catalog/Catalog_RawArch.parquet")
    parser.add_argument("--chemcam", default="data/catalog/chemcam_raw_catalog.parquet")
    args = parser.parse_args()

    base_path = Path(args.base).resolve()
    chemcam_path = Path(args.chemcam).resolve()
    base = pd.read_parquet(base_path)
    chemcam = pd.read_parquet(chemcam_path)

    required = {"product_id", "sol", "camera", "img_url"}
    if not required.issubset(base.columns) or not required.issubset(chemcam.columns):
        raise RuntimeError("Missing required catalog columns")
    if chemcam["img_url"].isna().any() or chemcam["img_url"].duplicated().any():
        raise RuntimeError("ChemCam RAW contains null or duplicate img_url values")

    overlap = set(base["img_url"].dropna()) & set(chemcam["img_url"].dropna())
    expected_rows = len(base) + len(chemcam) - len(overlap)
    all_columns = list(base.columns) + [column for column in chemcam.columns if column not in base.columns]
    for column in all_columns:
        if column not in base:
            base[column] = pd.NA
        if column not in chemcam:
            chemcam[column] = pd.NA

    # Keep the established RAW schema whenever the column already exists.
    for column in base.columns:
        try:
            chemcam[column] = chemcam[column].astype(base[column].dtype)
        except (TypeError, ValueError):
            pass

    merged = pd.concat([base[all_columns], chemcam[all_columns]], ignore_index=True)
    merged = merged.drop_duplicates(subset=["img_url"], keep="first")
    if len(merged) != expected_rows:
        raise RuntimeError(f"Unexpected merged row count: {len(merged)} != {expected_rows}")

    backup_dir = base_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"Catalog_RawArch_before_chemcam_{stamp}.parquet"
    shutil.copy2(base_path, backup_path)

    temp_path = base_path.with_suffix(".parquet.tmp")
    merged.to_parquet(temp_path, index=False)
    check = pd.read_parquet(temp_path)
    if (
        len(check) != expected_rows
        or check["img_url"].isna().any()
        or check["img_url"].duplicated().any()
    ):
        temp_path.unlink(missing_ok=True)
        raise RuntimeError("Post-write validation failed; original catalog was not replaced")
    temp_path.replace(base_path)

    print(f"base_rows={len(base)} chemcam_rows={len(chemcam)} overlap={len(overlap)}")
    print(f"merged_rows={len(check)} duplicate_urls={int(check['img_url'].duplicated().sum())}")
    print(f"backup={backup_path}")
    print(f"output={base_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
