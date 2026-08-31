"""Catalog search: the real counterpart of the frontend's `lib/nasaApi.js`.

Loads the same PDS+RAW parquet catalogs the Streamlit app reads (via `runtime.py`),
and filters them with the exact same engine the sidebar uses (`catalog.filter_dataframe`
-> `camera_rules.json`, `catalog.deduplicate_with_source_priority`) -- see
`app/ui_panels/builder_sidebar.py::_collect_builder_filters` for the filters-dict shape
this mirrors, and `app/services/catalog_apply_filters_service.py::CatalogApplyFiltersService`
for the filter-per-source -> concat -> dedupe pipeline this replicates without the
Streamlit session_state/caching machinery (a plain per-request call for now).
"""

from __future__ import annotations

import math
import threading
from typing import Any, Optional

import pandas as pd

import catalog as app_catalog
import runtime as app_runtime


_CATALOG_MIN_COLUMNS_COMMON = [
    "product_id",
    "camera",
    "sol",
    "sol_url",
    "img_url",
    "lbl_url",
    "img_size_bytes",
    "image_id",
    "instrument_id",
    "instrument_name",
    "start_time",
    "image_time",
    "site",
    "drive",
    "pose",
    "sclk",
    "collection",
    "data_root",
    "record_complete",
]

_lock = threading.Lock()
_cache: dict[str, Any] = {"key": None, "df_pds": None, "df_raw": None}


def _columns_for(source: str) -> list[str]:
    cols = list(_CATALOG_MIN_COLUMNS_COMMON)
    if source == "raw":
        cols += ["is_thumbnail", "sample_type"]
    return cols


def _load_source(path, source: str) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = app_runtime.prepare_catalog_index(app_runtime.load_catalog(str(path), columns=_columns_for(source)))
    if len(df) and "source" not in df.columns:
        df = df.copy()
        df["source"] = source
    return df


def _load_combined() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return `(df_pds, df_raw)`, each source-tagged, reloading whenever either parquet's mtime changes."""
    pds_path = app_runtime._resolve_catalog_parquet()
    raw_path = app_runtime._resolve_catalog_parquet_raw()
    key = (
        f"{pds_path}:{pds_path.stat().st_mtime if pds_path.exists() else 0}"
        f"|{raw_path}:{raw_path.stat().st_mtime if raw_path.exists() else 0}"
    )
    with _lock:
        if _cache["key"] == key:
            return _cache["df_pds"], _cache["df_raw"]
        df_pds = _load_source(pds_path, "pds")
        df_raw = _load_source(raw_path, "raw")
        _cache.update(key=key, df_pds=df_pds, df_raw=df_raw)
        return df_pds, df_raw


def build_filters(
    *,
    sol_start: Optional[int],
    sol_end: Optional[int],
    cameras: list[str],
    source_pds: bool,
    source_raw: bool,
    min_img_size_kb: Optional[int],
) -> dict[str, Any]:
    """Build the real `filters` dict `catalog.filter_dataframe`/camera_rules.json expect, matching `_collect_builder_filters`'s shape exactly (same camera-specific rule keys, same KB->bytes conversion)."""
    cams_norm = {str(c).strip().lower() for c in cameras}
    return {
        "sol_start": sol_start,
        "sol_end": sol_end,
        "cameras": list(cameras),
        "source_pds": bool(source_pds),
        "source_raw": bool(source_raw),
        "mastcam_raw_include_c00": True,
        "min_img_size": None if min_img_size_kb is None else max(0, int(min_img_size_kb)) * 1024,
        "only_with_lbl": False,
        "dr_variants": [],
        "name_tokens": [],
        "file_prefixes": [],
        "file_name_contains": [],
        "mastcam_only_drcl": "mastcam" in cams_norm,
        "mahli_only_drcl": "mahli" in cams_norm,
        "mardi_only_e01_drcx": "mardi" in cams_norm,
        "navcam_only_iltlf": "navcam" in cams_norm,
        "hazcam_only_lb_edr": "hazcam" in cams_norm,
    }


def _clean_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert a DataFrame to JSON-safe records: drop the filter engine's internal `_`-prefixed working columns (`_row_id`, `_file_name`, `_suffix_code`, `_family_key`, ...), and turn NaN/NaT/inf into `None` (raw `NaN` is not valid JSON)."""
    public_columns = [c for c in df.columns if not str(c).startswith("_")]
    records = df[public_columns].to_dict(orient="records")
    for row in records:
        for k, v in row.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                row[k] = None
            elif pd.isna(v) if not isinstance(v, (list, dict)) else False:
                row[k] = None
    return records


def search(
    *,
    sol_start: Optional[int],
    sol_end: Optional[int],
    cameras: list[str],
    source_pds: bool,
    source_raw: bool,
    min_img_size_kb: Optional[int],
    max_images: Optional[int],
) -> dict[str, Any]:
    """Filter the combined catalog and return matching products, capped to `max_images`.

    Mirrors `CatalogApplyFiltersService.apply_filters`: filter PDS and RAW
    separately (each still carries its own rows only, but `filter_dataframe`
    is given the full filters dict so `source_pds`/`source_raw` toggles are
    honoured identically to the live app), concatenate, then deduplicate
    across sources.
    """
    df_pds, df_raw = _load_combined()
    filters = build_filters(
        sol_start=sol_start,
        sol_end=sol_end,
        cameras=cameras,
        source_pds=source_pds,
        source_raw=source_raw,
        min_img_size_kb=min_img_size_kb,
    )

    out_pds = app_catalog.filter_dataframe(df_pds, filters) if len(df_pds) else df_pds
    out_raw = app_catalog.filter_dataframe(df_raw, filters) if len(df_raw) else df_raw
    if len(out_pds) == 0 and len(out_raw) == 0:
        merged = pd.DataFrame()
    elif len(out_pds) == 0:
        merged = out_raw
    elif len(out_raw) == 0:
        merged = out_pds
    else:
        merged = pd.concat([out_pds, out_raw], axis=0, ignore_index=True)

    merged = app_catalog.deduplicate_with_source_priority(merged) if len(merged) else merged
    total_found = len(merged)
    capped = merged.iloc[: max_images] if max_images and max_images > 0 else merged

    return {
        "total_found": total_found,
        "after_cap": len(capped),
        "products": _clean_records(capped),
    }
