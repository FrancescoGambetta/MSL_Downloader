from __future__ import annotations

from typing import Any, Callable

import streamlit as st


def render_bulk_confirmation_ui(
    *,
    t: Callable[..., str],
    normalize_text: Callable[[Any], str],
    bulk_overlay_slot: Any,
) -> None:
    queue_stage = normalize_text(st.session_state.get("bulk_queue_stage"))
    if queue_stage in {"hide_only", "ready_to_run", "run_now"}:
        bulk_overlay_slot.empty()
        return
    if bool(st.session_state.get("suppress_bulk_modal_once")):
        st.session_state.suppress_bulk_modal_once = False
        bulk_overlay_slot.empty()
        return
    pending = st.session_state.get("pending_bulk_action")
    if not isinstance(pending, dict):
        bulk_overlay_slot.empty()
        return
    total = int(pending.get("total", 0))
    action_type = normalize_text(pending.get("type"))
    action_label = t("bulk_action_download_process")
    if action_type == "download":
        action_label = t("bulk_action_download")

    with bulk_overlay_slot.container(key="bulk_overlay_panel"):
        with st.container(key="bulk_overlay_card"):
            header_l, header_r = st.columns([0.88, 0.12], gap="small")
            with header_l:
                st.markdown(f"#### {t('bulk_modal_title')}")
            with header_r:
                if st.button("×", key="bulk_overlay_close_btn", help=t("bulk_modal_cancel"), width="stretch"):
                    st.session_state.suppress_bulk_modal_once = True
                    st.session_state.queued_bulk_command = "cancel"
                    st.session_state.bulk_queue_stage = ""
                    st.session_state.operation_live_text = ""
                    bulk_overlay_slot.empty()
                    st.rerun()
            st.write(t("bulk_modal_message", total=total, action=action_label))
            limit = st.number_input(
                t("bulk_modal_limit_label"),
                min_value=0,
                value=0,
                step=1,
                key="bulk_overlay_limit_input",
            )
            c_cancel, c_continue = st.columns(2, gap="small")
            with c_cancel:
                if st.button(t("bulk_modal_cancel"), key="bulk_overlay_cancel_btn", width="stretch"):
                    st.session_state.suppress_bulk_modal_once = True
                    st.session_state.queued_bulk_command = "cancel"
                    st.session_state.bulk_queue_stage = ""
                    st.session_state.operation_live_text = ""
                    bulk_overlay_slot.empty()
                    st.rerun()
            with c_continue:
                if st.button(t("bulk_modal_continue"), key="bulk_overlay_continue_btn", width="stretch"):
                    n = int(limit) if int(limit) > 0 else 0
                    st.session_state.suppress_bulk_modal_once = True
                    st.session_state.queued_bulk_command = str(n) if n > 0 else "proceed"
                    st.session_state.bulk_queue_stage = "hide_only"
                    st.session_state.operation_live_text = t("bulk_starting_live")
                    bulk_overlay_slot.empty()
                    st.rerun()
