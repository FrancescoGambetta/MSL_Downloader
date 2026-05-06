from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import streamlit as st

from services.runtime_paths_service import RuntimePathsService
from services.runtime_selection_store_service import RuntimeSelectionStoreService
from services.runtime_output_index_service import RuntimeOutputIndexService
from services.catalog_io_service import CatalogIOService


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent


def normalize_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return str(v[0]).strip() if v else ""
    return str(v).strip()


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


_APP_DEFAULTS_FALLBACK: dict[str, Any] = {
    "supported_langs": ["it", "en", "fr", "es", "de"],
    "bulk_confirm_threshold": 50,
    "mardi_defaults": {
        "legacy_mode": True,
        "geometric_correction": True,
        "geometric_side_by_side": False,
    },
    "session_defaults": {
        "current_view": "login",
        "is_authenticated": False,
        "current_user_name": "",
        "current_user_norm": "",
        "current_session_id": "",
        "login_pending_user_name": "",
        "login_pending_user_norm": "",
        "login_pending_started_at": "",
        "show_help_popup": False,
        "help_popup_requested": False,
        "help_popup_opened_at": 0.0,
        "help_popup_dismissed": False,
        "ui_mode": "builder",
        "chat_history": [],
        "response_source": "n/a",
        "show_config_dialog": False,
        "last_query_preview": "",
        "operation_live_text": "",
        "is_processing": False,
        "stop_requested": False,
        "pending_bulk_action": None,
        "saved_output_files": [],
        "saved_output_selected_name": "",
        "selected_image": "",
        "selected_image_path": "",
        "selected_meta_path": "",
        "selected_meta_obj": {},
        "filters": {
            "sol_start": None,
            "sol_end": None,
            "cameras": [],
            "source_pds": True,
            "source_raw": True,
            "min_img_size": None,
            "only_with_lbl": False,
            "dr_variants": [],
            "name_tokens": [],
            "file_prefixes": [],
            "file_name_contains": [],
            "mastcam_only_drcl": False,
            "mastcam_raw_include_c00": True,
            "mahli_only_drcl": False,
            "mardi_only_e01_drcx": False,
            "navcam_only_iltlf": False,
            "hazcam_only_lb_edr": False,
        },
    },
}


def _load_app_defaults() -> dict[str, Any]:
    out = copy.deepcopy(_APP_DEFAULTS_FALLBACK)
    p = PROJECT_ROOT / "config" / "app_defaults.json"
    if not p.exists():
        return out
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for key, value in raw.items():
                if isinstance(value, dict) and isinstance(out.get(key), dict):
                    merged = dict(out[key])
                    merged.update(value)
                    out[key] = merged
                else:
                    out[key] = value
    except Exception:
        pass
    return out


_APP_DEFAULTS = _load_app_defaults()
SUPPORTED_LANGS = [str(x).strip() for x in _APP_DEFAULTS.get("supported_langs", _APP_DEFAULTS_FALLBACK["supported_langs"]) if str(x).strip()] or list(_APP_DEFAULTS_FALLBACK["supported_langs"])
DEFAULT_BULK_CONFIRM_THRESHOLD = int(_APP_DEFAULTS.get("bulk_confirm_threshold", _APP_DEFAULTS_FALLBACK["bulk_confirm_threshold"]))
_MARDI_DEFAULTS = _APP_DEFAULTS.get("mardi_defaults", _APP_DEFAULTS_FALLBACK["mardi_defaults"])
MARDI_LEGACY_MODE_DEFAULT = bool(_MARDI_DEFAULTS.get("legacy_mode", _APP_DEFAULTS_FALLBACK["mardi_defaults"]["legacy_mode"]))
MARDI_GEOMETRIC_CORRECTION_DEFAULT = bool(_MARDI_DEFAULTS.get("geometric_correction", _APP_DEFAULTS_FALLBACK["mardi_defaults"]["geometric_correction"]))
MARDI_GEOMETRIC_SIDE_BY_SIDE_DEFAULT = bool(_MARDI_DEFAULTS.get("geometric_side_by_side", _APP_DEFAULTS_FALLBACK["mardi_defaults"]["geometric_side_by_side"]))

_RUNTIME_PATHS_SERVICE: RuntimePathsService | None = None
_RUNTIME_SELECTION_STORE_SERVICE: RuntimeSelectionStoreService | None = None
_RUNTIME_OUTPUT_INDEX_SERVICE: RuntimeOutputIndexService | None = None
_CATALOG_IO_SERVICE: CatalogIOService | None = None


def _get_runtime_paths_service() -> RuntimePathsService:
    global _RUNTIME_PATHS_SERVICE
    if _RUNTIME_PATHS_SERVICE is None:
        _RUNTIME_PATHS_SERVICE = RuntimePathsService(
            project_root=PROJECT_ROOT,
            normalize_text=normalize_text,
            load_json=load_json,
            save_json=save_json,
        )
    return _RUNTIME_PATHS_SERVICE


def _get_runtime_selection_store_service() -> RuntimeSelectionStoreService:
    global _RUNTIME_SELECTION_STORE_SERVICE
    if _RUNTIME_SELECTION_STORE_SERVICE is None:
        _RUNTIME_SELECTION_STORE_SERVICE = RuntimeSelectionStoreService(
            resolve_selection_store=_resolve_selection_store,
            normalize_text=normalize_text,
            now=datetime.now,
        )
    return _RUNTIME_SELECTION_STORE_SERVICE


def _get_runtime_output_index_service() -> RuntimeOutputIndexService:
    global _RUNTIME_OUTPUT_INDEX_SERVICE
    if _RUNTIME_OUTPUT_INDEX_SERVICE is None:
        _RUNTIME_OUTPUT_INDEX_SERVICE = RuntimeOutputIndexService(
            normalize_text=normalize_text,
            display_image_name_from_output_file=_display_image_name_from_output_file,
            now=datetime.now,
        )
    return _RUNTIME_OUTPUT_INDEX_SERVICE


def _get_catalog_io_service() -> CatalogIOService:
    global _CATALOG_IO_SERVICE
    if _CATALOG_IO_SERVICE is None:
        _CATALOG_IO_SERVICE = CatalogIOService()
    return _CATALOG_IO_SERVICE


def _runtime_paths_path() -> Path:
    return _get_runtime_paths_service().runtime_paths_path()


@st.cache_data(show_spinner=False)
def load_runtime_paths() -> dict[str, Any]:
    return _get_runtime_paths_service().load_runtime_paths_uncached()


def _resolve_path(key: str, default_rel: str) -> Path:
    cfg = load_runtime_paths()
    return _get_runtime_paths_service().resolve_path(cfg=cfg, key=key, default_rel=default_rel)


def _resolve_catalog_parquet() -> Path:
    return _get_runtime_paths_service().resolve_catalog_parquet(cfg=load_runtime_paths())


def _resolve_catalog_parquet_raw() -> Path:
    return _get_runtime_paths_service().resolve_catalog_parquet_raw(cfg=load_runtime_paths())


def _resolve_pds_missing_sols() -> Path:
    return _get_runtime_paths_service().resolve_pds_missing_sols(cfg=load_runtime_paths())


def _resolve_intent_config() -> Path:
    return _get_runtime_paths_service().resolve_intent_config(cfg=load_runtime_paths())


def _resolve_msl_config() -> Path:
    return _get_runtime_paths_service().resolve_msl_config(cfg=load_runtime_paths())


def _resolve_ui_config() -> Path:
    return _get_runtime_paths_service().resolve_ui_config(cfg=load_runtime_paths())


def _resolve_selection_store() -> Path:
    return _get_runtime_paths_service().resolve_selection_store(cfg=load_runtime_paths())


_UI_CONFIG_TRANSIENT_KEYS = {
    "gemini_api_key",
    "github_token",
}


def _sanitize_app_ui_config(cfg: dict[str, Any]) -> dict[str, Any]:
    return _get_runtime_paths_service().sanitize_app_ui_config(cfg, transient_keys=_UI_CONFIG_TRANSIENT_KEYS)


def load_app_ui_config() -> dict[str, Any]:
    return _get_runtime_paths_service().load_app_ui_config(cfg=load_runtime_paths(), transient_keys=_UI_CONFIG_TRANSIENT_KEYS)


def save_app_ui_config(cfg: dict[str, Any]) -> None:
    _get_runtime_paths_service().save_app_ui_config(
        cfg=load_runtime_paths(),
        value=cfg,
        transient_keys=_UI_CONFIG_TRANSIENT_KEYS,
    )


def _clean_download_path_input(path: str) -> str:
    return _get_runtime_paths_service().clean_download_path_input(path)


def _default_download_path() -> str:
    return _get_runtime_paths_service().default_download_path(cfg=load_runtime_paths())


def _resolve_download_path(path: str) -> str:
    return _get_runtime_paths_service().resolve_download_path(cfg=load_runtime_paths(), path=path)


def _ensure_writable_download_path(path: str) -> tuple[bool, str]:
    return _get_runtime_paths_service().ensure_writable_download_path(cfg=load_runtime_paths(), path=path)


def _display_image_name_from_output_file(filename: str) -> str:
    name = normalize_text(filename)
    if not name:
        return ""
    low = name.lower()
    if low.endswith(".meta.json"):
        return name[: -len(".meta.json")]
    p = Path(name)
    ext = p.suffix.lower()
    if ext in {".jpg", ".jpeg", ".png", ".img", ".lbl"}:
        return p.stem
    return ""


def _refresh_saved_output_files(limit: int = 400) -> None:
    _get_runtime_output_index_service().refresh_saved_output_files(st.session_state, limit=limit)


def _output_bucket_roots(out: Path) -> list[Path]:
    return _get_runtime_output_index_service().output_bucket_roots(out)


def _output_index_base_name(filename: str) -> str:
    return _get_runtime_output_index_service().output_index_base_name(filename)


def _ensure_output_file_index(out: Path, *, force: bool = False) -> dict[str, Any]:
    return _get_runtime_output_index_service().ensure_output_file_index(st.session_state, out, force=force)


def _index_note_new_file(out: Path, file_path: Path) -> None:
    _get_runtime_output_index_service().index_note_new_file(st.session_state, out, file_path)


def _find_file_by_exact_name(out: Path, filename: str, *, max_dirs: int = 12000) -> Optional[Path]:
    return _get_runtime_output_index_service().find_file_by_exact_name(out, filename, max_dirs=max_dirs)


def _track_saved_output_file(filename: str) -> None:
    _get_runtime_output_index_service().track_saved_output_file(st.session_state, filename)


def _resolve_output_files_for_product(product_name: str) -> tuple[Optional[Path], Optional[Path]]:
    return _get_runtime_output_index_service().resolve_output_files_for_product(st.session_state, product_name)


@st.cache_data(show_spinner=False)
def load_catalog(path: str, columns: Optional[list[str]] = None) -> pd.DataFrame:
    return _get_catalog_io_service().load_catalog(path, columns=columns)


def prepare_catalog_index(df: pd.DataFrame) -> pd.DataFrame:
    return _get_catalog_io_service().prepare_catalog_index(df)


def load_selected_row_ids() -> list[int]:
    return _get_runtime_selection_store_service().load_selected_row_ids()


def save_selected_row_ids(row_ids: list[int]) -> None:
    _get_runtime_selection_store_service().save_selected_row_ids(st.session_state, row_ids)


def get_selected_images_df() -> pd.DataFrame:
    return _get_runtime_selection_store_service().get_selected_images_df(st.session_state)


def persist_selection_from_filtered() -> int:
    return _get_runtime_selection_store_service().persist_selection_from_filtered(st.session_state)
