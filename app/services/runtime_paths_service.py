"""Resolves every configurable filesystem path the app uses (catalog files, config, cache) and manages the download path + persisted UI config.

All the `resolve_*` methods follow the same pattern: read a key from
`config/runtime_paths.json` (via the `cfg` dict passed in), falling back to
a sensible relative default if that key is absent, then resolve it to an
absolute path under the project root.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable


class RuntimePathsService:
    """Path resolution + persisted app_ui_config.json read/write, backing `runtime.py`'s module-level functions."""

    def __init__(
        self,
        *,
        project_root: Path,
        normalize_text: Callable[[Any], str],
        load_json: Callable[[Path], dict[str, Any]],
        save_json: Callable[[Path, dict[str, Any]], None],
    ) -> None:
        self._project_root = project_root
        self._normalize_text = normalize_text
        self._load_json = load_json
        self._save_json = save_json

    def runtime_paths_path(self) -> Path:
        return self._project_root / "config" / "runtime_paths.json"

    def load_runtime_paths_uncached(self) -> dict[str, Any]:
        p = self.runtime_paths_path()
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def resolve_path(self, *, cfg: dict[str, Any], key: str, default_rel: str) -> Path:
        rel = self._normalize_text(cfg.get(key)) or default_rel
        return (self._project_root / rel).resolve()

    def resolve_catalog_parquet(self, *, cfg: dict[str, Any]) -> Path:
        return self.resolve_path(cfg=cfg, key="catalog_parquet", default_rel="data/catalog/Catalog_PDS.parquet")

    def resolve_catalog_parquet_raw(self, *, cfg: dict[str, Any]) -> Path:
        return self.resolve_path(cfg=cfg, key="catalog_parquet_raw", default_rel="data/catalog/Catalog_RawArch.parquet")

    def resolve_pds_missing_sols(self, *, cfg: dict[str, Any]) -> Path:
        return self.resolve_path(cfg=cfg, key="pds_missing_sols", default_rel="config/pds_missing_sols.json")

    def resolve_intent_config(self, *, cfg: dict[str, Any]) -> Path:
        return self.resolve_path(cfg=cfg, key="intent_config", default_rel="config/intent_config.json")

    def resolve_msl_config(self, *, cfg: dict[str, Any]) -> Path:
        return self.resolve_path(cfg=cfg, key="msl_catalog_config", default_rel="config/msl_catalog_config.json")

    def resolve_ui_config(self, *, cfg: dict[str, Any]) -> Path:
        return self.resolve_path(cfg=cfg, key="app_ui_config", default_rel="config/app_ui_config.json")

    def resolve_selection_store(self, *, cfg: dict[str, Any]) -> Path:
        return self.resolve_path(cfg=cfg, key="selected_rows_bin", default_rel="cache/selected_rows.bin")

    def sanitize_app_ui_config(self, cfg: dict[str, Any], *, transient_keys: set[str]) -> dict[str, Any]:
        """Drop `transient_keys` (e.g. API tokens) from `cfg` before it's read back or persisted."""
        if not isinstance(cfg, dict):
            return {}
        return {k: v for k, v in cfg.items() if k not in transient_keys}

    def load_app_ui_config(self, *, cfg: dict[str, Any], transient_keys: set[str]) -> dict[str, Any]:
        """Load app_ui_config.json, with `transient_keys` filtered out."""
        p = self.resolve_ui_config(cfg=cfg)
        raw = self._load_json(p)
        return self.sanitize_app_ui_config(raw, transient_keys=transient_keys)

    def save_app_ui_config(self, *, cfg: dict[str, Any], value: dict[str, Any], transient_keys: set[str]) -> None:
        """Persist `value` to app_ui_config.json, with `transient_keys` stripped first."""
        p = self.resolve_ui_config(cfg=cfg)
        self._save_json(p, self.sanitize_app_ui_config(value, transient_keys=transient_keys))

    def clean_download_path_input(self, path: str) -> str:
        """Normalize a raw download-path string to an absolute path (relative paths resolve against the project root), or "" if blank."""
        raw = self._normalize_text(path)
        if not raw:
            return ""
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = (self._project_root / p).resolve()
        return str(p)

    def default_download_path(self, *, cfg: dict[str, Any]) -> str:
        """Return the built-in default download folder (config's `app_download_default`, or `APP/downloads`), as an absolute path."""
        rel = self._normalize_text(cfg.get("app_download_default")) or "APP/downloads"
        p = (self._project_root / rel).resolve()
        return str(p)

    def resolve_download_path(self, *, cfg: dict[str, Any], path: str) -> str:
        """Clean `path` and resolve it to an absolute path, falling back to `default_download_path()` if `path` is blank."""
        cleaned = self.clean_download_path_input(path)
        if not cleaned:
            return self.default_download_path(cfg=cfg)
        p = Path(cleaned).expanduser()
        if not p.is_absolute():
            p = (self._project_root / p).resolve()
        return str(p)

    def ensure_writable_download_path(self, *, cfg: dict[str, Any], path: str) -> tuple[bool, str]:
        """Resolve `path`, create it, and verify it's writable (probe file). Falls back to `default_download_path()` if that fails too."""
        candidate = self.resolve_download_path(cfg=cfg, path=path)
        out = Path(candidate)
        try:
            out.mkdir(parents=True, exist_ok=True)
            probe = out / ".dwnapp_write_probe.tmp"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return True, str(out)
        except Exception:
            fallback = Path(self.default_download_path(cfg=cfg))
            try:
                fallback.mkdir(parents=True, exist_ok=True)
                return True, str(fallback)
            except Exception:
                return False, str(out)
