from __future__ import annotations

import copy
import json
import threading
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd
import streamlit as st

from Styles.themes import DEFAULT_MODE, DEFAULT_THEME_BY_MODE, MODE_THEMES, normalize_mode
from services.session_store_service import SessionStoreService, _default_now_local, _default_now_utc
from services.session_preload_service import SessionPreloadService
from runtime import (
    DEFAULT_BULK_CONFIRM_THRESHOLD,
    MARDI_GEOMETRIC_CORRECTION_DEFAULT,
    MARDI_GEOMETRIC_SIDE_BY_SIDE_DEFAULT,
    MARDI_LEGACY_MODE_DEFAULT,
    SUPPORTED_LANGS,
    _APP_DEFAULTS,
    _APP_DEFAULTS_FALLBACK,
    _default_download_path,
    _ensure_writable_download_path,
    _refresh_saved_output_files,
    _resolve_catalog_parquet,
    _resolve_catalog_parquet_raw,
    _resolve_intent_config,
    _resolve_download_path,
    get_selected_images_df,
    load_app_ui_config,
    load_catalog,
    load_json,
    normalize_text,
    prepare_catalog_index,
    save_app_ui_config,
)

_SESSION_STORE_SERVICE: SessionStoreService | None = None
_SESSION_PRELOAD_SERVICE: SessionPreloadService | None = None


_PRELOAD_LOCK = threading.Lock()
_PRELOAD_STATE: dict[str, Any] = {
    "started": False,
    "done": False,
    "error": "",
    "catalog_df": None,
    "catalog_df_pds": None,
    "catalog_df_raw": None,
    "data_source": "",
    "intent_cfg": None,
    "intent_cfg_mtime": 0.0,
}


def _sessions_root() -> str:
    from runtime import PROJECT_ROOT
    return str(PROJECT_ROOT / "data" / "sessions")


def _get_session_store_service() -> SessionStoreService:
    global _SESSION_STORE_SERVICE
    if _SESSION_STORE_SERVICE is None:
        from runtime import PROJECT_ROOT

        _SESSION_STORE_SERVICE = SessionStoreService(
            project_root=PROJECT_ROOT,
            normalize_text=normalize_text,
            now_local=_default_now_local,
            now_utc=_default_now_utc,
        )
    return _SESSION_STORE_SERVICE


def _get_session_preload_service() -> SessionPreloadService:
    global _SESSION_PRELOAD_SERVICE
    if _SESSION_PRELOAD_SERVICE is None:
        _SESSION_PRELOAD_SERVICE = SessionPreloadService(
            preload_lock=_PRELOAD_LOCK,
            preload_state=_PRELOAD_STATE,
            normalize_text=normalize_text,
            prepare_catalog_index=prepare_catalog_index,
            load_catalog=load_catalog,
            resolve_catalog_parquet=_resolve_catalog_parquet,
            resolve_catalog_parquet_raw=_resolve_catalog_parquet_raw,
            resolve_intent_config=_resolve_intent_config,
            load_json=load_json,
            get_selected_images_df=get_selected_images_df,
            refresh_saved_output_files=_refresh_saved_output_files,
        )
    return _SESSION_PRELOAD_SERVICE


def _normalize_user_name(name: str) -> str:
    return _get_session_store_service().normalize_user_name(name)


def _user_session_path(user_norm: str):
    return _get_session_store_service().user_session_path(user_norm)


def _load_user_session_data(user_norm: str) -> dict[str, Any]:
    return _get_session_store_service().load_user_session_data(user_norm)


def _save_user_session_data(user_norm: str, data: dict[str, Any]) -> None:
    _get_session_store_service().save_user_session_data(user_norm, data)


def _now_local_iso() -> str:
    return _get_session_store_service().now_local_iso()


def _now_utc_iso() -> str:
    return _get_session_store_service().now_utc_iso()


def _start_user_session(display_name: str) -> tuple[str, str]:
    user_norm, session_id = _get_session_store_service().start_user_session(display_name)
    st.session_state.show_help_popup = True
    st.session_state.help_popup_dismissed = False
    _restore_user_last_state(user_norm)
    return user_norm, session_id


def _get_latest_session_info(user_norm: str) -> Optional[dict[str, Any]]:
    return _get_session_store_service().get_latest_session_info(user_norm)


def _resume_user_session(user_norm: str, display_name: str) -> tuple[str, str]:
    user_norm, session_id = _get_session_store_service().resume_user_session(user_norm, display_name)
    st.session_state.show_help_popup = False
    _restore_user_last_state(user_norm)
    return user_norm, session_id


def _append_user_action(event_type: str, payload: Optional[dict[str, Any]] = None) -> None:
    _get_session_store_service().append_user_action(state=st.session_state, event_type=event_type, payload=payload)


def _snapshot_user_last_state() -> dict[str, Any]:
    """
    Minimal, stable state snapshot to restore the last used UI/settings for a user.

    Avoids transient keys (live logs, caches, selected images, dataframes, etc.).
    """
    mode = normalize_mode(normalize_text(st.session_state.get("mode")) or DEFAULT_MODE)
    theme_dark = normalize_text(st.session_state.get("theme_dark"))
    theme_light = normalize_text(st.session_state.get("theme_light"))
    lang = normalize_text(st.session_state.get("lang"))
    ui_mode = normalize_text(st.session_state.get("ui_mode"))

    dark_themes = MODE_THEMES.get("dark", [])
    light_themes = MODE_THEMES.get("light", [])
    if theme_dark not in dark_themes:
        theme_dark = DEFAULT_THEME_BY_MODE["dark"]
    if theme_light not in light_themes:
        theme_light = DEFAULT_THEME_BY_MODE["light"]
    if lang not in SUPPORTED_LANGS:
        lang = "it"
    if ui_mode not in {"parser", "builder"}:
        ui_mode = "builder"

    filters = st.session_state.get("filters", {}) or {}
    if not isinstance(filters, dict):
        filters = {}

    download_path = normalize_text(st.session_state.get("download_path")) or _default_download_path()
    ok_path, effective_path = _ensure_writable_download_path(download_path)
    download_path = effective_path if ok_path else _default_download_path()

    max_images = st.session_state.get("builder_max_images")
    try:
        max_images = int(max_images) if max_images is not None and str(max_images).strip() else None
    except Exception:
        max_images = None

    return {
        "version": 1,
        "saved_at": _now_local_iso(),
        "saved_at_utc": _now_utc_iso(),
        "mode": mode,
        "theme_dark": theme_dark,
        "theme_light": theme_light,
        "lang": lang,
        "ui_mode": ui_mode,
        "download_path": download_path,
        "organize_divide_by_camera_type": bool(st.session_state.get("organize_divide_by_camera_type", True)),
        "organize_divide_by_sol": bool(st.session_state.get("organize_divide_by_sol", False)),
        "filters": copy.deepcopy(filters),
        "builder_max_images": max_images,
    }


def _restore_user_last_state(user_norm: str) -> None:
    """
    Restore last snapshot (if present) into the current Streamlit session_state.

    Called at login time so that the app view opens pre-filled.
    """
    u = normalize_text(user_norm)
    if not u:
        return
    data = _load_user_session_data(u)
    state = data.get("last_state")
    if not isinstance(state, dict):
        return

    try:
        st.session_state.mode = normalize_mode(normalize_text(state.get("mode")) or DEFAULT_MODE)
    except Exception:
        pass
    try:
        thd = normalize_text(state.get("theme_dark"))
        st.session_state.theme_dark = thd if thd in MODE_THEMES.get("dark", []) else DEFAULT_THEME_BY_MODE["dark"]
    except Exception:
        pass
    try:
        thl = normalize_text(state.get("theme_light"))
        st.session_state.theme_light = thl if thl in MODE_THEMES.get("light", []) else DEFAULT_THEME_BY_MODE["light"]
    except Exception:
        pass
    try:
        lng = normalize_text(state.get("lang"))
        st.session_state.lang = lng if lng in SUPPORTED_LANGS else "it"
    except Exception:
        pass
    try:
        um = normalize_text(state.get("ui_mode"))
        st.session_state.ui_mode = um if um in {"parser", "builder"} else "builder"
    except Exception:
        pass

    try:
        requested = normalize_text(state.get("download_path")) or _default_download_path()
        ok, effective = _ensure_writable_download_path(requested)
        if ok:
            st.session_state.download_path = effective
    except Exception:
        pass

    try:
        st.session_state.organize_divide_by_camera_type = bool(state.get("organize_divide_by_camera_type", True))
        st.session_state.organize_divide_by_sol = bool(state.get("organize_divide_by_sol", False))
    except Exception:
        pass

    filters = state.get("filters")
    if isinstance(filters, dict):
        st.session_state.filters = copy.deepcopy(filters)

    try:
        mx = state.get("builder_max_images")
        if mx is None or (isinstance(mx, str) and not mx.strip()):
            st.session_state.builder_max_images = None
        else:
            st.session_state.builder_max_images = int(mx)
    except Exception:
        pass


def _save_user_last_state(reason: str = "") -> None:
    user_norm = normalize_text(st.session_state.get("current_user_norm"))
    if not user_norm:
        return
    data = _load_user_session_data(user_norm)
    data["last_state"] = _snapshot_user_last_state()
    if reason:
        data["last_state_reason"] = normalize_text(reason)
    _save_user_session_data(user_norm, data)


def _end_user_session() -> None:
    _get_session_store_service().end_user_session(state=st.session_state)


def _with_source(df: pd.DataFrame, source: str) -> pd.DataFrame:
    return _get_session_preload_service().with_source(df, source)


def _combine_catalogs(df_pds: pd.DataFrame, df_raw: pd.DataFrame) -> pd.DataFrame:
    return _get_session_preload_service().combine_catalogs(df_pds, df_raw)


def _catalog_min_columns(source: str) -> list[str]:
    return _get_session_preload_service().catalog_min_columns(source)


def _load_catalog_source(path, source: str) -> pd.DataFrame:
    return _get_session_preload_service().load_catalog_source(path, source)


def _preload_heavy_state_worker() -> None:
    _get_session_preload_service().preload_heavy_state_worker()


def _kickoff_login_preload() -> None:
    _get_session_preload_service().kickoff_login_preload()


def _ensure_heavy_state() -> None:
    _get_session_preload_service().ensure_heavy_state(st.session_state)


def init_state(light_only: bool = False) -> None:
    ui_cfg = load_app_ui_config()
    persisted_mode = normalize_text(ui_cfg.get("mode")) if isinstance(ui_cfg, dict) else ""
    persisted_theme_dark = normalize_text(ui_cfg.get("theme_dark")) if isinstance(ui_cfg, dict) else ""
    persisted_theme_light = normalize_text(ui_cfg.get("theme_light")) if isinstance(ui_cfg, dict) else ""
    persisted_lang = normalize_text(ui_cfg.get("lang")) if isinstance(ui_cfg, dict) else ""
    persisted_ui_mode = normalize_text(ui_cfg.get("ui_mode")) if isinstance(ui_cfg, dict) else ""
    persisted_download_path = _resolve_download_path(normalize_text(ui_cfg.get("download_path"))) if isinstance(ui_cfg, dict) else _default_download_path()

    mode = normalize_mode(persisted_mode or DEFAULT_MODE)
    dark_themes = MODE_THEMES["dark"]
    light_themes = MODE_THEMES["light"]
    theme_dark = persisted_theme_dark if persisted_theme_dark in dark_themes else DEFAULT_THEME_BY_MODE["dark"]
    theme_light = persisted_theme_light if persisted_theme_light in light_themes else DEFAULT_THEME_BY_MODE["light"]

    defaults = copy.deepcopy(_APP_DEFAULTS.get("session_defaults", _APP_DEFAULTS_FALLBACK["session_defaults"]))
    defaults.update(
        {
            "mode": mode,
            "theme_dark": theme_dark,
            "theme_light": theme_light,
            "lang": persisted_lang if persisted_lang in SUPPORTED_LANGS else "it",
            "ui_mode": persisted_ui_mode if persisted_ui_mode in {"parser", "builder"} else "builder",
            "download_path": persisted_download_path,
            "mardi_legacy_mode": MARDI_LEGACY_MODE_DEFAULT,
            "mardi_geometric_correction": MARDI_GEOMETRIC_CORRECTION_DEFAULT,
            "mardi_geometric_side_by_side": MARDI_GEOMETRIC_SIDE_BY_SIDE_DEFAULT,
            "organize_divide_by_camera_type": True,
            "organize_divide_by_sol": False,
        }
    )
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v
    st.session_state["mardi_legacy_mode"] = MARDI_LEGACY_MODE_DEFAULT
    st.session_state["mardi_geometric_correction"] = MARDI_GEOMETRIC_CORRECTION_DEFAULT
    st.session_state["mardi_geometric_side_by_side"] = MARDI_GEOMETRIC_SIDE_BY_SIDE_DEFAULT
    if "organize_divide_by_camera_type" not in st.session_state:
        st.session_state["organize_divide_by_camera_type"] = True
    if "organize_divide_by_sol" not in st.session_state:
        st.session_state["organize_divide_by_sol"] = False

    if not light_only:
        _ensure_heavy_state()
