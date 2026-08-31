"""Persisted download-path management (the only surviving responsibility of this service after the chat-era config/geo commands were removed as dead code)."""

from __future__ import annotations

from typing import Any, Callable


class AppConfigService:
    """Resolves and persists the download path, both in the current session and in app_ui_config.json."""

    def __init__(
        self,
        *,
        resolve_download_path: Callable[[str], str],
        refresh_saved_output_files: Callable[[], None],
        load_app_ui_config: Callable[[], dict[str, Any]],
        save_app_ui_config: Callable[[dict[str, Any]], None],
    ) -> None:
        self._resolve_download_path = resolve_download_path
        self._refresh_saved_output_files = refresh_saved_output_files
        self._load_app_ui_config = load_app_ui_config
        self._save_app_ui_config = save_app_ui_config

    def set_download_path(self, state: dict[str, Any], path: str, persist: bool = True) -> str:
        """Resolve `path`, store it in session_state, refresh the saved-output-files index, and (if `persist`) save it to app_ui_config.json."""
        normalized = self._resolve_download_path(path)
        state["download_path"] = normalized
        self._refresh_saved_output_files()
        if persist:
            cfg = self._load_app_ui_config()
            cfg["download_path"] = normalized
            self._save_app_ui_config(cfg)
        return normalized

    # Folder chooser is implemented in UI layer (see `app/utils/folder_dialog.py`).
