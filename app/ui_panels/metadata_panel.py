from __future__ import annotations

from typing import Any, Callable

import streamlit as st


def render_metadata_panel(
    *,
    t: Callable[..., str],
    meta_line_html: Callable[..., str],
) -> None:
    st.markdown(f'<div class="pane-title">{t("metadata_title")}</div>', unsafe_allow_html=True)
    selected_meta = st.session_state.get("selected_meta_obj", {}) or {}
    if selected_meta:
        product = selected_meta.get("product", {}) if isinstance(selected_meta, dict) else {}
        sources = selected_meta.get("sources", {}) if isinstance(selected_meta, dict) else {}
        outputs = selected_meta.get("outputs", {}) if isinstance(selected_meta, dict) else {}
        quick = {
            "product_id": product.get("product_id"),
            "instrument_id": product.get("instrument_id"),
            "instrument_name": product.get("instrument_name"),
            "sol": product.get("sol"),
            "site": product.get("site"),
            "drive": product.get("drive"),
            "pose": product.get("pose"),
            "img_url": sources.get("img_url"),
            "jpg_path": outputs.get("jpg_path"),
            "meta_json_path": outputs.get("meta_json_path"),
            "warnings": selected_meta.get("warnings", []),
            "errors": selected_meta.get("errors", []),
        }
        lines = [
            meta_line_html("product_id", quick.get("product_id")),
            meta_line_html("instrument_id", quick.get("instrument_id")),
            meta_line_html("instrument_name", quick.get("instrument_name")),
            meta_line_html("sol", quick.get("sol")),
            meta_line_html("site", quick.get("site")),
            meta_line_html("drive", quick.get("drive")),
            meta_line_html("pose", quick.get("pose")),
            meta_line_html("img_url", quick.get("img_url"), path_like=True),
            meta_line_html("jpg_path", quick.get("jpg_path"), path_like=True),
            meta_line_html("meta_json_path", quick.get("meta_json_path"), path_like=True),
            meta_line_html("warnings", quick.get("warnings")),
            meta_line_html("errors", quick.get("errors")),
        ]
        st.markdown(f"<div class='meta-json-light'>{''.join(lines)}</div>", unsafe_allow_html=True)
    else:
        st.markdown(
            f"""
<div class="meta-box">
{t("mission_label")}: MSL Curiosity<br>
{t("rows_filtered_label")}: {len(st.session_state.df_filtered)}<br>
{t("source_label")}: {st.session_state.get('data_source','')}<br>
{t("response_source_label")}: {st.session_state.get('response_source','n/a')}<br>
</div>
""",
            unsafe_allow_html=True,
        )

