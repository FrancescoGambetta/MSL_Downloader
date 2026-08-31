"""Handles replies to the bulk-download confirmation modal -- the only "command" surface left after the chat/parser UI was removed."""

from __future__ import annotations

from typing import Any, Callable, Optional

import pandas as pd

from bulk_reply_parser import (
    _bulk_cancel_words,
    _bulk_cancelled_text,
    _bulk_confirmation_text,
    _bulk_proceed_words,
    _contains_word,
    _no_pending_bulk_text,
    _normalize_command_for_parser,
    _parse_int,
)
from portable_engine_adapter import records_from_dataframe  # type: ignore


class LocalCommandHandlerService:
    """
    Handles locally-resolvable commands.

    Historically this parsed full natural-language chat commands (camera/sol/
    filter extraction, analytics queries, config commands, etc.), but that
    entire chat/parser UI was removed. The only thing still reachable in the
    live app is the bulk-download confirmation reply ("procedi"/"annulla"/a
    number), sent from the bulk-confirmation modal via `submit_command`. This
    class now only handles that -- see `handle_local` below.
    """

    def __init__(
        self,
        *,
        normalize_text: Callable[[Any], str],
        prepare_action_df: Callable[..., pd.DataFrame],
        run_download: Callable[..., str],
        run_download_and_process_interleaved: Callable[..., str],
        organize_photos_simple_layout: Callable[[], tuple[bool, str]],
    ) -> None:
        self._normalize_text = normalize_text
        self._prepare_action_df = prepare_action_df
        self._run_download = run_download
        self._run_download_and_process_interleaved = run_download_and_process_interleaved
        self._organize_photos_simple_layout = organize_photos_simple_layout

    def _count_records_for_action(
        self,
        action_type: str,
        *,
        all_variants: bool,
        max_images: Optional[int] = None,
        random_sample: bool = False,
        per_camera_limits: Optional[dict[str, int]] = None,
        selection_df: Optional[pd.DataFrame] = None,
    ) -> int:
        """Count how many records `prepare_action_df`+`records_from_dataframe` would actually act on, without running the action.

        `action_type` isn't used yet -- the count doesn't currently depend
        on whether the caller means "download" vs "download_process".
        """
        require_lbl = False
        df = self._prepare_action_df(
            all_variants=all_variants,
            max_images=max_images,
            random_sample=random_sample,
            per_camera_limits=per_camera_limits,
            require_lbl=require_lbl,
            selection_df=selection_df,
        )
        return len(records_from_dataframe(df, require_lbl=require_lbl))

    def count_records_for_action(
        self,
        action_type: str,
        *,
        all_variants: bool,
        max_images: Optional[int] = None,
        random_sample: bool = False,
        per_camera_limits: Optional[dict[str, int]] = None,
        selection_df: Optional[pd.DataFrame] = None,
    ) -> int:
        """Public entry point for `_count_records_for_action` (used e.g. by `actions._count_records_for_action` for the bulk-confirm threshold check)."""
        return self._count_records_for_action(
            action_type,
            all_variants=all_variants,
            max_images=max_images,
            random_sample=random_sample,
            per_camera_limits=per_camera_limits,
            selection_df=selection_df,
        )

    def handle_local(
        self,
        state: dict[str, Any],
        command: str,
        *,
        progress_emit: Optional[callable] = None,
    ) -> tuple[bool, str]:
        """
        Handle a reply to the bulk-download confirmation modal ("procedi" /
        "annulla" / a number typed as the per-run limit). Returns (False, "")
        when there is no pending bulk action to reply to -- there is nothing
        else for this to handle anymore.
        """
        normalize_text = self._normalize_text
        pending = state.get("pending_bulk_action")
        if not isinstance(pending, dict):
            return False, ""

        cmd = _normalize_command_for_parser(command)
        action_type = normalize_text(pending.get("type"))
        if _contains_word(cmd, _bulk_cancel_words()):
            state["pending_bulk_action"] = None
            return True, _bulk_cancelled_text()

        limit: Optional[int] = None
        n = _parse_int(cmd, r"\b(\d{1,6})\b")
        if n is not None and n > 0:
            limit = int(n)
        elif _contains_word(cmd, _bulk_proceed_words()):
            limit = None
        else:
            return True, _bulk_confirmation_text(int(pending.get("total", 0)), action_type=action_type or "download_process")

        all_variants = bool(pending.get("all_variants", False))
        per_camera_limits = pending.get("per_camera_limits")
        state["pending_bulk_action"] = None
        if action_type == "download_process":
            action_msg = self._run_download_and_process_interleaved(
                all_variants=all_variants,
                progress_emit=progress_emit,
                max_images=limit,
                random_sample=False,
                per_camera_limits=per_camera_limits,
            )
            _, org_msg = self._organize_photos_simple_layout()
            return True, f"{action_msg}\n\n{org_msg}".strip()
        if action_type == "download":
            action_msg = self._run_download(
                all_variants=all_variants,
                progress_emit=progress_emit,
                max_images=limit,
                random_sample=False,
                per_camera_limits=per_camera_limits,
            )
            _, org_msg = self._organize_photos_simple_layout()
            return True, f"{action_msg}\n\n{org_msg}".strip()
        return True, _no_pending_bulk_text()
