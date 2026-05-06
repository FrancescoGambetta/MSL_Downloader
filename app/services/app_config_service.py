from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import requests


class AppConfigService:
    def __init__(
        self,
        *,
        project_root: Path,
        translator: Callable[..., str],
        normalize_text: Callable[[str], str],
        resolve_download_path: Callable[[str], str],
        refresh_saved_output_files: Callable[[], None],
        load_app_ui_config: Callable[[], dict[str, Any]],
        save_app_ui_config: Callable[[dict[str, Any]], None],
        load_json: Callable[[Path], dict[str, Any]],
        resolve_msl_config: Callable[[], Path],
        ensure_writable_download_path: Callable[[str], tuple[bool, str]],
        default_download_path: Callable[[], str],
    ) -> None:
        self._project_root = project_root
        self._t = translator
        self._normalize_text = normalize_text
        self._resolve_download_path = resolve_download_path
        self._refresh_saved_output_files = refresh_saved_output_files
        self._load_app_ui_config = load_app_ui_config
        self._save_app_ui_config = save_app_ui_config
        self._load_json = load_json
        self._resolve_msl_config = resolve_msl_config
        self._ensure_writable_download_path = ensure_writable_download_path
        self._default_download_path = default_download_path

    def set_download_path(self, state: dict[str, Any], path: str, persist: bool = True) -> str:
        normalized = self._resolve_download_path(path)
        state["download_path"] = normalized
        self._refresh_saved_output_files()
        if persist:
            cfg = self._load_app_ui_config()
            cfg["download_path"] = normalized
            self._save_app_ui_config(cfg)
        return normalized

    def show_download_path_text(self, state: dict[str, Any]) -> str:
        session_path = self._resolve_download_path(self._normalize_text(state.get("download_path")))
        cfg = self._load_app_ui_config()
        cfg_path = self._resolve_download_path(self._normalize_text(cfg.get("download_path")))
        ok, effective = self._ensure_writable_download_path(session_path or cfg_path or self._default_download_path())
        exists = Path(effective).expanduser().exists() if effective else False
        return "\n".join(
            [
                self._t("show_download_path_session", value=session_path or self._t("not_set_label")),
                self._t("show_download_path_config", value=cfg_path or self._t("not_set_label")),
                self._t("show_download_path_effective", value=effective or self._t("not_set_label")),
                self._t("show_download_path_exists", value=exists),
                f"writable={ok}",
            ]
        )

    def show_combined_config_text(self) -> str:
        app_cfg = self._load_app_ui_config()
        msl_cfg = self._load_json(self._resolve_msl_config())
        return "\n".join(
            [
                self._t("config_section_app"),
                json.dumps(app_cfg, ensure_ascii=False, indent=2),
                "",
                self._t("config_section_msl"),
                json.dumps(msl_cfg, ensure_ascii=False, indent=2),
            ]
        )

    def geo_status_text(self) -> str:
        cfg = self._load_json(self._resolve_msl_config())
        c_url = self._normalize_text(cfg.get("coord_url"))
        rel = self._normalize_text(cfg.get("coord_local_path", "data/reference/geo/localized_interp_demv2.csv"))
        path = (self._project_root / rel).resolve()
        exists = path.exists()
        size = path.stat().st_size if exists else 0
        mtime = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds") if exists else "n/a"
        return self._t("geo_status_text", coord_url=c_url, local=path, exists=exists, size=size, mtime=mtime)

    def download_geo_csv(self) -> str:
        cfg = self._load_json(self._resolve_msl_config())
        c_url = self._normalize_text(cfg.get("coord_url"))
        rel = self._normalize_text(cfg.get("coord_local_path", "data/reference/geo/localized_interp_demv2.csv"))
        path = (self._project_root / rel).resolve()
        if not c_url:
            return self._t("coord_url_missing")
        path.parent.mkdir(parents=True, exist_ok=True)
        resp = requests.get(c_url, timeout=120)
        resp.raise_for_status()
        path.write_bytes(resp.content)
        return self._t("geo_csv_downloaded", path=path, bytes=len(resp.content))

    def parse_set_config(self, text: str) -> tuple[Optional[str], Optional[str]]:
        match = re.search(r"(?:set config|imposta config|config set)\s+([a-zA-Z0-9_\.]+)\s*=\s*(.+)$", text, re.IGNORECASE)
        if not match:
            return None, None
        return self._normalize_text(match.group(1)), self._normalize_text(match.group(2))

    def parse_cfg_value(self, raw: str) -> Any:
        value = self._normalize_text(raw)
        low = value.lower()
        if low in {"true", "false"}:
            return low == "true"
        if low in {"null", "none"}:
            return None
        if re.fullmatch(r"-?\d+", value):
            return int(value)
        if re.fullmatch(r"-?\d+\.\d+", value):
            return float(value)
        if value.startswith("[") or value.startswith("{"):
            try:
                return json.loads(value)
            except Exception:
                return value
        return value

    def set_nested(self, cfg: dict[str, Any], dotted_key: str, value: Any) -> None:
        parts = [part for part in dotted_key.split(".") if part]
        node = cfg
        for part in parts[:-1]:
            cur = node.get(part)
            if cur is None:
                node[part] = {}
                cur = node[part]
            if not isinstance(cur, dict):
                raise ValueError(f"Cannot set nested key under non-object: {part}")
            node = cur
        node[parts[-1]] = value

    # Folder chooser is implemented in UI layer (see `app/utils/folder_dialog.py`).
