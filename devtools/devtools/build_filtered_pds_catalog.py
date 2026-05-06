#!/usr/bin/env python
"""
Build a full merged PDS catalog and an optional filtered catalog.

Why this script exists:
- keep a "full" union catalog around as a reference archive
- express camera-by-camera cleaning rules in one editable Python file
- rebuild future derived catalogs from explicit rules instead of ad-hoc edits

Default outputs:
- Catalog_PDS_3.parquet = full deduplicated union of PDS_1 + PDS_2
- Catalog_PDS.parquet = filtered catalog built from the full union

Usage:
    python devtools/devtools/build_filtered_pds_catalog.py
    python devtools/devtools/build_filtered_pds_catalog.py --full-only
    python devtools/devtools/build_filtered_pds_catalog.py --filtered-only
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = ROOT / "data" / "catalog"
# NOTE: `backup_files/` was a local workspace-only folder and is not part of the published repo.
ARCHIVE_DIR = ROOT / "data" / "_archive" / "catalog_snapshots" / "pds_legacy_2026-04-27"


def _first_existing(*candidates: Path) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Missing source catalog. Tried: {[str(c) for c in candidates]}")

SOURCE_FILES = {
    "pds1": _first_existing(
        CATALOG_DIR / "Catalog_PDS_1.parquet",
        ARCHIVE_DIR / "Catalog_PDS_1.parquet",
    ),
    "pds2": _first_existing(
        CATALOG_DIR / "Catalog_PDS_2.parquet",
        ARCHIVE_DIR / "Catalog_PDS_2.parquet",
    ),
}

FULL_OUTPUT = ARCHIVE_DIR / "Catalog_PDS_3.parquet"
FILTERED_OUTPUT = CATALOG_DIR / "Catalog_PDS.parquet"


@dataclass(frozen=True)
class CameraRule:
    enabled: bool = True
    keep_products: tuple[str, ...] | None = None
    keep_suffixes: tuple[str, ...] | None = None
    keep_name_startswith_any: tuple[str, ...] | None = None
    keep_name_contains_any: tuple[str, ...] | None = None
    drop_name_contains_any: tuple[str, ...] | None = None


# This is the part we will evolve together.
# Decision taken so far:
# - Mastcam should stay on the useful field-oriented subset we validated
# - keep only DRCL products
# - inside DRCL, keep only C00 and E01
# - Navcam should reflect the useful real datasets:
#   keep only the mask-compatible products we actually use:
#   ILTLF images + MXYLF masks
# - Hazcam should stay on the useful real-data families, using name-based
#   matching because its IMG names do not expose clean product/suffix codes
# - MAHLI should stay conservative for now: keep only DRCL
# - MARDI can stay fully enabled for now
# - all other cameras stay untouched for now and will be analyzed later
CAMERA_RULES: dict[str, CameraRule] = {
    "mastcam": CameraRule(
        enabled=True,
        keep_products=("C00", "E01"),
        keep_suffixes=("DRCL",),
    ),
    "navcam": CameraRule(
        enabled=True,
        keep_name_startswith_any=("NLB_", "NRB_"),
        keep_name_contains_any=("ILTLF", "MXYLF"),
    ),
    "hazcam": CameraRule(
        enabled=True,
        keep_name_startswith_any=("FLB_", "FRB_", "RLB_", "RRB_"),
        # keep only mask-compatible products:
        # ILT_F images + MXYLF masks
        keep_name_contains_any=("ILT_F", "MXYLF"),
    ),
    "mahli": CameraRule(
        enabled=True,
        keep_suffixes=("DRCL",),
    ),
    "mardi": CameraRule(enabled=True),
    "chemcam": CameraRule(enabled=True),
}


def normalize_schema(reference: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    """Match column set and broad dtypes to the reference catalog."""
    cols = list(reference.columns)
    out = df.copy()

    for col in cols:
        if col not in out.columns:
            out[col] = pd.NA
    out = out[cols]

    string_cols = [c for c, dt in reference.dtypes.items() if str(dt) == "string"]
    for col in string_cols:
        reference[col] = reference[col].astype("string")
        out[col] = out[col].astype("string")

    out["sol"] = pd.to_numeric(out["sol"], errors="coerce").fillna(0).astype("int64")

    for col in ["site", "drive", "pose", "img_size_bytes"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").astype("float64")

    for col in ["geo_found", "record_complete"]:
        if col in out.columns:
            out[col] = out[col].fillna(False).astype("bool")

    return out


def add_merge_key(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    pid = out["product_id"].astype("string")
    img = out["img_name"].astype("string")
    out["_merge_key"] = pid.where(pid.notna() & (pid.str.len() > 0), img)
    return out


def read_sources() -> dict[str, pd.DataFrame]:
    pds1 = pd.read_parquet(SOURCE_FILES["pds1"])
    pds2 = pd.read_parquet(SOURCE_FILES["pds2"])
    pds1 = normalize_schema(pds1, pds1)
    pds2 = normalize_schema(pds1, pds2)
    return {"pds1": pds1, "pds2": pds2}


def build_full_union(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Prefer PDS_1 rows, then add only genuinely new rows from PDS_2."""
    p1 = add_merge_key(frames["pds1"])
    p2 = add_merge_key(frames["pds2"])

    existing = set(p1["_merge_key"].dropna().astype(str))
    p2_new = p2[~p2["_merge_key"].astype(str).isin(existing)].copy()

    merged = pd.concat([p1, p2_new], ignore_index=True)
    merged = merged.drop(columns=["_merge_key"])
    return merged


def extract_product_code(names: pd.Series) -> pd.Series:
    return names.astype(str).str.extract(r"([A-Z]\d{2})_", expand=False).fillna("UNKNOWN")


def extract_suffix_code(names: pd.Series) -> pd.Series:
    return names.astype(str).str.extract(r"_([A-Z0-9]{4})\.IMG$", expand=False).fillna("UNKNOWN")


def apply_camera_rule(camera_df: pd.DataFrame, rule: CameraRule) -> pd.DataFrame:
    if not rule.enabled or camera_df.empty:
        return camera_df

    out = camera_df.copy()
    names = out["img_name"].astype(str)
    products = extract_product_code(names)
    suffixes = extract_suffix_code(names)

    mask = pd.Series(True, index=out.index)

    if rule.keep_products:
        mask &= products.isin(rule.keep_products)
    if rule.keep_suffixes:
        mask &= suffixes.isin(rule.keep_suffixes)
    if rule.keep_name_startswith_any:
        starts = pd.Series(False, index=out.index)
        for token in rule.keep_name_startswith_any:
            starts |= names.str.startswith(token, na=False)
        mask &= starts
    if rule.keep_name_contains_any:
        contains = pd.Series(False, index=out.index)
        for token in rule.keep_name_contains_any:
            contains |= names.str.contains(token, case=False, na=False)
        mask &= contains
    if rule.drop_name_contains_any:
        for token in rule.drop_name_contains_any:
            mask &= ~names.str.contains(token, case=False, na=False)

    return out[mask].copy()


def build_filtered_catalog(full_df: pd.DataFrame) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    camera_series = full_df["camera"].astype(str).str.lower()

    for camera_name, rule in CAMERA_RULES.items():
        camera_df = full_df[camera_series == camera_name].copy()
        parts.append(apply_camera_rule(camera_df, rule))

    known = set(CAMERA_RULES)
    remainder = full_df[~camera_series.isin(known)].copy()
    if not remainder.empty:
        parts.append(remainder)

    return pd.concat(parts, ignore_index=True)


def summarize_mastcam_rule(full_df: pd.DataFrame, filtered_df: pd.DataFrame) -> None:
    """Print a compact Mastcam summary so we can see the effect of the current rule."""
    full_m = full_df[full_df["camera"].astype(str).str.lower() == "mastcam"].copy()
    filt_m = filtered_df[filtered_df["camera"].astype(str).str.lower() == "mastcam"].copy()
    if full_m.empty:
        print("MASTCAM RULE")
        print("  no mastcam rows found")
        return

    full_names = full_m["img_name"].astype(str)
    filt_names = filt_m["img_name"].astype(str)
    full_prod = extract_product_code(full_names)
    full_suf = extract_suffix_code(full_names)
    filt_prod = extract_product_code(filt_names)
    filt_suf = extract_suffix_code(filt_names)

    print("MASTCAM RULE")
    print(f"  source_rows = {len(full_m)}")
    print(f"  kept_rows = {len(filt_m)}")
    print(f"  kept_pct = {round((len(filt_m) / len(full_m)) * 100, 2)}")
    print(f"  kept_products = {dict(filt_prod.value_counts().sort_index())}")
    print(f"  kept_suffixes = {dict(filt_suf.value_counts().sort_index())}")
    print(f"  dropped_top_products = {dict(full_prod[~full_prod.isin(['C00', 'E01'])].value_counts().head(10))}")
    print(f"  dropped_top_suffixes = {dict(full_suf[full_suf != 'DRCL'].value_counts().head(10))}")


def summarize_navcam_rule(full_df: pd.DataFrame, filtered_df: pd.DataFrame) -> None:
    """Print a compact Navcam summary for the current useful-real-data rule."""
    full_n = full_df[full_df["camera"].astype(str).str.lower() == "navcam"].copy()
    filt_n = filtered_df[filtered_df["camera"].astype(str).str.lower() == "navcam"].copy()
    if full_n.empty:
        print("NAVCAM RULE")
        print("  no navcam rows found")
        return

    full_names = full_n["img_name"].astype(str)
    filt_names = filt_n["img_name"].astype(str)

    def _count(series: pd.Series, token: str) -> int:
        return int(series.str.contains(token, case=False, na=False).sum())

    print("NAVCAM RULE")
    print(f"  source_rows = {len(full_n)}")
    print(f"  kept_rows = {len(filt_n)}")
    print(f"  kept_pct = {round((len(filt_n) / len(full_n)) * 100, 2)}")
    print(
        "  kept_prefixes = "
        f"{{'NLB': {int(filt_names.str.startswith('NLB_', na=False).sum())}, "
        f"'NRB': {int(filt_names.str.startswith('NRB_', na=False).sum())}}}"
    )
    print(
        "  kept_families = "
        f"{{'TRAV': {_count(filt_names, 'TRAV')}, "
        f"'NCAM': {_count(filt_names, 'NCAM')}, "
        f"'ILTLF': {_count(filt_names, 'ILTLF')}, "
        f"'MXYLF': {_count(filt_names, 'MXYLF')}}}"
    )


def summarize_simple_camera_rule(full_df: pd.DataFrame, filtered_df: pd.DataFrame, camera_name: str) -> None:
    source = full_df[full_df["camera"].astype(str).str.lower() == camera_name].copy()
    kept = filtered_df[filtered_df["camera"].astype(str).str.lower() == camera_name].copy()
    print(f"{camera_name.upper()} RULE")
    if source.empty:
        print("  no rows found")
        return

    print(f"  source_rows = {len(source)}")
    print(f"  kept_rows = {len(kept)}")
    print(f"  kept_pct = {round((len(kept) / len(source)) * 100, 2)}")

    names = kept["img_name"].astype(str)
    suffixes = extract_suffix_code(names)
    products = extract_product_code(names)
    print(f"  kept_suffixes = {dict(suffixes.value_counts().sort_index())}")
    print(f"  kept_products = {dict(products.value_counts().head(10))}")


def summarize_hazcam_rule(full_df: pd.DataFrame, filtered_df: pd.DataFrame) -> None:
    source = full_df[full_df["camera"].astype(str).str.lower() == "hazcam"].copy()
    kept = filtered_df[filtered_df["camera"].astype(str).str.lower() == "hazcam"].copy()
    print("HAZCAM RULE")
    if source.empty:
        print("  no rows found")
        return

    names = kept["img_name"].astype(str)

    def _count(token: str) -> int:
        return int(names.str.contains(token, case=False, na=False).sum())

    print(f"  source_rows = {len(source)}")
    print(f"  kept_rows = {len(kept)}")
    print(f"  kept_pct = {round((len(kept) / len(source)) * 100, 2)}")
    print(
        "  kept_prefixes = "
        f"{{'FLB': {int(names.str.startswith('FLB_', na=False).sum())}, "
        f"'FRB': {int(names.str.startswith('FRB_', na=False).sum())}, "
        f"'RLB': {int(names.str.startswith('RLB_', na=False).sum())}, "
        f"'RRB': {int(names.str.startswith('RRB_', na=False).sum())}}}"
    )
    print(
        "  kept_families = "
        f"{{'TRAV': {_count('TRAV')}, "
        f"'FHAZ': {_count('FHAZ')}, "
        f"'RHAZ': {_count('RHAZ')}, "
        f"'ILT_F': {_count('ILT_F')}, "
        f"'ILTLF': {_count('ILTLF')}, "
        f"'MXYLF': {_count('MXYLF')}}}"
    )


def summarize(df: pd.DataFrame, label: str) -> None:
    counts = df["camera"].astype(str).str.lower().value_counts().sort_index().to_dict()
    print(label)
    print(f"  rows = {len(df)}")
    print(f"  sol_range = {int(df['sol'].min())} -> {int(df['sol'].max())}")
    print(f"  camera_counts = {counts}")


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    df.to_parquet(path, index=False)
    print(f"  wrote = {path}")
    print(f"  size_bytes = {path.stat().st_size}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build merged and filtered PDS catalogs.")
    parser.add_argument("--full-only", action="store_true", help="Build only Catalog_PDS_3.")
    parser.add_argument("--filtered-only", action="store_true", help="Build only Catalog_PDS (filtered) from Catalog_PDS_3.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.full_only and args.filtered_only:
        raise SystemExit("Choose either --full-only or --filtered-only, not both.")

    if args.filtered_only:
        if not FULL_OUTPUT.exists():
            raise SystemExit(f"Missing full catalog: {FULL_OUTPUT}")
        full_df = pd.read_parquet(FULL_OUTPUT)
        filtered_df = build_filtered_catalog(full_df)
        summarize(filtered_df, "FILTERED CATALOG")
        summarize_mastcam_rule(full_df, filtered_df)
        summarize_navcam_rule(full_df, filtered_df)
        summarize_hazcam_rule(full_df, filtered_df)
        summarize_simple_camera_rule(full_df, filtered_df, "mahli")
        summarize_simple_camera_rule(full_df, filtered_df, "mardi")
        write_parquet(filtered_df, FILTERED_OUTPUT)
        return

    frames = read_sources()
    full_df = build_full_union(frames)
    summarize(full_df, "FULL UNION CATALOG")
    write_parquet(full_df, FULL_OUTPUT)

    if not args.full_only:
        filtered_df = build_filtered_catalog(full_df)
        summarize(filtered_df, "FILTERED CATALOG")
        summarize_mastcam_rule(full_df, filtered_df)
        summarize_navcam_rule(full_df, filtered_df)
        summarize_hazcam_rule(full_df, filtered_df)
        summarize_simple_camera_rule(full_df, filtered_df, "mahli")
        summarize_simple_camera_rule(full_df, filtered_df, "mardi")
        write_parquet(filtered_df, FILTERED_OUTPUT)


if __name__ == "__main__":
    main()
