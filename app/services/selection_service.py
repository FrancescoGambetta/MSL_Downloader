from __future__ import annotations

import hashlib
from typing import Any, Callable

import pandas as pd


class SelectionService:
    def default_filters_state(self) -> dict[str, Any]:
        return {
            "sol_start": None,
            "sol_end": None,
            "cameras": [],
            "source_pds": True,
            "source_raw": True,
            "min_img_size": None,
            "only_with_lbl": False,
            "dr_variants": [],
            "name_tokens": [],
            "file_prefixes": [],
            "file_name_contains": [],
            "mastcam_only_drcl": False,
            "mastcam_raw_include_c00": True,
            "mahli_only_drcl": False,
            "mardi_only_e01_drcx": False,
            "navcam_only_iltlf": False,
            "hazcam_only_lb_edr": False,
        }

    def filters_are_default(self, state: dict[str, Any]) -> bool:
        cur = state.get("filters", {})
        try:
            return dict(cur) == self.default_filters_state()
        except Exception:
            return False

    def reset_filters_state(
        self,
        state: dict[str, Any],
        *,
        apply_filters: Callable[[], int],
        preserve_selection: bool = False,
    ) -> int:
        state["filters"] = self.default_filters_state()
        if preserve_selection:
            if isinstance(state.get("df_pds"), pd.DataFrame):
                state["df_filtered_pds"] = state["df_pds"].copy().reset_index(drop=True)
            if isinstance(state.get("df_raw"), pd.DataFrame):
                state["df_filtered_raw"] = state["df_raw"].copy().reset_index(drop=True)
            if isinstance(state.get("df"), pd.DataFrame):
                state["df_filtered"] = state["df"].copy().reset_index(drop=True)
                return len(state["df_filtered"])
            return 0
        return apply_filters()

    def get_selection_df(self, state: dict[str, Any], *, all_variants: bool = False) -> pd.DataFrame:
        if not self.filters_are_default(state):
            sel = state["df_filtered"].copy()
        else:
            sel = state["selected_df"].copy() if "selected_df" in state else state["df_filtered"].copy()
            if len(sel) == 0:
                sel = state["df_filtered"].copy()
        if not all_variants or len(sel) == 0:
            return sel
        if "_family_key" not in sel.columns or "_family_key" not in state["df"].columns:
            return sel

        keys = [k for k in sel["_family_key"].fillna("").astype(str).unique().tolist() if k]
        if not keys:
            return sel

        digest = ""
        keys_sorted: list[str] = []
        try:
            keys_sorted = sorted(set(keys))
            digest = hashlib.sha1("\n".join(keys_sorted).encode("utf-8")).hexdigest()
            cache = state.get("_all_variants_cache")
            if isinstance(cache, dict) and cache.get("df_id") == id(state["df"]) and cache.get("digest") == digest:
                cached_df = cache.get("df")
                if isinstance(cached_df, pd.DataFrame):
                    return cached_df
        except Exception:
            digest = ""
            keys_sorted = []

        fam = state["df"]["_family_key"]
        try:
            mask = fam.isin(keys_sorted)
        except Exception:
            mask = fam.astype(str).isin(keys_sorted)
        out = state["df"][mask].copy()
        if "img_url" in out.columns:
            out = out.drop_duplicates(subset=["img_url"], keep="first")
        out = out.reset_index(drop=True)
        try:
            if digest:
                state["_all_variants_cache"] = {"df_id": id(state["df"]), "digest": digest, "df": out}
        except Exception:
            pass
        return out

