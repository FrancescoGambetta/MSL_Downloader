from __future__ import annotations

from html import escape
from typing import Any, Callable

import streamlit as st


def render_live_log(
    *,
    t: Callable[..., str],
    normalize_text: Callable[[Any], str],
    progress_slot: Any,
) -> None:
    # If a command just ran, the progress UI was rendered inside `submit_command`.
    # Clear the placeholder here to avoid stacking multiple live containers.
    progress_slot.empty()
    live_txt = normalize_text(st.session_state.get("operation_live_text"))
    live_body = live_txt if live_txt else t("live_idle_text")
    progress_slot.markdown(
        f"<div class='live-log'><div class='live-tag'>⟳ {escape(t('live_badge_label'))}</div><div class='msg-text'>{escape(live_body)}</div></div>",
        unsafe_allow_html=True,
    )

