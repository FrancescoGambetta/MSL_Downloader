from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd
import streamlit as st


def render_builder_sidebar(
    *,
    t: Callable[..., str],
    normalize_text: Callable[[Any], str],
    load_app_ui_config: Callable[[], dict[str, Any]],
    save_app_ui_config: Callable[[dict[str, Any]], None],
    append_user_action: Callable[..., Any],
    save_user_last_state: Callable[[str], Any],
    end_user_session: Callable[[], Any],
    bytes_to_kb_text: Callable[[Any], str],
    sync_builder_inputs_from_filters: Callable[[], None],
    apply_filters: Callable[..., Any],
    reset_filters_state: Callable[..., int],
    load_camera_rules: Callable[[], dict[str, Any]],
    choose_download_path_dialog: Callable[[], tuple[bool, str]],
    set_download_path: Callable[..., Any],
    load_selected_image_outputs: Callable[[str], Any],
    submit_command: Callable[..., Any],
    run_builder_download_process_organize: Callable[..., Any],
    progress_slot: Any,
) -> None:
    with st.sidebar:
        st.markdown(f'<div class="ai-heart"><div class="ai-heart-title">{t("ai_agent_title")}</div></div>', unsafe_allow_html=True)
        current_user_name = normalize_text(st.session_state.get("current_user_name"))
        if current_user_name:
            st.caption(t("current_user_caption", user=current_user_name))
        if st.button(t("logout_button"), width="stretch", key="logout_btn"):
            append_user_action("logout")
            save_user_last_state("logout")
            end_user_session()
            st.session_state.is_authenticated = False
            st.session_state.current_view = "login"
            st.session_state.current_user_name = ""
            st.session_state.current_user_norm = ""
            st.session_state.current_session_id = ""
            st.session_state.login_pending_user_name = ""
            st.session_state.login_pending_user_norm = ""
            st.session_state.login_pending_started_at = ""
            # Reset login input state so Enter-only login works right after logout.
            st.session_state.login_name_input = ""
            st.session_state.login_submit_requested = False
            st.session_state.login_name_widget_key = ""
            st.session_state.boot_poll_count = 0
            st.rerun()
        st.markdown("<div class='sb-sep'></div>", unsafe_allow_html=True)
        st.session_state.ui_mode = "builder"
        ui_cfg = load_app_ui_config()
        if normalize_text(ui_cfg.get("ui_mode")).lower() != "builder":
            ui_cfg["ui_mode"] = "builder"
            save_app_ui_config(ui_cfg)

        def _int_or_none(raw: str) -> Optional[int]:
            txt = normalize_text(raw)
            if not txt:
                return None
            try:
                return int(txt)
            except Exception:
                return None

        def _collect_builder_filters() -> tuple[dict[str, Any], Optional[int]]:
            updated = dict(st.session_state.get("filters", {}))
            updated["sol_start"] = _int_or_none(st.session_state.get("builder_sol_start_text"))
            updated["sol_end"] = _int_or_none(st.session_state.get("builder_sol_end_text"))
            updated["cameras"] = [str(v) for v in (st.session_state.get("builder_cameras_selected") or []) if str(v).strip()]
            updated["source_pds"] = bool(st.session_state.get("builder_source_pds", True))
            updated["source_raw"] = bool(st.session_state.get("builder_source_raw", True))
            # Mastcam RAW: always include C00 products (they require debayer).
            updated["mastcam_raw_include_c00"] = True
            min_size_kb = _int_or_none(st.session_state.get("builder_min_img_size_text"))
            updated["min_img_size"] = None if min_size_kb is None else max(0, int(min_size_kb)) * 1024

            # Builder UI does not expose advanced filename/variant filters; reset them so
            # old parser-mode state can't silently zero-out results.
            updated["only_with_lbl"] = False
            updated["dr_variants"] = []
            updated["name_tokens"] = []
            updated["file_prefixes"] = []
            updated["file_name_contains"] = []
            # Enable camera-specific rules only for selected cameras.
            cams_norm = {normalize_text(c).strip().lower() for c in (updated.get("cameras") or [])}
            updated["mastcam_only_drcl"] = ("mastcam" in cams_norm) if cams_norm else False
            updated["mahli_only_drcl"] = ("mahli" in cams_norm) if cams_norm else False
            updated["mardi_only_e01_drcx"] = ("mardi" in cams_norm) if cams_norm else False
            updated["navcam_only_iltlf"] = ("navcam" in cams_norm) if cams_norm else False
            updated["hazcam_only_lb_edr"] = ("hazcam" in cams_norm) if cams_norm else False
            max_images = _int_or_none(st.session_state.get("builder_max_images_text"))
            return updated, max_images

        current_filters = dict(st.session_state.get("filters", {}))
        if "builder_sol_start_text" not in st.session_state:
            st.session_state.builder_sol_start_text = "" if current_filters.get("sol_start") is None else str(current_filters.get("sol_start"))
        if "builder_sol_end_text" not in st.session_state:
            st.session_state.builder_sol_end_text = "" if current_filters.get("sol_end") is None else str(current_filters.get("sol_end"))
        if "builder_min_img_size_text" not in st.session_state:
            st.session_state.builder_min_img_size_text = bytes_to_kb_text(current_filters.get("min_img_size"))
        if "builder_source_pds" not in st.session_state:
            st.session_state.builder_source_pds = bool(current_filters.get("source_pds", True))
        if "builder_source_raw" not in st.session_state:
            st.session_state.builder_source_raw = bool(current_filters.get("source_raw", True))
        if "builder_cameras_selected" not in st.session_state:
            st.session_state.builder_cameras_selected = [str(v) for v in (current_filters.get("cameras") or []) if str(v).strip()]
            st.session_state.builder_cameras_sync_needed = True
        if "builder_max_images_text" not in st.session_state:
            st.session_state.builder_max_images_text = normalize_text(st.session_state.get("builder_max_images"))

        cam_options: list[str] = []
        df_all = st.session_state.get("df")
        if isinstance(df_all, pd.DataFrame) and "camera" in df_all.columns:
            cam_options = sorted({str(v) for v in df_all["camera"].dropna().astype(str) if str(v).strip()})
        if not cam_options:
            cam_options = ["hazcam", "mahli", "mardi", "mastcam", "navcam"]

        # Hide cameras that are not ready for the UI yet (they may still exist in catalogs).
        hidden_cameras = {"chemcam"}
        cam_options = [
            cam
            for cam in cam_options
            if normalize_text(cam).strip().lower() not in hidden_cameras
        ]

        selected_now = [str(v) for v in (st.session_state.get("builder_cameras_selected") or []) if str(v).strip()]
        selected_valid = [v for v in selected_now if v in cam_options]
        if selected_valid != selected_now:
            st.session_state.builder_cameras_selected = selected_valid

        sync_needed = bool(st.session_state.get("builder_cameras_sync_needed", False))
        for cam in cam_options:
            cam_key = f"builder_camera_chk_{cam.lower()}"
            if sync_needed or cam_key not in st.session_state:
                st.session_state[cam_key] = cam in selected_valid
        st.session_state.builder_cameras_sync_needed = False
        all_checked_now = bool(cam_options) and all(
            bool(st.session_state.get(f"builder_camera_chk_{cam.lower()}", False)) for cam in cam_options
        )

        st.caption(t("builder_mode_hint"))

        with st.form("builder_controls_form", clear_on_submit=False, enter_to_submit=False):
            st.markdown(f"### {t('builder_section_sol_title')}")
            st.caption(t("builder_section_sol_caption"))
            st.text_input(t("builder_sol_start_label"), key="builder_sol_start_text")
            st.text_input(t("builder_sol_end_label"), key="builder_sol_end_text")
            st.divider()

            st.markdown(f"### {t('builder_section_camera_title')}")
            st.caption(t("builder_section_camera_caption"))
            all_cameras_checked = st.checkbox(t("builder_cameras_select_all"), value=all_checked_now, key="builder_camera_all_checkbox")
            if all_cameras_checked:
                for cam in cam_options:
                    st.session_state[f"builder_camera_chk_{cam.lower()}"] = True
            cam_cols = st.columns(2)
            for idx, cam in enumerate(cam_options):
                cam_key = f"builder_camera_chk_{cam.lower()}"
                cam_cols[idx % 2].checkbox(cam, key=cam_key)

            selected_after = [cam for cam in cam_options if bool(st.session_state.get(f"builder_camera_chk_{cam.lower()}", False))]
            if selected_after:
                st.caption(t("builder_cameras_selected_caption", count=len(selected_after), values=", ".join(selected_after)))
            else:
                st.caption(t("builder_cameras_selected_empty"))
            st.divider()

            st.markdown(f"### {t('builder_section_filters_title')}")
            st.caption(t("builder_section_filters_caption"))
            st.text_input(t("builder_min_img_size_label"), key="builder_min_img_size_text")
            st.text_input(t("builder_max_images_label"), key="builder_max_images_text")
            st.markdown(f"### {t('builder_section_catalog_title')}")
            st.caption(t("builder_section_catalog_caption"))
            src_left, src_right = st.columns(2)
            with src_left:
                st.checkbox("PDS", key="builder_source_pds")
            with src_right:
                st.checkbox("RAW archive", key="builder_source_raw")
            st.divider()

            # Organization settings (the workflow always runs: Download + Process + Organize).
            st.markdown(f"### {t('builder_section_organize_title')}")
            st.caption(t("builder_section_organize_caption"))
            org_left, org_right = st.columns(2)
            with org_left:
                st.checkbox(
                    t("organize_divide_by_camera_type"),
                    key="organize_divide_by_camera_type",
                )
            with org_right:
                st.checkbox(
                    t("organize_divide_by_sol"),
                    key="organize_divide_by_sol",
                )

            builder_apply = st.form_submit_button(t("builder_apply_filters_button"), use_container_width=True)
            builder_clear_filters_inline = st.form_submit_button(t("clear_filters_button"), use_container_width=True)

        st.session_state.builder_cameras_selected = [cam for cam in cam_options if bool(st.session_state.get(f"builder_camera_chk_{cam.lower()}", False))]
        updated_filters, max_images = _collect_builder_filters()
        st.session_state.builder_max_images = max_images

        if builder_clear_filters_inline:
            rows = reset_filters_state()
            sync_builder_inputs_from_filters()
            append_user_action("filters_reset_manual", {"rows": int(rows)})
            save_user_last_state("filters_reset_manual")
            st.rerun()

        if builder_apply:
            st.session_state.filters = updated_filters

        run_requested = st.button(t("builder_download_process_organize"), width="stretch", key="builder_run_btn")
        stop_clicked = st.button(t("stop_button"), width="stretch", key="stop_request_btn_builder")
        if stop_clicked:
            st.session_state.stop_requested = True
            st.warning(t("stop_requested_ui"))

        st.markdown("<div class='sb-sep'></div>", unsafe_allow_html=True)

        with st.expander(t("applied_filters_title"), expanded=False):
            current_ui_mode = normalize_text(st.session_state.get("ui_mode")).lower() or "builder"
            if current_ui_mode != "builder" and st.button(t("clear_filters_button"), width="stretch", key="clear_filters_btn"):
                rows = reset_filters_state()
                sync_builder_inputs_from_filters()
                append_user_action("filters_reset_manual", {"rows": int(rows)})
                save_user_last_state("filters_reset_manual")
                st.success(t("filters_reset_rows", rows=rows))
            active_filters = dict(st.session_state.filters)
            if current_ui_mode == "builder":
                sol_start = active_filters.get("sol_start")
                sol_end = active_filters.get("sol_end")
                sol_txt = "-"
                if sol_start is not None and sol_end is not None:
                    sol_txt = f"{min(int(sol_start), int(sol_end))}..{max(int(sol_start), int(sol_end))}"
                elif sol_start is not None:
                    sol_txt = str(sol_start)
                cameras = [str(c) for c in (active_filters.get("cameras") or []) if str(c).strip()]
                cameras_txt = ", ".join(cameras) if cameras else "-"
                min_size = active_filters.get("min_img_size")
                min_size_txt = "-" if min_size is None else str(max(1, int(round(float(min_size) / 1024.0))))
                source_pds = bool(active_filters.get("source_pds", True))
                source_raw = bool(active_filters.get("source_raw", True))
                if source_pds and source_raw:
                    source_txt = "PDS + RAW archive"
                elif source_pds:
                    source_txt = "PDS"
                elif source_raw:
                    source_txt = "RAW archive"
                else:
                    source_txt = "-"
                max_images_val = st.session_state.get("builder_max_images")
                max_images_txt = str(max_images_val) if isinstance(max_images_val, int) and max_images_val > 0 else "-"
                st.caption(t("builder_filters_summary_caption"))
                st.markdown(
                    "\n".join(
                        [
                            f"- {t('builder_summary_sol')}: {sol_txt}",
                            f"- {t('builder_summary_cameras')}: {cameras_txt}",
                            f"- Source: {source_txt}",
                            f"- {t('builder_summary_min_img_size')}: {min_size_txt}",
                            f"- {t('builder_summary_max_images')}: {max_images_txt}",
                            f"- {t('builder_summary_rules')}: {t('yes_label')}",
                        ]
                    )
                )
            else:
                st.caption(t("applied_filters_active_caption"))
                st.code(json.dumps(active_filters, ensure_ascii=False, indent=2))

                rules_raw = load_camera_rules()
                selected_cameras = [str(c) for c in (active_filters.get("cameras") or []) if str(c).strip()]
                selected_norm = {str(c).strip().lower() for c in selected_cameras}
                rule_snapshot: dict[str, dict[str, Any]] = {}
                for cam_name, cam_rule in rules_raw.items():
                    cam = str(cam_name).strip()
                    if not cam:
                        continue
                    if selected_norm and cam.lower() not in selected_norm:
                        continue
                    if not isinstance(cam_rule, dict):
                        continue
                    rule_snapshot[cam] = {
                        "filter_key": normalize_text(cam_rule.get("filter_key")),
                        "min_img_size_bytes": cam_rule.get("min_img_size_bytes"),
                        "suffix_equals_any": cam_rule.get("suffix_equals_any", []),
                        "filename_prefix_any": cam_rule.get("filename_prefix_any", []),
                        "filename_contains_all": cam_rule.get("filename_contains_all", []),
                    }
                st.caption(t("applied_filters_rules_caption"))
                st.code(json.dumps(rule_snapshot, ensure_ascii=False, indent=2))

        st.markdown("<div class='sb-sep'></div>", unsafe_allow_html=True)

        with st.expander(t("selected_images_title"), expanded=False):
            if st.button(t("browse_folders"), width="stretch"):
                ok, path = choose_download_path_dialog()
                if ok:
                    set_download_path(path, persist=True)
                    append_user_action("browse_folders_set_path", {"path": path})
                    save_user_last_state("browse_folders_set_path")
                    st.rerun()
                else:
                    st.warning(t("folder_dialog_disabled"))

            download_path = normalize_text(st.session_state.get("download_path"))
            if download_path:
                folder_name = Path(download_path.rstrip("/\\")).name
                st.caption(t("output_folder_caption", path=folder_name or download_path))

            st.caption(t("saved_files_title"))
            saved_files = st.session_state.get("saved_output_files", []) or []
            if saved_files:
                options = saved_files[:120]
                current_name = normalize_text(st.session_state.get("saved_output_selected_name"))
                default_idx = options.index(current_name) if current_name in options else 0
                picked_name = st.radio(
                    t("saved_files_pick_label"),
                    options,
                    index=default_idx,
                    key="saved_output_selected_name",
                    label_visibility="collapsed",
                )
                load_selected_image_outputs(picked_name)
            else:
                st.caption(t("saved_files_empty"))

        # Run last: keep the whole sidebar rendered (including Stop + Selected images) while the workflow executes.
        if run_requested:
            st.session_state.filters = updated_filters
            st.session_state.builder_max_images = max_images
            prog_ph = st.empty()
            msg_ph = st.empty()
            bar = st.progress(0.0)

            def _on_filter_progress(p: float, msg: str) -> None:
                try:
                    msg_ph.caption(msg)
                    bar.progress(max(0.0, min(1.0, float(p))))
                except Exception:
                    pass

            builder_max_images = st.session_state.get("builder_max_images")
            live_container = progress_slot.container()
            live_md = live_container.empty()

            def _emit(msg: str) -> None:
                txt = normalize_text(msg)
                if not txt:
                    return
                live_body = normalize_text(st.session_state.get("operation_live_text")) or txt
                try:
                    live_md.markdown(
                        f"<div class='live-log'><div class='live-tag'>⟳ {escape(t('live_badge_label'))}</div><div class='msg-text'>{escape(live_body)}</div></div>",
                        unsafe_allow_html=True,
                    )
                except Exception:
                    pass

            ok, _ = run_builder_download_process_organize(
                state=st.session_state,
                filters=updated_filters,
                apply_filters_progress=_on_filter_progress,
                progress_emit=_emit,
                max_images=int(builder_max_images) if isinstance(builder_max_images, int) and builder_max_images > 0 else None,
                wants_organize=True,
            )
            prog_ph.empty()
            msg_ph.empty()
            rows_applied = int(st.session_state.get("filtered_rows_count", 0) or 0)
            try:
                st.success(t("filters_applied_rows", rows=rows_applied))
            except Exception:
                st.success(f"Rows={rows_applied}")
            append_user_action(
                "builder_run_action",
                {
                    "action": "download_process_organize",
                    "rows": rows_applied,
                    "max_images": int(builder_max_images) if isinstance(builder_max_images, int) and builder_max_images > 0 else 0,
                    "bulk_required": bool(not ok),
                },
            )
            save_user_last_state("builder_run_action")
            # If bulk confirmation is required, the existing bulk modal (pending_bulk_action) will take over.
