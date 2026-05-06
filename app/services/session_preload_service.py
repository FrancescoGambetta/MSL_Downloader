from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd


class SessionPreloadService:
    def __init__(
        self,
        *,
        preload_lock: threading.Lock,
        preload_state: dict[str, Any],
        normalize_text: Callable[[Any], str],
        prepare_catalog_index: Callable[[pd.DataFrame], pd.DataFrame],
        load_catalog: Callable[[str, Optional[list[str]]], pd.DataFrame],
        resolve_catalog_parquet: Callable[[], Path],
        resolve_catalog_parquet_raw: Callable[[], Path],
        resolve_intent_config: Callable[[], Path],
        load_json: Callable[[Path], dict[str, Any]],
        get_selected_images_df: Callable[[dict[str, Any]], pd.DataFrame] | Callable[[], pd.DataFrame],
        refresh_saved_output_files: Callable[[], None],
    ) -> None:
        self._preload_lock = preload_lock
        self._preload_state = preload_state
        self._normalize_text = normalize_text
        self._prepare_catalog_index = prepare_catalog_index
        self._load_catalog = load_catalog
        self._resolve_catalog_parquet = resolve_catalog_parquet
        self._resolve_catalog_parquet_raw = resolve_catalog_parquet_raw
        self._resolve_intent_config = resolve_intent_config
        self._load_json = load_json
        self._get_selected_images_df = get_selected_images_df
        self._refresh_saved_output_files = refresh_saved_output_files

    def with_source(self, df: pd.DataFrame, source: str) -> pd.DataFrame:
        if len(df) == 0:
            return df.copy()
        out = df.copy()
        if "source" not in out.columns:
            out["source"] = source
        return out

    def combine_catalogs(self, df_pds: pd.DataFrame, df_raw: pd.DataFrame) -> pd.DataFrame:
        left = self.with_source(df_pds, "pds")
        right = self.with_source(df_raw, "raw")
        if len(left) == 0 and len(right) == 0:
            return pd.DataFrame()
        if len(left) == 0:
            return right.reset_index(drop=True)
        if len(right) == 0:
            return left.reset_index(drop=True)
        return pd.concat([left, right], axis=0, ignore_index=True)

    def catalog_min_columns(self, source: str) -> list[str]:
        """
        Minimal set of columns required for the app's filters/actions.
        Keeping this small speeds up initial parquet load without changing behavior.
        """
        src = self._normalize_text(source).lower()
        base = [
            "product_id",
            "camera",
            "sol",
            "sol_url",
            "img_url",
            "lbl_url",
            "img_size_bytes",
            "image_id",
            "instrument_id",
            "instrument_name",
            "start_time",
            "image_time",
            "collection",
            "data_root",
            "record_complete",
        ]
        if src == "raw":
            # RAW uses thumbnail flag in some UX/reporting.
            base.append("is_thumbnail")
            base.append("sample_type")
        return base

    def load_catalog_source(self, path: Path, source: str) -> pd.DataFrame:
        if not path.exists():
            return pd.DataFrame()
        df = self._prepare_catalog_index(self._load_catalog(str(path), columns=self.catalog_min_columns(source)))
        return self.with_source(df, source)

    def preload_heavy_state_worker(self) -> None:
        catalog_df: pd.DataFrame
        catalog_df_pds: pd.DataFrame
        catalog_df_raw: pd.DataFrame
        data_source = ""
        intent_cfg: dict[str, Any] = {}
        intent_cfg_mtime = 0.0
        err = ""
        try:
            p_pds = self._resolve_catalog_parquet()
            p_raw = self._resolve_catalog_parquet_raw()
            data_source = f"pds={p_pds} | raw={p_raw}"
            with ThreadPoolExecutor(max_workers=2) as ex:
                fut_pds = ex.submit(self.load_catalog_source, p_pds, "pds")
                fut_raw = ex.submit(self.load_catalog_source, p_raw, "raw")
                catalog_df_pds = fut_pds.result()
                catalog_df_raw = fut_raw.result()
            catalog_df = self.combine_catalogs(catalog_df_pds, catalog_df_raw)

            intent_p = self._resolve_intent_config()
            intent_cfg_mtime = intent_p.stat().st_mtime if intent_p.exists() else 0.0
            intent_cfg = self._load_json(intent_p)
        except Exception as exc:
            catalog_df = pd.DataFrame()
            catalog_df_pds = pd.DataFrame()
            catalog_df_raw = pd.DataFrame()
            err = self._normalize_text(exc)

        with self._preload_lock:
            self._preload_state["catalog_df"] = catalog_df
            self._preload_state["catalog_df_pds"] = catalog_df_pds
            self._preload_state["catalog_df_raw"] = catalog_df_raw
            self._preload_state["data_source"] = data_source
            self._preload_state["intent_cfg"] = intent_cfg
            self._preload_state["intent_cfg_mtime"] = intent_cfg_mtime
            self._preload_state["error"] = err
            self._preload_state["done"] = True

    def kickoff_login_preload(self) -> None:
        with self._preload_lock:
            if self._preload_state.get("started"):
                return
            self._preload_state["started"] = True
        t = threading.Thread(target=self.preload_heavy_state_worker, name="dwnapp-preload", daemon=True)
        t.start()

    def ensure_heavy_state(self, state: dict[str, Any]) -> None:
        used_preload = False
        with self._preload_lock:
            preload_done = bool(self._preload_state.get("done"))
            preload_df = self._preload_state.get("catalog_df")
            preload_df_pds = self._preload_state.get("catalog_df_pds")
            preload_df_raw = self._preload_state.get("catalog_df_raw")
            preload_source = self._normalize_text(self._preload_state.get("data_source"))
            preload_intent = self._preload_state.get("intent_cfg")
            preload_intent_mtime = float(self._preload_state.get("intent_cfg_mtime") or 0.0)

        if ("df" not in state) or ("df_pds" not in state) or ("df_raw" not in state):
            if (
                preload_done
                and isinstance(preload_df, pd.DataFrame)
                and isinstance(preload_df_pds, pd.DataFrame)
                and isinstance(preload_df_raw, pd.DataFrame)
            ):
                state["df"] = preload_df.copy()
                state["df_pds"] = preload_df_pds.copy()
                state["df_raw"] = preload_df_raw.copy()
                state["data_source"] = preload_source
                used_preload = True
            else:
                p_pds = self._resolve_catalog_parquet()
                p_raw = self._resolve_catalog_parquet_raw()
                with ThreadPoolExecutor(max_workers=2) as ex:
                    fut_pds = ex.submit(self.load_catalog_source, p_pds, "pds")
                    fut_raw = ex.submit(self.load_catalog_source, p_raw, "raw")
                    state["df_pds"] = fut_pds.result()
                    state["df_raw"] = fut_raw.result()
                state["df"] = self.combine_catalogs(state["df_pds"], state["df_raw"])
                state["data_source"] = f"pds={p_pds} | raw={p_raw}"

        # Stable token used for caching filtered results. Updates automatically when catalog files change.
        try:
            p_pds = self._resolve_catalog_parquet()
            p_raw = self._resolve_catalog_parquet_raw()
            pds_mtime = p_pds.stat().st_mtime if p_pds.exists() else 0.0
            pds_size = p_pds.stat().st_size if p_pds.exists() else 0
            raw_mtime = p_raw.stat().st_mtime if p_raw.exists() else 0.0
            raw_size = p_raw.stat().st_size if p_raw.exists() else 0
            state["_catalog_token"] = f"{p_pds.name}:{pds_mtime:.6f}:{pds_size}|{p_raw.name}:{raw_mtime:.6f}:{raw_size}"
        except Exception:
            state["_catalog_token"] = self._normalize_text(state.get("data_source"))

        if "df_filtered" not in state:
            state["df_filtered"] = state["df"].copy()
        if "df_filtered_pds" not in state:
            state["df_filtered_pds"] = state["df_pds"].copy() if isinstance(state.get("df_pds"), pd.DataFrame) else pd.DataFrame()
        if "df_filtered_raw" not in state:
            state["df_filtered_raw"] = state["df_raw"].copy() if isinstance(state.get("df_raw"), pd.DataFrame) else pd.DataFrame()
        if "selected_df" not in state:
            # `get_selected_images_df` in runtime depends on st.session_state; allow both signatures.
            try:
                selected = self._get_selected_images_df(state)  # type: ignore[misc]
            except TypeError:
                selected = self._get_selected_images_df()  # type: ignore[call-arg]
            state["selected_df"] = selected
        if not state.get("saved_output_files"):
            self._refresh_saved_output_files()

        intent_p = self._resolve_intent_config()
        mtime = intent_p.stat().st_mtime if intent_p.exists() else 0.0
        if ("intent_cfg" not in state) or state.get("intent_cfg_mtime") != mtime:
            if used_preload and isinstance(preload_intent, dict) and abs(preload_intent_mtime - mtime) < 0.0001:
                state["intent_cfg"] = preload_intent
                state["intent_cfg_mtime"] = preload_intent_mtime
            else:
                state["intent_cfg"] = self._load_json(intent_p)
                state["intent_cfg_mtime"] = mtime

