from __future__ import annotations

from typing import Any, Callable, Sequence

import streamlit as st


def render_configurations_expander(
    *,
    t: Callable[..., str],
    normalize_text: Callable[[Any], str],
    supported_langs: Sequence[str],
    theme_names: Callable[[str], list[str]],
    load_app_ui_config: Callable[[], dict[str, Any]],
    save_app_ui_config: Callable[[dict[str, Any]], None],
    choose_download_path_dialog: Callable[[], tuple[bool, str]],
    set_download_path: Callable[[str, bool], str],
    append_user_action: Callable[..., Any],
    save_user_last_state: Callable[[str], Any],
    mardi_legacy_mode_default: bool,
    mardi_geometric_correction_default: bool,
    mardi_geometric_side_by_side_default: bool,
) -> None:
    with st.expander(f"⚙ {t('configurations_title')}", expanded=False):
        ui_cfg = load_app_ui_config()
        col_cfg_l, col_cfg_r = st.columns([1, 1], gap="small")

        def _render_ui_config(prefix: str) -> None:
            st.markdown(f"#### {t('config_section_ui_title')}")
            st.caption(t("config_section_ui_caption"))

            ui_left, ui_right = st.columns(2, gap="small")
            with ui_left:
                mode_labels = {"dark": t("mode_dark"), "light": t("mode_light")}
                mode_choice = st.selectbox(
                    t("mode_label"),
                    ["dark", "light"],
                    format_func=lambda x: mode_labels.get(x, x),
                    index=0 if st.session_state.mode == "dark" else 1,
                    key=f"{prefix}_mode_select",
                )
                current_lang = st.session_state.lang if st.session_state.lang in supported_langs else "it"
                lang_choice = st.selectbox(
                    t("language_label"),
                    list(supported_langs),
                    index=list(supported_langs).index(current_lang),
                    key=f"{prefix}_lang_select",
                )
            with ui_right:
                dark_names = theme_names("dark")
                light_names = theme_names("light")
                theme_dark_choice = st.selectbox(
                    t("theme_dark_mode"),
                    dark_names,
                    index=dark_names.index(st.session_state.theme_dark),
                    key=f"{prefix}_theme_dark_select",
                )
                theme_light_choice = st.selectbox(
                    t("theme_light_mode"),
                    light_names,
                    index=light_names.index(st.session_state.theme_light),
                    key=f"{prefix}_theme_light_select",
                )

            if st.button(t("save_ui_settings"), width="stretch", key=f"{prefix}_save_ui_settings_btn"):
                ui_cfg["mode"] = mode_choice
                ui_cfg["theme_dark"] = theme_dark_choice
                ui_cfg["theme_light"] = theme_light_choice
                ui_cfg["lang"] = lang_choice
                save_app_ui_config(ui_cfg)
                st.session_state.mode = mode_choice
                st.session_state.theme_dark = theme_dark_choice
                st.session_state.theme_light = theme_light_choice
                st.session_state.lang = lang_choice
                append_user_action(
                    "save_ui_settings",
                    {
                        "mode": mode_choice,
                        "theme_dark": theme_dark_choice,
                        "theme_light": theme_light_choice,
                        "lang": lang_choice,
                        "mardi_legacy_mode": mardi_legacy_mode_default,
                        "mardi_geometric_correction": mardi_geometric_correction_default,
                        "mardi_geometric_side_by_side": mardi_geometric_side_by_side_default,
                    },
                )
                save_user_last_state("save_ui_settings")
                st.rerun()

        def _render_download_config() -> None:
            st.markdown(f"#### {t('config_section_download_title')}")
            st.caption(t("config_section_download_caption"))

            current_download = normalize_text(st.session_state.get("download_path"))
            if (
                "cfg_download_path_input" not in st.session_state
                or st.session_state.get("_last_download_path_for_input") != current_download
            ):
                st.session_state["cfg_download_path_input"] = current_download
                st.session_state["_last_download_path_for_input"] = current_download

            path_col, btn_col = st.columns([0.82, 0.18], gap="small")
            with path_col:
                st.markdown(t("download_path_label"))
                download_path_value = st.text_input(
                    t("download_path_label"),
                    key="cfg_download_path_input",
                    label_visibility="collapsed",
                )
            with btn_col:
                st.markdown(t("config_choose_folder_caption"))
                if st.button(
                    "...",
                    key="cfg_choose_folder_btn",
                    width="stretch",
                    type="secondary",
                ):
                    ok, picked = choose_download_path_dialog()
                    if ok:
                        set_download_path(picked, True)
                        append_user_action("choose_download_path", {"path": picked})
                        save_user_last_state("choose_download_path")
                        st.rerun()

            if st.button(t("save_download_path"), width="stretch", key="cfg_save_download_path_btn"):
                set_download_path(download_path_value, True)
                st.session_state["_last_download_path_for_input"] = normalize_text(st.session_state.get("download_path"))
                append_user_action("save_download_path", {"path": normalize_text(st.session_state.get("download_path"))})
                save_user_last_state("save_download_path")
                st.success(t("download_path_saved"))

        with col_cfg_l:
            _render_ui_config("cfg_ui_left")
        with col_cfg_r:
            _render_download_config()

