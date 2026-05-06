from __future__ import annotations

from typing import Any, Callable, Optional

import pandas as pd


class CatalogSelectionService:
    def __init__(
        self,
        *,
        normalize_text: Callable[[Any], str],
        load_json: Callable[..., Any],
        resolve_pds_missing_sols: Callable[[], Any],
    ) -> None:
        self._normalize_text = normalize_text
        self._load_json = load_json
        self._resolve_pds_missing_sols = resolve_pds_missing_sols

    def get_pds_max_sol(self, state: dict[str, Any]) -> Optional[int]:
        cached = state.get("_pds_max_sol_cached")
        try:
            if cached is not None:
                return int(cached)
        except Exception:
            pass

        def _scan(df: Any) -> Optional[int]:
            if not isinstance(df, pd.DataFrame) or len(df) == 0 or "sol" not in df.columns:
                return None
            vals = pd.to_numeric(df["sol"], errors="coerce").dropna()
            if len(vals) == 0:
                return None
            return int(vals.max())

        max_sol: Optional[int] = _scan(state.get("df_pds"))
        if max_sol is None:
            df_all = state.get("df")
            if isinstance(df_all, pd.DataFrame) and len(df_all) > 0 and "source" in df_all.columns:
                src = df_all["source"].astype(str).str.strip().str.lower()
                max_sol = _scan(df_all[src == "pds"])

        if max_sol is not None:
            state["_pds_max_sol_cached"] = int(max_sol)
        return max_sol

    def get_pds_missing_sols(self, state: dict[str, Any]) -> set[int]:
        cached = state.get("_pds_missing_sols_cached")
        if isinstance(cached, set):
            return {int(v) for v in cached}

        missing: set[int] = set()
        cfg = self._load_json(self._resolve_pds_missing_sols())
        if isinstance(cfg, dict):
            explicit = cfg.get("missing_sols")
            if isinstance(explicit, list):
                for item in explicit:
                    try:
                        missing.add(int(item))
                    except Exception:
                        continue

            ranges = cfg.get("missing_sol_ranges")
            if not isinstance(ranges, list):
                ranges = cfg.get("ranges")
            if isinstance(ranges, list):
                for item in ranges:
                    txt = self._normalize_text(item)
                    if not txt:
                        continue
                    if ".." not in txt:
                        try:
                            missing.add(int(txt))
                        except Exception:
                            continue
                        continue
                    a_raw, b_raw = txt.split("..", 1)
                    try:
                        a = int(a_raw.strip())
                        b = int(b_raw.strip())
                    except Exception:
                        continue
                    lo = min(a, b)
                    hi = max(a, b)
                    for val in range(lo, hi + 1):
                        missing.add(val)

        state["_pds_missing_sols_cached"] = set(missing)
        return missing

    def route_selection_by_catalog_boundary(self, state: dict[str, Any], df: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(df, pd.DataFrame) or len(df) == 0:
            return df
        if "source" not in df.columns or "sol" not in df.columns:
            return df

        filters = state.get("filters", {}) or {}
        allow_pds = bool(filters.get("source_pds", True))
        allow_raw = bool(filters.get("source_raw", True))
        src = df["source"].astype(str).str.strip().str.lower()
        if allow_pds and allow_raw:
            return df
        if allow_pds and not allow_raw:
            return df[src.eq("pds")].copy().reset_index(drop=True)
        if allow_raw and not allow_pds:
            return df[src.eq("raw")].copy().reset_index(drop=True)
        return df.iloc[0:0].copy().reset_index(drop=True)

