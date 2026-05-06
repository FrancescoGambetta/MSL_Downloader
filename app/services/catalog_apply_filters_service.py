from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

import pandas as pd


class CatalogApplyFiltersService:
    def __init__(
        self,
        *,
        normalize_text: Callable[[Any], str],
        filter_dataframe: Callable[[pd.DataFrame, dict[str, Any], Optional[Callable[[float, str], None]]], pd.DataFrame],
        deduplicate_with_source_priority: Callable[[pd.DataFrame], pd.DataFrame],
        persist_selection_from_filtered: Callable[[], None],
    ) -> None:
        self._normalize_text = normalize_text
        self._filter_dataframe = filter_dataframe
        self._deduplicate_with_source_priority = deduplicate_with_source_priority
        self._persist_selection_from_filtered = persist_selection_from_filtered

    def filters_cache_key(self, filters: dict[str, Any], token: str) -> str:
        try:
            payload = json.dumps(filters or {}, sort_keys=True, ensure_ascii=False, default=str)
        except Exception:
            payload = str(filters or {})
        raw = (self._normalize_text(token) + "|" + payload).encode("utf-8", errors="ignore")
        return hashlib.sha1(raw).hexdigest()

    def apply_filters(
        self,
        state: dict[str, Any],
        *,
        progress: Optional[Callable[[float, str], None]] = None,
    ) -> int:
        df, filters, df_pds, df_raw = self._read_state(state)
        cache_key = self._filters_cache_key_for_state(state, filters)

        if self._apply_cached_result_if_available(state, cache_key, progress=progress):
            out_df = state.get("df_filtered")
            return len(out_df) if isinstance(out_df, pd.DataFrame) else 0

        out = self._filter_sources(
            df=df,
            filters=filters,
            df_pds=df_pds,
            df_raw=df_raw,
            state=state,
            progress=progress,
        )
        out = self._finalize_filtered_df(out, state=state, progress=progress)
        self._store_filters_cache(state, cache_key)
        return len(out)

    def _read_state(
        self,
        state: dict[str, Any],
    ) -> tuple[pd.DataFrame, dict[str, Any], Any, Any]:
        df = state["df"]
        filters = state["filters"]
        return df, filters, state.get("df_pds"), state.get("df_raw")

    def _filters_cache_key_for_state(self, state: dict[str, Any], filters: dict[str, Any]) -> str:
        cache_token = self._normalize_text(state.get("_catalog_token")) or self._normalize_text(state.get("data_source"))
        return self.filters_cache_key(filters, cache_token)

    def _safe_progress(self, progress: Optional[Callable[[float, str], None]], p: float, msg: str) -> None:
        if progress is None:
            return
        try:
            progress(p, msg)
        except Exception:
            pass

    def _apply_cached_result_if_available(
        self,
        state: dict[str, Any],
        cache_key: str,
        *,
        progress: Optional[Callable[[float, str], None]] = None,
    ) -> bool:
        cached = state.get("_filters_cache")
        if not (isinstance(cached, dict) and cached.get("key") == cache_key):
            return False
        state["df_filtered"] = cached.get("df_filtered", pd.DataFrame())
        state["df_filtered_pds"] = cached.get("df_filtered_pds", pd.DataFrame())
        state["df_filtered_raw"] = cached.get("df_filtered_raw", pd.DataFrame())
        self._persist_selection_from_filtered()
        self._safe_progress(progress, 1.0, "Fatto (cache)")
        return True

    def _filter_sources(
        self,
        *,
        df: pd.DataFrame,
        filters: dict[str, Any],
        df_pds: Any,
        df_raw: Any,
        state: dict[str, Any],
        progress: Optional[Callable[[float, str], None]] = None,
    ) -> pd.DataFrame:
        if isinstance(df_pds, pd.DataFrame) or isinstance(df_raw, pd.DataFrame):
            src_pds = df_pds if isinstance(df_pds, pd.DataFrame) else pd.DataFrame()
            src_raw = df_raw if isinstance(df_raw, pd.DataFrame) else pd.DataFrame()

            # If progress updates are requested, run sequentially. Streamlit UI updates are
            # not thread-safe from background threads.
            if progress is None:
                with ThreadPoolExecutor(max_workers=2) as ex:
                    fut_pds = ex.submit(self._filter_dataframe, src_pds, filters, None)
                    fut_raw = ex.submit(self._filter_dataframe, src_raw, filters, None)
                    out_pds = fut_pds.result()
                    out_raw = fut_raw.result()
            else:
                self._safe_progress(progress, 0.02, "Filtro: PDS")
                out_pds = self._filter_dataframe(
                    src_pds,
                    filters,
                    lambda p, m: progress(0.02 + (p * 0.48), m),
                )
                self._safe_progress(progress, 0.52, "Filtro: RAW archive")
                out_raw = self._filter_dataframe(
                    src_raw,
                    filters,
                    lambda p, m: progress(0.52 + (p * 0.40), m),
                )

            # filter_dataframe already resets index.
            state["df_filtered_pds"] = out_pds
            state["df_filtered_raw"] = out_raw
            if len(out_pds) == 0 and len(out_raw) == 0:
                return pd.DataFrame(columns=df.columns.tolist())
            if len(out_pds) == 0:
                return out_raw.copy()
            if len(out_raw) == 0:
                return out_pds.copy()
            return pd.concat([out_pds, out_raw], axis=0, ignore_index=True)

        return self._filter_dataframe(df, filters, progress)

    def _finalize_filtered_df(
        self,
        out: pd.DataFrame,
        *,
        state: dict[str, Any],
        progress: Optional[Callable[[float, str], None]] = None,
    ) -> pd.DataFrame:
        self._safe_progress(progress, 0.93, "Deduplicazione")
        out = self._deduplicate_with_source_priority(out)
        # deduplicate_with_source_priority already resets index.
        state["df_filtered"] = out
        self._persist_selection_from_filtered()
        self._safe_progress(progress, 1.0, "Fatto")
        return out

    def _store_filters_cache(self, state: dict[str, Any], cache_key: str) -> None:
        state["_filters_cache"] = {
            "key": cache_key,
            "df_filtered": state.get("df_filtered"),
            "df_filtered_pds": state.get("df_filtered_pds"),
            "df_filtered_raw": state.get("df_filtered_raw"),
        }
