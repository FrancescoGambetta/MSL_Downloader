from __future__ import annotations

from html import escape
from typing import Any, Callable


class CommandSubmissionService:
    def __init__(
        self,
        *,
        translator: Callable[..., str],
        normalize_text: Callable[[Any], str],
        append_user_action: Callable[..., Any],
        handle_local: Callable[..., tuple[bool, str]],
        parser_validation_note: Callable[[str, str], str],
        humanize_parser_response: Callable[[str, str], str],
        norm_ascii: Callable[[str], str],
        show_combined_config_text: Callable[[], str],
        geo_status_text: Callable[[], str],
        show_download_path_text: Callable[[], str],
    ) -> None:
        self._t = translator
        self._normalize_text = normalize_text
        self._append_user_action = append_user_action
        self._handle_local = handle_local
        self._parser_validation_note = parser_validation_note
        self._humanize_parser_response = humanize_parser_response
        self._norm_ascii = norm_ascii
        self._show_combined_config_text = show_combined_config_text
        self._geo_status_text = geo_status_text
        self._show_download_path_text = show_download_path_text

    def submit_command(self, state: dict[str, Any], command: str, *, progress_slot: Any = None, progress_bar: Any = None) -> None:
        text = self._normalize_text(command)
        if not text:
            return
        self._append_user_action("command_submitted", {"text": text})
        state["chat_history"] = [{"role": "user", "text": text}]
        state["operation_live_text"] = ""
        state["is_processing"] = True
        state["stop_requested"] = False
        progress_lines: list[str] = []

        def maybe_update_progress_from_line(line: str) -> None:
            if progress_bar is None:
                return
            try:
                import re

                m = re.search(r"\b(\d+)\s+of\s+(\d+)\s+images\b", line, flags=re.IGNORECASE)
                if not m:
                    return
                cur = int(m.group(1))
                total = int(m.group(2))
                if total <= 0:
                    return
                p = float(max(0, min(cur, total))) / float(total)
                progress_bar.progress(max(0.0, min(1.0, p)))
            except Exception:
                return

        def progress_emit(msg: str) -> None:
            line = self._normalize_text(msg)
            if not line:
                return
            progress_lines.append(line)
            state["operation_live_text"] = "\n".join(progress_lines[-14:])
            maybe_update_progress_from_line(line)
            if progress_slot is not None:
                progress_slot.markdown(
                    f"<div class='live-log'><div class='live-tag'>⟳ {escape(self._t('live_badge_label'))}</div><div class='msg-text'>{escape(self._normalize_text(state.get('operation_live_text')))}</div></div>",
                    unsafe_allow_html=True,
                )

        try:
            if progress_bar is not None:
                try:
                    progress_bar.progress(0.0)
                except Exception:
                    pass

            ok, local_answer = self._handle_local(text, progress_emit=progress_emit)
            if ok:
                src = "parser"
                raw_local = self._normalize_text(local_answer)
                note = self._parser_validation_note(text, raw_local)
                ans = self._humanize_parser_response(text, raw_local)
                if note:
                    ans = f"[check] {note}\n\n{ans}"
                if ans != self._normalize_text(local_answer):
                    src = "parser_humanized"
            else:
                src = "parser_fallback_local"
                ascii_text = self._norm_ascii(text)
                if "config" in ascii_text:
                    ans = self._show_combined_config_text()
                elif "geo" in ascii_text or "coord" in ascii_text:
                    ans = self._geo_status_text()
                elif "download path" in ascii_text or "cartella download" in ascii_text:
                    ans = self._show_download_path_text()
                else:
                    ans = self._t("parser_only_mode")

            state["response_source"] = src
            state.setdefault("chat_history", []).append({"role": "ai", "text": ans, "source": src})
            self._append_user_action("command_result", {"source": src, "response_preview": self._normalize_text(ans)[:600]})
        finally:
            state["is_processing"] = False
            if progress_bar is not None:
                try:
                    progress_bar.progress(1.0)
                except Exception:
                    pass
