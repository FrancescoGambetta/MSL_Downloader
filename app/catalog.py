from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd
import streamlit as st

from services.catalog_filter_service import CatalogFilterService
from services.catalog_dataframe_ops_service import CatalogDataframeOpsService
from services.catalog_apply_filters_service import CatalogApplyFiltersService
from services.catalog_analytics_service import CatalogAnalyticsService
from services.catalog_rules_service import CatalogRulesService
from runtime import (
    _resolve_selection_store,
    load_json,
    normalize_text,
    persist_selection_from_filtered,
    save_selected_row_ids,
)

_T: Callable[..., str] = lambda key, **kwargs: key.format(**kwargs) if kwargs else key

_CATALOG_RULES_SERVICE: CatalogRulesService | None = None
_CATALOG_FILTER_SERVICE: CatalogFilterService | None = None
_CATALOG_DF_OPS_SERVICE: CatalogDataframeOpsService | None = None
_CATALOG_APPLY_FILTERS_SERVICE: CatalogApplyFiltersService | None = None
_CATALOG_ANALYTICS_SERVICE: CatalogAnalyticsService | None = None


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


def _get_catalog_analytics_service() -> CatalogAnalyticsService:
    global _CATALOG_ANALYTICS_SERVICE
    if _CATALOG_ANALYTICS_SERVICE is None:
        _CATALOG_ANALYTICS_SERVICE = CatalogAnalyticsService(
            normalize_text=normalize_text,
            norm_ascii=_norm_ascii,
        )
    return _CATALOG_ANALYTICS_SERVICE


def _norm_ascii(text: str) -> str:
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
def _load_camera_rules_cached(_mtime: float) -> dict[str, Any]:
    return _get_catalog_rules_service().load_camera_rules_from_path(
        fallback=_CAMERA_RULES_FALLBACK,
        path=_camera_rules_path(),
    )


def load_camera_rules() -> dict[str, Any]:
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
def load_compiled_camera_rules() -> dict[str, Any]:
    raw = load_camera_rules()
    return _get_catalog_rules_service().compile_camera_rules(
        raw,
        camera_alias_defaults=_CAMERA_ALIAS_DEFAULTS,
    )


def _normalize_camera_key(text: str) -> str:
    return _norm_ascii(text)


def _parse_cameras(text: str, available: list[str]) -> list[str]:
    cmd = _norm_ascii(text)
    available_norm = { _norm_ascii(c): c for c in available if normalize_text(c) }
    if not available_norm:
        return []
    if any(re.search(rf"\b{re.escape(w)}\b", cmd) for w in ("all", "tutte", "tutti", "tutto", "toutes", "todos", "alle")):
        return [available_norm[k] for k in sorted(available_norm)]
    picked: list[str] = []
    for norm_key, orig in available_norm.items():
        if re.search(rf"\b{re.escape(norm_key)}\b", cmd):
            picked.append(orig)
    return picked


def _wants_all_cameras(text: str) -> bool:
    cmd = _norm_ascii(text)
    return bool(re.search(r"\b(?:all|tutte|tutti|tutto|toutes|todos|alle)\b", cmd))


def _parse_dr_variants(text: str) -> list[str]:
    cmd = _norm_ascii(text)
    out: list[str] = []
    for tok in ("drcl", "drcx", "drxx", "edr", "rdr"):
        if re.search(rf"\b{tok}\b", cmd):
            out.append(tok.upper())
    return out


def _parse_size_bytes_from_text(text: str) -> Optional[int]:
    t = text.lower().replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(kb|mb|gb|b)\b", t, re.IGNORECASE)
    if not m:
        m = re.search(r"(?:>=|>|min(?:imum)?|almeno|piu grandi di|piu grande di)\s*(\d{3,})\b", t, re.IGNORECASE)
        if m:
            try:
                return int(float(m.group(1)))
            except Exception:
                return None
        return None
    try:
        value = float(m.group(1))
    except Exception:
        return None
    unit = m.group(2).lower()
    if unit == "kb":
        return int(value * 1024)
    if unit == "mb":
        return int(value * 1024 * 1024)
    if unit == "gb":
        return int(value * 1024 * 1024 * 1024)
    return int(value)


def _is_camera_list_request(text: str) -> bool:
    cmd = _norm_ascii(text)

    def _has_any(words: list[str]) -> bool:
        return any(re.search(rf"\b{re.escape(w)}\b", cmd) for w in words)

    camera_words = ["camera", "cameras", "camere", "camara", "camaras", "kamera", "kameras", "instrument", "instruments"]
    list_words = ["list", "lista", "elenco", "show", "mostra", "display", "which", "quali", "what", "dammi", "fammi"]
    action_words = ["scaric", "download", "process", "convert", "organizz", "organize", "selezion", "select", "random", "casual", "sol", "kb", "mb"]
    has_action = any(re.search(rf"\b{w}\w*\b", cmd) for w in action_words)
    return _has_any(camera_words) and _has_any(list_words) and not has_action


def apply_filters(progress: Optional[Callable[[float, str], None]] = None) -> int:
    return _get_catalog_apply_filters_service().apply_filters(st.session_state, progress=progress)


def _filters_cache_key(filters: dict[str, Any], token: str) -> str:
    return _get_catalog_apply_filters_service().filters_cache_key(filters, token)


def selection_report() -> str:
    return _get_catalog_analytics_service().selection_report(st.session_state, t=_T)


def catalog_content_report(*, use_filtered: bool = True) -> str:
    return _get_catalog_analytics_service().catalog_content_report(
        st.session_state,
        t=_T,
        use_filtered=use_filtered,
    )


def camera_types_report() -> str:
    return _get_catalog_analytics_service().camera_types_report(st.session_state, t=_T)


def _query_uses_filtered_context(cmd: str) -> bool:
    return _get_catalog_analytics_service().query_uses_filtered_context(cmd)


def _query_uses_global_context(cmd: str) -> bool:
    return _get_catalog_analytics_service().query_uses_global_context(cmd)


def _filters_active() -> bool:
    f = st.session_state.get("filters", {}) or {}
    if f.get("sol_start") is not None or f.get("sol_end") is not None:
        return True
    if f.get("min_img_size") is not None:
        return True
    if bool(f.get("only_with_lbl")):
        return True
    if f.get("cameras"):
        return True
    if bool(f.get("source_pds", True)) is False or bool(f.get("source_raw", True)) is False:
        return True
    if f.get("dr_variants"):
        return True
    if f.get("name_tokens"):
        return True
    if f.get("file_prefixes"):
        return True
    if f.get("file_name_contains"):
        return True
    for k in (
        "mastcam_only_drcl",
        "mahli_only_drcl",
        "mardi_only_e01_drcx",
        "navcam_only_iltlf",
        "hazcam_only_lb_edr",
        "raw_mahli_legacy_subset",
        "raw_reduce_bursts",
    ):
        if bool(f.get(k)):
            return True
    return False


def analytics_use_filtered_scope(command: str) -> bool:
    return _get_catalog_analytics_service().analytics_use_filtered_scope(
        st.session_state,
        command,
        filters_active=_filters_active,
    )


def report_scope_text(*, use_filtered: bool) -> str:
    return _get_catalog_analytics_service().report_scope_text(st.session_state, t=_T, use_filtered=use_filtered)


def _count_query_camera_matches(cmd: str, available_cameras: list[str]) -> list[str]:
    return _get_catalog_analytics_service().count_query_camera_matches(cmd, available_cameras)


def _query_is_count(cmd: str) -> bool:
    return _get_catalog_analytics_service().query_is_count(cmd)


def _query_is_max_sol(cmd: str) -> bool:
    return _get_catalog_analytics_service().query_is_max_sol(cmd)


def is_analytics_query(command: str) -> bool:
    return _get_catalog_analytics_service().is_analytics_query(command)


def _parse_size_bytes_from_query(text: str) -> Optional[int]:
    return _get_catalog_analytics_service().parse_size_bytes_from_query(text)




def _parse_sol_range_from_query(text: str) -> tuple[Optional[int], Optional[int]]:
    return _get_catalog_analytics_service().parse_sol_range_from_query(text)


def deduplicate_with_source_priority(df: pd.DataFrame) -> pd.DataFrame:
    return _get_catalog_df_ops_service().deduplicate_with_source_priority(df)


def reduce_raw_burst_sequences(df: pd.DataFrame, keep_per_group: int = 1) -> pd.DataFrame:
    return _get_catalog_df_ops_service().reduce_raw_burst_sequences(df, keep_per_group=keep_per_group)

def filter_dataframe(
    df: pd.DataFrame,
    filters: dict[str, Any],
    progress: Optional[Callable[[float, str], None]] = None,
) -> pd.DataFrame:
    return _get_catalog_filter_service().filter_dataframe(df, filters, progress=progress)


def _format_size_human(size_bytes: int) -> str:
    return _get_catalog_analytics_service().format_size_human(size_bytes)


def database_count_report(command: str, *, use_filtered: bool = False) -> str:
    return _get_catalog_analytics_service().database_count_report(
        st.session_state,
        command,
        t=_T,
        use_filtered=use_filtered,
    )


def database_max_sol_report(command: str, *, use_filtered: bool = False) -> str:
    return _get_catalog_analytics_service().database_max_sol_report(
        st.session_state,
        command,
        t=_T,
        use_filtered=use_filtered,
    )
