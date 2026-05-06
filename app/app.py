from __future__ import annotations

import json
import re
import sys
import time
from html import escape
from pathlib import Path
from typing import Any, Optional

import streamlit as st
from streamlit.components.v1 import html as components_html
try:
    import markdown as markdown_lib
except Exception:  # pragma: no cover
    markdown_lib = None
try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None
try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None

from Styles.themes import DEFAULT_MODE, DEFAULT_THEME_BY_MODE, MODE_THEMES, get_theme, normalize_mode, theme_names
from Styles.css import build_app_css
from i18n_helper import load_i18n, translate
from ui_panels.config_panel import render_configurations_expander
from ui_panels.builder_sidebar import render_builder_sidebar
from ui_panels.bulk_modal import render_bulk_confirmation_ui
from ui_panels.live_log import render_live_log
from ui_panels.viewport_panel import render_viewport_panel
from ui_panels.metadata_panel import render_metadata_panel
from runtime import (
    DEFAULT_BULK_CONFIRM_THRESHOLD,
    MARDI_GEOMETRIC_CORRECTION_DEFAULT,
    MARDI_GEOMETRIC_SIDE_BY_SIDE_DEFAULT,
    MARDI_LEGACY_MODE_DEFAULT,
    SUPPORTED_LANGS,
    _APP_DEFAULTS,
    _APP_DEFAULTS_FALLBACK,
    _clean_download_path_input,
    _default_download_path,
    _display_image_name_from_output_file,
    _ensure_writable_download_path,
    _refresh_saved_output_files,
    _resolve_catalog_parquet,
    _resolve_download_path,
    _resolve_intent_config,
    _resolve_msl_config,
    _resolve_output_files_for_product,
    _resolve_path,
    _resolve_selection_store,
    _resolve_ui_config,
    _track_saved_output_file,
    get_selected_images_df,
    load_app_ui_config,
    load_catalog,
    load_json,
    load_runtime_paths,
    load_selected_row_ids,
    normalize_text,
    persist_selection_from_filtered,
    prepare_catalog_index,
    save_app_ui_config,
    save_json,
    save_selected_row_ids,
)
from session import (
    _append_user_action,
    _end_user_session,
    _ensure_heavy_state,
    _get_latest_session_info,
    _kickoff_login_preload,
    _resume_user_session,
    _save_user_last_state,
    _start_user_session,
    init_state,
)
from catalog import (
    apply_filters,
    camera_types_report,
    catalog_content_report,
    load_camera_rules,
    selection_report,
    set_translator,
)

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
I18N = load_i18n(str(APP_DIR / "i18n_app.json"))
st.set_page_config(page_title="MSL Real App", page_icon="🔴", layout="wide", initial_sidebar_state="expanded")
CORE_DIR = PROJECT_ROOT / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))
from portable_engine_adapter import download_records, process_records_with_engine, records_from_dataframe  # type: ignore
from catalog_runner import CatalogUpdateOptions, run_catalog_update  # type: ignore

def t(key: str, **kwargs: Any) -> str:
    lang = st.session_state.get("lang", "it")
    try:
        return translate(I18N, lang, key, **kwargs)
    except Exception:
        return key.format(**kwargs) if kwargs else key


set_translator(t)
from parser import (
    _append_parser_debug,
    _bulk_cancel_words,
    _bulk_cancelled_text,
    _bulk_confirmation_text,
    _bulk_proceed_words,
    _cfg_keywords,
    _contains_word,
    _has_download_intent,
    _has_process_intent,
    _has_workflow_action_words,
    _humanize_parser_response,
    _intent_match,
    _is_camera_list_request,
    _is_unsupported_image_url_request,
    _normalize_camera_key,
    _normalize_command_for_parser,
    _no_pending_bulk_text,
    _parse_camera_quota_map,
    _parse_cameras,
    _parse_each_camera_count,
    _parse_int,
    _parse_requested_image_count,
    _parse_size_bytes_from_text,
    _parse_sol_range,
    _parser_validation_note,
    _wants_all_cameras,
    _wants_organize_step,
    _wants_random_sample,
)
from actions import (
    _apply_mardi_geometric_correction,
    _camera_folder_for_filename,
    _count_records_for_action,
    _load_selected_image_outputs,
    _mardi_geometric_correction_enabled,
    _mardi_legacy_mode_enabled,
    _mardi_side_by_side_enabled,
    _maybe_correct_mardi_products,
    _parse_cfg_value,
    _reset_filters_state,
    _parse_set_config,
    _prepare_action_df,
    _set_nested,
    choose_download_path_dialog,
    download_geo_csv,
    execute_action,
    geo_status_text,
    get_selection_df,
    handle_local,
    organize_photos_in_output,
    organize_photos_by_sol_in_output,
    organize_photos_simple_layout,
    run_catalog_update_from_text,
    run_download,
    run_download_and_process_interleaved,
    run_process,
    run_builder_download_process_organize,
    run_sql_query,
    set_download_path,
    set_translator as set_actions_translator,
    show_combined_config_text,
    show_download_path_text,
    submit_command,
)
from help import (
    _help_markdown_to_html,
    _load_help_guide_markdown,
    _render_help_overlay,
    set_translator as set_help_translator,
)
from ui import (
    _format_msg_text_as_html,
    _hero_logo_html,
    _is_preload_done,
    _meta_line_html,
    _render_boot_page,
    _render_login_page,
    set_translator as set_ui_translator,
)

set_actions_translator(t)
set_help_translator(t)
set_ui_translator(t)
_parser_helpers_unused = (
    _append_parser_debug,
    _bulk_cancel_words,
    _bulk_cancelled_text,
    _bulk_confirmation_text,
    _bulk_proceed_words,
    _cfg_keywords,
    _contains_word,
    _has_download_intent,
    _has_process_intent,
    _has_workflow_action_words,
    _humanize_parser_response,
    _intent_match,
    _is_camera_list_request,
    _is_unsupported_image_url_request,
    _normalize_camera_key,
    _normalize_command_for_parser,
    _no_pending_bulk_text,
    _parse_camera_quota_map,
    _parse_cameras,
    _parse_each_camera_count,
    _parse_int,
    _parse_requested_image_count,
    _parse_size_bytes_from_text,
    _parse_sol_range,
    _parser_validation_note,
    _wants_all_cameras,
    _wants_organize_step,
    _wants_random_sample,
)


def ui_main() -> None:
    init_state()

    st.session_state.mode = normalize_mode(st.session_state.get("mode", DEFAULT_MODE))
    if st.session_state.theme_dark not in MODE_THEMES["dark"]:
        st.session_state.theme_dark = DEFAULT_THEME_BY_MODE["dark"]
    if st.session_state.theme_light not in MODE_THEMES["light"]:
        st.session_state.theme_light = DEFAULT_THEME_BY_MODE["light"]
    if st.session_state.lang not in SUPPORTED_LANGS:
        st.session_state.lang = "it"
    if normalize_text(st.session_state.get("ui_mode")).lower() not in {"parser", "builder"}:
        st.session_state.ui_mode = "builder"

    def _bytes_to_kb_text(raw: Any) -> str:
        if raw is None:
            return ""
        try:
            b = int(float(raw))
            if b <= 0:
                return ""
            return str(max(1, int(round(b / 1024.0))))
        except Exception:
            return ""

    def _sync_builder_inputs_from_filters() -> None:
        f = dict(st.session_state.get("filters", {}))
        st.session_state.builder_sol_start_text = "" if f.get("sol_start") is None else str(f.get("sol_start"))
        st.session_state.builder_sol_end_text = "" if f.get("sol_end") is None else str(f.get("sol_end"))
        st.session_state.builder_min_img_size_text = _bytes_to_kb_text(f.get("min_img_size"))
        st.session_state.builder_cameras_selected = [str(v) for v in (f.get("cameras") or []) if str(v).strip()]
        st.session_state.builder_source_pds = bool(f.get("source_pds", True))
        st.session_state.builder_source_raw = bool(f.get("source_raw", True))
        st.session_state.builder_cameras_sync_needed = True

    current_ui_mode = normalize_text(st.session_state.get("ui_mode")).lower() or "builder"
    prev_ui_mode = normalize_text(st.session_state.get("last_ui_mode")).lower() or ""
    if current_ui_mode == "builder" and prev_ui_mode != "builder":
        _sync_builder_inputs_from_filters()
    st.session_state.last_ui_mode = current_ui_mode

    active_theme = st.session_state.theme_dark if st.session_state.mode == "dark" else st.session_state.theme_light
    st.markdown(build_app_css(st.session_state.mode, active_theme), unsafe_allow_html=True)

    st.session_state.current_view = "app" if bool(st.session_state.get("is_authenticated")) else "login"

    if st.session_state.current_view == "login":
        _render_login_page()
        return
    hero_logo_html = _hero_logo_html(st.session_state.mode, active_theme)
    st.markdown(
        f"""
<div class="hero-wrap">
    {hero_logo_html if hero_logo_html else f'<div class="hero-title">{escape(t("hero_title"))}</div>'}
</div>
""",
        unsafe_allow_html=True,
    )

    if bool(st.session_state.get("show_help_popup")):
        help_left, help_right = st.columns([0.88, 0.12], gap="small")
        with help_right:
            if st.button(t("help_trigger_button"), help=t("help_trigger_tooltip"), key="help_trigger_btn", width="stretch"):
                st.session_state.help_popup_requested = True
                st.session_state.help_popup_opened_at = time.time()

        trigger_guard_key = f"help_overlay_closed::{normalize_text(st.session_state.get('current_user_norm'))}::{normalize_text(st.session_state.get('current_session_id'))}"
        trigger_guard_script = f"""
<script>
(function() {{
  try {{
    if (window.parent.localStorage.getItem({json.dumps(trigger_guard_key)}) !== "1") {{
      return;
    }}
  }} catch (err) {{
    return;
  }}
  let parentDoc = document;
  try {{
    if (window.parent && window.parent.document && window.parent.document.body) {{
      parentDoc = window.parent.document;
    }}
  }} catch (err) {{
    parentDoc = document;
  }}
  const trigger = parentDoc.querySelector('[class*="st-key-help_trigger_btn"]');
  if (trigger) {{
    trigger.remove();
  }}
}})();
</script>
"""
        components_html(trigger_guard_script, height=0, width=0)

    if bool(st.session_state.get("help_popup_requested")):
        _render_help_overlay()

    render_configurations_expander(
        t=t,
        normalize_text=normalize_text,
        supported_langs=SUPPORTED_LANGS,
        theme_names=theme_names,
        load_app_ui_config=load_app_ui_config,
        save_app_ui_config=save_app_ui_config,
        choose_download_path_dialog=choose_download_path_dialog,
        set_download_path=set_download_path,
        append_user_action=_append_user_action,
        save_user_last_state=_save_user_last_state,
        mardi_legacy_mode_default=MARDI_LEGACY_MODE_DEFAULT,
        mardi_geometric_correction_default=MARDI_GEOMETRIC_CORRECTION_DEFAULT,
        mardi_geometric_side_by_side_default=MARDI_GEOMETRIC_SIDE_BY_SIDE_DEFAULT,
    )

    progress_slot = st.empty()
    bulk_overlay_slot = st.empty()

    bulk_stage = normalize_text(st.session_state.get("bulk_queue_stage"))
    if bulk_stage == "hide_only":
        st.session_state.bulk_queue_stage = "ready_to_run"
        st.rerun()

    render_builder_sidebar(
        t=t,
        normalize_text=normalize_text,
        load_app_ui_config=load_app_ui_config,
        save_app_ui_config=save_app_ui_config,
        append_user_action=_append_user_action,
        save_user_last_state=_save_user_last_state,
        end_user_session=_end_user_session,
        bytes_to_kb_text=_bytes_to_kb_text,
        sync_builder_inputs_from_filters=_sync_builder_inputs_from_filters,
        apply_filters=apply_filters,
        reset_filters_state=_reset_filters_state,
        load_camera_rules=load_camera_rules,
        choose_download_path_dialog=choose_download_path_dialog,
        set_download_path=set_download_path,
        load_selected_image_outputs=_load_selected_image_outputs,
        submit_command=submit_command,
        run_builder_download_process_organize=run_builder_download_process_organize,
        progress_slot=progress_slot,
    )

    render_bulk_confirmation_ui(t=t, normalize_text=normalize_text, bulk_overlay_slot=bulk_overlay_slot)

    queue_stage_now = normalize_text(st.session_state.get("bulk_queue_stage"))
    if queue_stage_now == "ready_to_run":
        st.session_state.bulk_queue_stage = "run_now"
        st.rerun()

    queued_bulk_command = normalize_text(st.session_state.get("queued_bulk_command"))
    if queued_bulk_command and normalize_text(st.session_state.get("bulk_queue_stage")) == "run_now":
        st.session_state.bulk_queue_stage = ""
        st.session_state.queued_bulk_command = ""
        bulk_overlay_slot.empty()
        live_container = progress_slot.container()
        live_bar = live_container.progress(0.0)
        live_md = live_container.empty()
        submit_command(queued_bulk_command, progress_slot=live_md, progress_bar=live_bar)

    render_live_log(t=t, normalize_text=normalize_text, progress_slot=progress_slot)

    st.markdown('<div class="main-section-gap"></div>', unsafe_allow_html=True)

    main_l, main_r = st.columns([65, 35], gap="small")
    with main_l:
        render_viewport_panel(t=t, normalize_text=normalize_text)

    with main_r:
        render_metadata_panel(t=t, meta_line_html=_meta_line_html)

    if st.session_state.get("last_query_preview"):
        st.subheader(t("last_query_result"))
        st.text(st.session_state["last_query_preview"])


if __name__ == "__main__":
    ui_main()
