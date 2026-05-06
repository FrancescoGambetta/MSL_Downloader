from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pandas as pd


class CatalogUpdateService:
    def __init__(
        self,
        *,
        project_root: Path,
        translator: Callable[..., str],
        normalize_text: Callable[[str], str],
        normalize_command_for_parser: Callable[[str], str],
        parse_sol_range: Callable[[str], tuple[int | None, int | None]],
        parse_int: Callable[..., int | None],
        parse_cameras: Callable[[str, list[str]], list[str]],
        resolve_msl_config: Callable[[], Path],
        catalog_update_options_cls: type,
        run_catalog_update: Callable[..., dict[str, Any]],
    ) -> None:
        self._project_root = project_root
        self._t = translator
        self._normalize_text = normalize_text
        self._normalize_command_for_parser = normalize_command_for_parser
        self._parse_sol_range = parse_sol_range
        self._parse_int = parse_int
        self._parse_cameras = parse_cameras
        self._resolve_msl_config = resolve_msl_config
        self._catalog_update_options_cls = catalog_update_options_cls
        self._run_catalog_update = run_catalog_update

    def run_catalog_update_from_text(self, state: dict[str, Any], command: str) -> str:
        cmd = self._normalize_command_for_parser(command)
        sol_start, sol_end = self._parse_sol_range(cmd)
        workers = self._parse_int(cmd, r"\bworkers?\s+(\d{1,3})\b")
        cameras = None
        df = state.get("df")
        if isinstance(df, pd.DataFrame) and "camera" in df.columns:
            cams = self._parse_cameras(cmd, sorted(set(df["camera"].dropna().astype(str))))
            cameras = cams or None
        logs: list[str] = []

        def on_event(ev: dict[str, Any]) -> None:
            msg = self._normalize_text(ev.get("message"))
            if msg:
                logs.append(msg)

        res = self._run_catalog_update(
            project_root=self._project_root,
            options=self._catalog_update_options_cls(
                config_path=self._resolve_msl_config(),
                cameras=cameras,
                sol_start=sol_start,
                sol_end=sol_end,
                workers=workers,
                refresh_sol_index=("refresh" in cmd and "sol" in cmd),
                checkpoint_write_parquet=("checkpoint" in cmd and "parquet" in cmd),
            ),
            event_callback=on_event,
        )
        return self._t("catalog_update_exit", code=res["return_code"]) + "\n" + "\n".join(logs[-10:])
