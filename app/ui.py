from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import streamlit as st

import sys
sys.path.append(str(Path(__file__).resolve().parent))
from Styles.themes import get_theme
from actions import _load_selected_image_outputs, set_download_path
from session import _append_user_action, _get_latest_session_info, _normalize_user_name, _resume_user_session, _start_user_session
from runtime import normalize_text

_T: Callable[..., str] = lambda key, **kwargs: key.format(**kwargs) if kwargs else key


def set_translator(fn: Callable[..., str]) -> None:
    global _T
    _T = fn


def t(key: str, **kwargs: Any) -> str:
    try:
        return _T(key, **kwargs)
    except Exception:
        return key.format(**kwargs) if kwargs else key


def _hero_logo_html(mode: str, theme_name: str) -> str:
    title_path = Path(__file__).resolve().parent.parent / "Title.svg"
    if not title_path.exists():
        return ""
    try:
        svg = title_path.read_text(encoding="utf-8")
    except Exception:
        return ""
    theme = get_theme(mode, theme_name)
    accent = theme.get("accent", "#c77d2b")
    text = theme.get("text", "#f5efe4")
    svg = svg.replace("</svg>", f"<style>.cls-1{{fill:{accent};}}.cls-2{{fill:{text};}}</style></svg>", 1)
    return f'<div class="hero-logo">{svg}</div>'


def _format_msg_text_as_html(text: str) -> str:
    raw = normalize_text(text)
    if not raw:
        return f"<div class='msg-text'>{escape(t('empty_label'))}</div>"
    return f"<div class='msg-text'>{escape(raw)}</div>"


def _render_chat_history_html(history: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for msg in history:
        role = normalize_text(msg.get("role"))
        if role != "ai":
            continue
        source = normalize_text(msg.get("source"))
        hide_source = source in {"parser", "parser_humanized"}
        header = "" if hide_source else (f"[{source}] " if source else "")
        text = normalize_text(msg.get("text"))
        lines.append(f"{header}{text}")
    if not lines:
        return f"<div class='msg-text is-idle'>{escape(t('ai_response_waiting'))}</div>"
    plain = "\n\n".join(lines)
    return f"<div class='msg-text'>{escape(plain)}</div>"


def _meta_line_html(label: str, value: Any, path_like: bool = False) -> str:
    key_html = escape(str(label))
    if value is None:
        value_html = "<span class='meta-value'>(null)</span>"
    else:
        txt = normalize_text(value) if not isinstance(value, (dict, list)) else json.dumps(value, ensure_ascii=False)
        esc = escape(txt)
        if path_like and txt:
            value_html = f"<span class='meta-value meta-path' title=\"{esc}\">{esc}</span>"
        else:
            value_html = f"<span class='meta-value'>{esc}</span>"
    return f"<div class='meta-line'><span class='meta-key'>{key_html}:</span> {value_html}</div>"


def _render_login_page() -> None:
    from session import _get_latest_session_info  # local import avoids cycles during bootstrap

    is_light_mode = normalize_text(st.session_state.get("mode", "dark")) == "light"
    theme_name = st.session_state.theme_light if is_light_mode else st.session_state.theme_dark
    theme = get_theme(st.session_state.mode, theme_name)
    login_input_color = "rgba(32, 42, 53, 0.95)" if is_light_mode else "rgba(238, 232, 220, 0.96)"
    login_placeholder_color = "rgba(32, 42, 53, 0.42)" if is_light_mode else "rgba(238, 232, 220, 0.36)"
    login_accent_color = theme["accent"]
    login_accent_soft_color = theme["accent_soft"]
    login_theme_text = theme["text"]
    login_panel_color = "#fff9ef" if is_light_mode else "#221f1a"
    login_surface_color = "#f8f4eb" if is_light_mode else "#1e1b17"
    login_css = """<style>section.main > div.block-container { padding-top: 0.5rem !important; }</style>"""
    login_css += """
<style>
.login-hero-logo {
  width: min(100%, 350px);
  margin: 0 auto 0.35rem auto;
  max-height: 112px;
  overflow: hidden;
}
.login-hero-logo svg { width: 100%; height: auto; display: block; }
.login-title { text-align: center; font-size: clamp(2.2rem, 4vw, 3.4rem); font-weight: 700; letter-spacing: 0.1em; margin-top: 150px; margin-bottom: 0.55rem; opacity: 0.96; }
.login-subtitle { text-align: center; font-size: 0.92rem; letter-spacing: 0.07em; opacity: 0.62; margin-top: 0.7rem; margin-bottom: 0.25rem; }
.login-hint { text-align: center; font-size: 0.82rem; letter-spacing: 0.05em; opacity: 0.76; margin-bottom: 1.4rem; }
.login-pending-card { padding: 0.4rem 0.25rem 0.25rem 0.25rem; margin-top: 0; margin-bottom: 0; }
.login-pending-label { font-family: 'Source Code Pro', monospace; font-size: 0.92rem; letter-spacing: 0.2em; text-transform: uppercase; opacity: 0.82; margin-bottom: 0.5rem; }
.login-pending-line { font-size: 1.12rem; line-height: 1.5; opacity: 0.98; }
.login-pending-line + .login-pending-line { margin-top: 0.3rem; }
.login-pending-key { font-weight: 700; font-size: 1.12rem; color: __LOGIN_INPUT_COLOR__ !important; }
.login-pending-divider { margin: 0.35rem 0 0.45rem 0; height: 1px; background: linear-gradient(90deg, transparent, color-mix(in srgb, __LOGIN_ACCENT__ 42%, transparent), transparent); }
[data-testid="stVerticalBlock"]:has(.login-session-panel) { max-width: 480px !important; width: 100% !important; margin-left: auto !important; margin-right: auto !important; box-sizing: border-box !important; }
[data-testid="stVerticalBlock"]:has(.login-session-panel) > div { padding-left: 0 !important; padding-right: 0 !important; }
[class*="st-key-login_resume_btn"] button,
[class*="st-key-login_new_btn"] button,
[class*="st-key-login_cancel_btn"] button { min-height: 2.8rem !important; border-radius: 12px !important; font-weight: 800 !important; letter-spacing: 0.02em !important; white-space: nowrap !important; overflow: hidden !important; text-overflow: ellipsis !important; padding-left: 0.7rem !important; padding-right: 0.7rem !important; font-size: 0.84rem !important; line-height: 1 !important; }
[class*="st-key-login_resume_btn"] button { background: linear-gradient(180deg, color-mix(in srgb, __LOGIN_ACCENT_SOFT__ 84%, __LOGIN_ACCENT__ 16%), __LOGIN_ACCENT__) !important; color: __LOGIN_THEME_TEXT__ !important; border: 1px solid color-mix(in srgb, __LOGIN_ACCENT__ 82%, transparent) !important; box-shadow: 0 10px 22px color-mix(in srgb, __LOGIN_ACCENT__ 28%, transparent) !important; }
[class*="st-key-login_resume_btn"] button:hover { background: linear-gradient(180deg, color-mix(in srgb, __LOGIN_ACCENT_SOFT__ 72%, __LOGIN_ACCENT__ 28%), color-mix(in srgb, __LOGIN_ACCENT__ 88%, __LOGIN_ACCENT_SOFT__ 12%)) !important; }
[class*="st-key-login_new_btn"] button,
[class*="st-key-login_cancel_btn"] button { background: color-mix(in srgb, __LOGIN_PANEL__ 88%, __LOGIN_SURFACE__ 12%) !important; color: __LOGIN_INPUT_COLOR__ !important; border: 1px solid color-mix(in srgb, __LOGIN_INPUT_COLOR__ 18%, transparent) !important; opacity: 0.95 !important; }
[class*="st-key-login_new_btn"] button:hover,
[class*="st-key-login_cancel_btn"] button:hover { background: color-mix(in srgb, __LOGIN_PANEL__ 80%, __LOGIN_SURFACE__ 20%) !important; border-color: color-mix(in srgb, __LOGIN_INPUT_COLOR__ 28%, transparent) !important; }
[data-testid="stVerticalBlock"]:has(.login-session-panel) .stButton > button { width: 100% !important; min-width: 0 !important; }
[data-testid="stVerticalBlock"]:has(.login-session-panel) .stButton > button p,
[data-testid="stVerticalBlock"]:has(.login-session-panel) .stButton > button span { white-space: nowrap !important; }
[class*="st-key-login_hidden_submit_btn"] { display: none !important; }
[class*="st-key-login_hidden_submit_btn"] button { display: none !important; }
[data-testid="stTextInput"] label { display: none !important; }
[data-testid="stTextInput"] { margin-bottom: 2rem !important; }
[data-testid="stTextInput"] input { background: transparent !important; border: none !important; box-shadow: none !important; outline: none !important; color: __LOGIN_INPUT_COLOR__ !important; caret-color: __LOGIN_INPUT_COLOR__ !important; text-align: center !important; font-size: 2.05rem !important; font-weight: 500 !important; letter-spacing: 0.08em !important; padding: 0.1rem 0.1rem !important; }
[data-testid="stTextInput"] input::placeholder { color: __LOGIN_PLACEHOLDER_COLOR__ !important; opacity: 1 !important; }
[data-testid="stTextInput"] [data-baseweb="input"] { border: none !important; box-shadow: none !important; background: transparent !important; }
[data-testid="stTextInput"] [data-baseweb="input"] > div { border: none !important; box-shadow: none !important; background: transparent !important; }
[data-testid="InputInstructions"] { display: none !important; }
</style>
"""
    login_css = login_css.replace("__LOGIN_INPUT_COLOR__", login_input_color).replace("__LOGIN_PLACEHOLDER_COLOR__", login_placeholder_color).replace("__LOGIN_ACCENT__", login_accent_color).replace("__LOGIN_PANEL__", login_panel_color).replace("__LOGIN_SURFACE__", login_surface_color).replace("__LOGIN_ACCENT_SOFT__", login_accent_soft_color).replace("__LOGIN_THEME_TEXT__", login_theme_text)
    st.markdown(login_css, unsafe_allow_html=True)
    login_logo_html = _hero_logo_html(st.session_state.mode, theme_name).replace('class="hero-logo"', 'class="hero-logo login-hero-logo"', 1)
    if login_logo_html:
        st.markdown(login_logo_html, unsafe_allow_html=True)
    st.markdown(f'<div class="login-title">{escape(t("login_title"))}</div>', unsafe_allow_html=True)

    pending_norm = normalize_text(st.session_state.get("login_pending_user_norm"))
    pending_name = normalize_text(st.session_state.get("login_pending_user_name"))
    pending_started = normalize_text(st.session_state.get("login_pending_started_at"))

    login_widget_key = normalize_text(st.session_state.get("login_name_widget_key"))
    if not login_widget_key:
        login_widget_key = f"login_name_input_{uuid4().hex[:10]}"
        st.session_state["login_name_widget_key"] = login_widget_key

    c_l, c_mid, c_r = st.columns([1, 1.65, 1], gap="small")
    with c_mid:
        with st.form("login_enter_form", clear_on_submit=False, border=False):
            user_name = st.text_input(t("login_name_label"), value=normalize_text(st.session_state.get("login_name_input", "")), placeholder=t("login_name_placeholder"), key=login_widget_key, label_visibility="collapsed", autocomplete="off")
            if not pending_norm:
                st.markdown(f"<div class='login-subtitle'>{escape(t('login_privacy_note'))}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='login-hint'>{escape(t('login_enter_hint'))}</div>", unsafe_allow_html=True)
            submit_login = st.form_submit_button(t("login_enter"), key="login_hidden_submit_btn", use_container_width=False)
        st.session_state["login_name_input"] = normalize_text(st.session_state.get(login_widget_key, ""))
        if submit_login:
            user_name = normalize_text(user_name)
            user_norm = _normalize_user_name(user_name)
            if not user_norm:
                st.warning(t("login_name_invalid"))
            else:
                latest = _get_latest_session_info(user_norm)
                display_name = normalize_text(user_name) or user_norm
                if latest and normalize_text(latest.get("last_display_name")):
                    display_name = normalize_text(latest.get("last_display_name"))
                if latest and normalize_text(latest.get("session_id")):
                    st.session_state.login_pending_user_name = display_name
                    st.session_state.login_pending_user_norm = user_norm
                    st.session_state.login_pending_started_at = normalize_text(latest.get("started_at"))
                    st.rerun()
                else:
                    current_user_norm, session_id = _start_user_session(display_name)
                    st.session_state.current_user_name = display_name
                    st.session_state.current_user_norm = current_user_norm
                    st.session_state.current_session_id = session_id
                    st.session_state.is_authenticated = True
                    st.session_state.current_view = "app"
                    _append_user_action("login", {"display_name": display_name, "mode": "new"})
                    st.rerun()

    if pending_norm:
        started_txt = pending_started or t("login_unknown_date")
        pending_text = t("login_user_found", user=pending_name, started=started_txt)
        pending_parts = [part.strip() for part in pending_text.split("|") if part.strip()]
        pending_head = pending_parts[0] if pending_parts else pending_text
        pending_detail = pending_parts[1] if len(pending_parts) > 1 else ""
        with st.container():
            pending_detail_html = f"<div class='login-pending-line'>{escape(pending_detail)}</div>" if pending_detail else ""
            st.markdown(
                f"""
<div class="login-session-panel">
  <div class="login-pending-card">
    <div class="login-pending-label">{escape(t("login_session_found_label"))}</div>
    <div class="login-pending-line"><span class="login-pending-key">{escape(pending_head)}</span></div>
    {pending_detail_html}
    <div class="login-pending-divider"></div>
  </div>
</div>
""",
                unsafe_allow_html=True,
            )
            c_resume, c_new, c_cancel = st.columns([1, 1, 1], gap="small")
            with c_resume:
                if st.button(t("login_resume"), width="stretch", key="login_resume_btn"):
                    current_user_norm, session_id = _resume_user_session(pending_norm, pending_name or pending_norm)
                    st.session_state.current_user_name = pending_name or pending_norm
                    st.session_state.current_user_norm = current_user_norm
                    st.session_state.current_session_id = session_id
                    st.session_state.is_authenticated = True
                    st.session_state.current_view = "app"
                    _append_user_action("login", {"display_name": st.session_state.current_user_name, "mode": "resume"})
                    st.session_state.login_pending_user_name = ""
                    st.session_state.login_pending_user_norm = ""
                    st.session_state.login_pending_started_at = ""
                    st.rerun()
            with c_new:
                if st.button(t("login_new"), width="stretch", key="login_new_btn"):
                    current_user_norm, session_id = _start_user_session(pending_name or pending_norm)
                    st.session_state.current_user_name = pending_name or pending_norm
                    st.session_state.current_user_norm = current_user_norm
                    st.session_state.current_session_id = session_id
                    st.session_state.is_authenticated = True
                    st.session_state.current_view = "app"
                    _append_user_action("login", {"display_name": st.session_state.current_user_name, "mode": "new"})
                    st.session_state.login_pending_user_name = ""
                    st.session_state.login_pending_user_norm = ""
                    st.session_state.login_pending_started_at = ""
                    st.rerun()
            with c_cancel:
                if st.button(t("login_change_username"), width="stretch", key="login_cancel_btn"):
                    st.session_state.login_pending_user_name = ""
                    st.session_state.login_pending_user_norm = ""
                    st.session_state.login_pending_started_at = ""
                    st.rerun()


def _is_preload_done() -> bool:
    from session import _is_preload_done as _session_preload_done

    return _session_preload_done()


def _render_boot_page() -> None:
    st.markdown(
        """
<style>
.boot-wrap {
  min-height: 62vh;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  text-align: center;
}
.boot-title {
  font-size: clamp(1.8rem, 3vw, 2.4rem);
  font-weight: 800;
  letter-spacing: 0.08em;
  margin-bottom: 0.5rem;
  opacity: 0.95;
}
.boot-sub {
  font-size: 0.9rem;
  letter-spacing: 0.06em;
  opacity: 0.72;
}
</style>
""",
        unsafe_allow_html=True,
    )
    st.markdown(f"<div class='boot-wrap'><div class='boot-title'>{escape(t('boot_loading_workspace'))}</div></div>", unsafe_allow_html=True)
