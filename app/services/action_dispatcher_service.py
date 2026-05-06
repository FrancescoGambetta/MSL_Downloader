from __future__ import annotations

from typing import Any, Callable


class ActionDispatcherService:
    def __init__(
        self,
        *,
        translator: Callable[..., str],
        normalize_text: Callable[[Any], str],
        run_sql_query: Callable[..., tuple[bool, str, Any]],
        run_download: Callable[..., str],
        run_download_and_process_interleaved: Callable[..., str],
    ) -> None:
        self._t = translator
        self._normalize_text = normalize_text
        self._run_sql_query = run_sql_query
        self._run_download = run_download
        self._run_download_and_process_interleaved = run_download_and_process_interleaved

    def execute_action(self, state: dict[str, Any], payload: dict[str, Any]) -> str:
        action = self._normalize_text(payload.get("action"))
        params = payload.get("params", {}) or {}
        df = state["df_filtered"]
        if action == "count_rows":
            return self._t("report_rows", rows=len(df))
        if action == "show_schema":
            return "\n".join(f"- {c}: {df[c].dtype}" for c in df.columns)
        if action == "run_query":
            ok, msg, out = self._run_sql_query(df, self._normalize_text(params.get("sql")))
            if ok:
                try:
                    state["last_query_preview"] = out.head(20).to_string(index=False) if len(out) else self._t("empty_label")
                except Exception:
                    state["last_query_preview"] = self._t("empty_label")
                return msg
            return msg
        if action == "download":
            return self._run_download(
                all_variants=bool(params.get("all_variants", False)),
                max_images=params.get("max_images"),
                random_sample=bool(params.get("random_sample", False)),
                per_camera_limits=params.get("per_camera_limits"),
            )
        if action == "process":
            return self._run_download_and_process_interleaved(
                all_variants=bool(params.get("all_variants", False)),
                max_images=params.get("max_images"),
                random_sample=bool(params.get("random_sample", False)),
                per_camera_limits=params.get("per_camera_limits"),
            )
        if action == "respond":
            return (
                self._normalize_text(params.get("text"))
                or self._normalize_text(payload.get("text"))
                or self._normalize_text(payload.get("message"))
                or self._t("ok_label")
            )
        return self._normalize_text(payload.get("message")) or self._t("unsupported_action", action=action)
