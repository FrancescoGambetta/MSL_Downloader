"""Catalog facade: camera_rules.json loading, filtering, and dataframe cleanup.

Thin wrapper over `services/catalog_*_service.py`, following the same
lazy-singleton pattern as `actions.py` (see that module's docstring). The
non-obvious piece here is `camera_rules.json`: it's the single source of
truth for "which product type/level combo counts as the real image for
camera X" (used both by the live app's filtering, via this module, and by
the catalog builders in `core/`, via `_record_is_allowed`), and both cached
loaders below key their `st.cache_data` cache on the file's mtime -- without
that, editing camera_rules.json while the app is running would have no
effect until a full restart (Streamlit's cache_data ignores
underscore-prefixed args, so a naive `_path` parameter used to defeat this
silently; see the comments on the two `_load_*_cached` functions).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd
import streamlit as st

from services.catalog_filter_service import CatalogFilterService
from services.catalog_dataframe_ops_service import CatalogDataframeOpsService
from services.catalog_apply_filters_service import CatalogApplyFiltersService
from services.catalog_rules_service import CatalogRulesService
from runtime import (
    normalize_text,
    persist_selection_from_filtered,
)

_T: Callable[..., str] = lambda key, **kwargs: key.format(**kwargs) if kwargs else key

_CATALOG_RULES_SERVICE: CatalogRulesService | None = None
_CATALOG_FILTER_SERVICE: CatalogFilterService | None = None
_CATALOG_DF_OPS_SERVICE: CatalogDataframeOpsService | None = None
_CATALOG_APPLY_FILTERS_SERVICE: CatalogApplyFiltersService | None = None


def set_translator(fn: Callable[..., str]) -> None:
    global _T
    _T = fn


def _get_catalog_rules_service() -> CatalogRulesService:
    global _CATALOG_RULES_SERVICE
    if _CATALOG_RULES_SERVICE is None:
        _CATALOG_RULES_SERVICE = CatalogRulesService(
            normalize_text=normalize_text,
            norm_ascii=_norm_ascii,
        )
    return _CATALOG_RULES_SERVICE


def _get_catalog_filter_service() -> CatalogFilterService:
    global _CATALOG_FILTER_SERVICE
    if _CATALOG_FILTER_SERVICE is None:
        _CATALOG_FILTER_SERVICE = CatalogFilterService(
            normalize_text=normalize_text,
            norm_ascii=_norm_ascii,
            load_compiled_camera_rules=load_compiled_camera_rules,
            load_camera_rules=load_camera_rules,
            reduce_raw_burst_sequences=reduce_raw_burst_sequences,
        )
    return _CATALOG_FILTER_SERVICE


def _get_catalog_df_ops_service() -> CatalogDataframeOpsService:
    global _CATALOG_DF_OPS_SERVICE
    if _CATALOG_DF_OPS_SERVICE is None:
        _CATALOG_DF_OPS_SERVICE = CatalogDataframeOpsService(
            normalize_text=normalize_text,
            norm_ascii=_norm_ascii,
        )
    return _CATALOG_DF_OPS_SERVICE


def _get_catalog_apply_filters_service() -> CatalogApplyFiltersService:
    global _CATALOG_APPLY_FILTERS_SERVICE
    if _CATALOG_APPLY_FILTERS_SERVICE is None:
        _CATALOG_APPLY_FILTERS_SERVICE = CatalogApplyFiltersService(
            normalize_text=normalize_text,
            filter_dataframe=filter_dataframe,
            deduplicate_with_source_priority=deduplicate_with_source_priority,
            persist_selection_from_filtered=persist_selection_from_filtered,
        )
    return _CATALOG_APPLY_FILTERS_SERVICE


def _norm_ascii(text: str) -> str:
    """Lowercase `text` and fold common Latin/German accented characters to their ASCII base letter."""
    return (
        text.lower()
        .replace("à", "a").replace("á", "a").replace("â", "a").replace("ä", "a")
        .replace("è", "e").replace("é", "e").replace("ê", "e").replace("ë", "e")
        .replace("ì", "i").replace("í", "i").replace("î", "i").replace("ï", "i")
        .replace("ò", "o").replace("ó", "o").replace("ô", "o").replace("ö", "o")
        .replace("ù", "u").replace("ú", "u").replace("û", "u").replace("ü", "u")
        .replace("ß", "ss")
    )


def _camera_rules_path() -> Path:
    from runtime import PROJECT_ROOT
    return PROJECT_ROOT / "config" / "camera_rules.json"


def _deep_merge(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    return _get_catalog_rules_service().deep_merge(dst, src)


# Built-in fallback used when config/camera_rules.json is missing/invalid --
# defines, per camera, which product-type/processing-level combination is
# treated as "the real image" (as opposed to raw intermediates, thumbnails,
# etc.) for both PDS and RAW Archive sources.
_CAMERA_RULES_FALLBACK: dict[str, Any] = {
    "raw_global_rules": {
        "drop_filename_contains_any": ["THUMBNAIL"],
        "reduce_bursts": {
            "apply_when_filter_key": "raw_reduce_bursts",
            "keep_per_group_filter_key": "raw_burst_keep_per_group",
            "default_keep_per_group": 1,
        },
    },
    "mastcam": {
        "filter_key": "mastcam_only_drcl",
        "rules": {
            "pds": {
                "suffix_equals_any": ["DRCL"],
                "min_img_size_bytes": 102400,
            },
            "raw": {
                "apply_when_filter_key": "mastcam_only_drcl",
                "filename_contains_any": ["C00", "E01", "E1_"],
            },
        },
    },
    "mahli": {
        "filter_key": "mahli_only_drcl",
        "rules": {
            "pds": {
                "suffix_equals_any": ["DRCL"],
            },
            "raw": {
                "apply_when_filter_key": "raw_mahli_legacy_subset",
                "filename_contains_any": ["C00_", "R0_", "E01_"],
            },
        },
    },
    "mardi": {
        "filter_key": "mardi_only_e01_drcx",
        "rules": {
            "pds": {
                "suffix_equals_any": ["DRCL"],
                "filename_contains_any": ["E01_", "E00_", "C00_"],
            },
        },
    },
    "navcam": {
        "filter_key": "navcam_only_iltlf",
        "camera_markers_any": ["NCAM"],
        "rules": {
            "pds": {
                "filename_prefix_any": ["NLB_", "NRB_"],
                "filename_contains_all": ["ILTLF"],
            },
        },
    },
    "hazcam": {
        "filter_key": "hazcam_only_lb_edr",
        "camera_markers_any": ["FHAZ", "RHAZ"],
        "rules": {
            "pds": {
                "filename_prefix_any": ["FLB_", "RLB_"],
                "filename_contains_all": ["ILT_F"],
            },
        },
    },
}

_CAMERA_ALIAS_DEFAULTS: dict[str, list[str]] = {
    "navcam": ["nav cam", "ncam"],
    "hazcam": ["haz cam", "fhaz", "rhaz"],
    "mastcam": ["mast cam", "mcam"],
    "mahli": ["m h l i", "mhli"],
    "mardi": ["m a r d i", "mdi"],
    "chemcam": ["chem cam", "ccam", "rmi"],
}


@st.cache_data(show_spinner=False)
def _load_camera_rules_cached(mtime: float) -> dict[str, Any]:
    # NOTE: the cache-busting argument must NOT start with "_" -- Streamlit's
    # st.cache_data explicitly excludes underscore-prefixed parameters from
    # the cache key hash, which used to silently defeat this exact mtime
    # check (editing camera_rules.json while the app was running had zero
    # effect until a full process restart).
    return _get_catalog_rules_service().load_camera_rules_from_path(
        fallback=_CAMERA_RULES_FALLBACK,
        path=_camera_rules_path(),
    )


def load_camera_rules() -> dict[str, Any]:
    """Return config/camera_rules.json merged over the built-in fallback, re-read whenever the file's mtime changes."""
    p = _camera_rules_path()
    try:
        mtime = float(p.stat().st_mtime) if p.exists() else 0.0
    except Exception:
        mtime = 0.0
    return _load_camera_rules_cached(mtime)


def _norm_token_list(values: Any) -> list[str]:
    return _get_catalog_rules_service().norm_token_list(values)


def _norm_alias_list(values: Any) -> list[str]:
    return _get_catalog_rules_service().norm_alias_list(values)


def _compact_ascii(text: str) -> str:
    return _get_catalog_rules_service().compact_ascii(text)


@st.cache_data(show_spinner=False)
def _load_compiled_camera_rules_cached(mtime: float) -> dict[str, Any]:
    # Same file-state-token requirement as _load_camera_rules_cached above:
    # this had zero arguments before, so it never recompiled after the first
    # call in a running process, regardless of camera_rules.json changing.
    raw = _load_camera_rules_cached(mtime)
    return _get_catalog_rules_service().compile_camera_rules(
        raw,
        camera_alias_defaults=_CAMERA_ALIAS_DEFAULTS,
    )


def load_compiled_camera_rules() -> dict[str, Any]:
    """Return `load_camera_rules()` pre-compiled into the flat per-camera-key matcher list the filter service consumes."""
    p = _camera_rules_path()
    try:
        mtime = float(p.stat().st_mtime) if p.exists() else 0.0
    except Exception:
        mtime = 0.0
    return _load_compiled_camera_rules_cached(mtime)


def apply_filters(progress: Optional[Callable[[float, str], None]] = None) -> int:
    """Load the catalog, apply `st.session_state["filters"]`, and store the resulting DataFrame back into session_state. Returns the row count."""
    return _get_catalog_apply_filters_service().apply_filters(st.session_state, progress=progress)


def _filters_cache_key(filters: dict[str, Any], token: str) -> str:
    return _get_catalog_apply_filters_service().filters_cache_key(filters, token)


def deduplicate_with_source_priority(df: pd.DataFrame) -> pd.DataFrame:
    """Drop duplicate products across PDS/RAW sources, keeping the higher-priority source's row for each."""
    return _get_catalog_df_ops_service().deduplicate_with_source_priority(df)


def reduce_raw_burst_sequences(df: pd.DataFrame, keep_per_group: int = 1) -> pd.DataFrame:
    """Collapse RAW Archive burst sequences (many near-identical frames) down to `keep_per_group` rows per burst."""
    return _get_catalog_df_ops_service().reduce_raw_burst_sequences(df, keep_per_group=keep_per_group)


def filter_dataframe(
    df: pd.DataFrame,
    filters: dict[str, Any],
    progress: Optional[Callable[[float, str], None]] = None,
) -> pd.DataFrame:
    """Apply a `filters` dict (Sol range, cameras, source, min size, camera-rules...) to `df` and return the matching rows."""
    return _get_catalog_filter_service().filter_dataframe(df, filters, progress=progress)
