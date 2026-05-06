from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any, Callable

import streamlit as st


def render_viewport_panel(
    *,
    t: Callable[..., str],
    normalize_text: Callable[[Any], str],
) -> None:
    st.markdown(f'<div class="pane-title">{t("viewport_title")}</div>', unsafe_allow_html=True)
    selected = normalize_text(st.session_state.get("selected_image"))
    selected_image_path = normalize_text(st.session_state.get("selected_image_path"))
    if selected and selected_image_path and Path(selected_image_path).exists():
        st.image(selected_image_path, caption=selected, use_container_width=True)
    else:
        if not selected:
            st.markdown(
                f"""
<div class="viewport-box viewport-empty">
  <div class="viewport-empty-icon">🛰</div>
  <div class="viewport-empty-title">{escape(t("waiting_for_image"))}</div>
  <div class="viewport-empty-sub">{escape(t("saved_files_preview_hint"))}</div>
</div>
""",
                unsafe_allow_html=True,
            )
        else:
            txt = f"{t('preview_image')}: {selected} ({t('saved_files_no_preview')})"
            st.markdown(f"""<div class="viewport-box">{txt}</div>""", unsafe_allow_html=True)

