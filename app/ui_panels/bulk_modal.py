"""The bulk-download confirmation modal: shown when a builder run would act on more than DEFAULT_BULK_CONFIRM_THRESHOLD images.

See `app.py::ui_main`'s comment on the `bulk_queue_stage` state machine for
why "Continua" and "Annulla"/"x" take different paths: Continua needs the
overlay to visually disappear before the (blocking) download/process call
starts, so it drives a multi-rerun hide_only -> ready_to_run -> run_now
sequence; Cancel doesn't run anything, so it clears `pending_bulk_action`
immediately instead of queuing through that sequence.
"""

from __future__ import annotations

from typing import Any, Callable

import streamlit as st


def render_bulk_confirmation_ui(
    *,
    t: Callable[..., str],
    normalize_text: Callable[[Any], str],
    bulk_overlay_slot: Any,
) -> None:
    """Render the bulk-confirm overlay if there's a pending bulk action to confirm, else clear the slot."""
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
                    # Cancel doesn't run anything, unlike "Continua" -- it must
                    # not wait for the queued_bulk_command/run_now choreography
                    # (app.py only drains that queue once bulk_queue_stage
                    # reaches "run_now", which cancel never sets), or
                    # pending_bulk_action is left set and the modal can pop
                    # back up on the next unrelated rerun.
                    st.session_state.pending_bulk_action = None
                    st.session_state.suppress_bulk_modal_once = True
                    st.session_state.queued_bulk_command = ""
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
                    # See the × handler above: clear pending_bulk_action here
                    # directly rather than queuing "cancel" for the run_now
                    # drain, which cancel never reaches.
                    st.session_state.pending_bulk_action = None
                    st.session_state.suppress_bulk_modal_once = True
                    st.session_state.queued_bulk_command = ""
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
