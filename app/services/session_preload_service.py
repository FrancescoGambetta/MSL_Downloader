"""Background catalog+intent-config preload, so the first real page render doesn't block on the full synchronous parquet load.

`kickoff_login_preload` starts a background thread (once per process) that
loads both catalog parquets and the intent config into the module-level
`_PRELOAD_STATE` dict (see `session.py`). `ensure_heavy_state` is what
actually consumes that: it either adopts the preloaded snapshot (first load
only, if the catalog hasn't changed on disk since) or loads synchronously,
then makes sure every derived piece of session_state (`df_filtered*`,
`selected_df`, `intent_cfg`) is populated.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd


class SessionPreloadService:
    """Loads the PDS+RAW catalog parquets (in a background thread at login, or synchronously as a fallback) and derives the session's initial DataFrame state."""

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
        """Add a `source` column (if not already present) to `df`, tagging every row as "pds" or "raw"."""
        if len(df) == 0:
            return df.copy()
        out = df.copy()
        if "source" not in out.columns:
            out["source"] = source
        return out

    def combine_catalogs(self, df_pds: pd.DataFrame, df_raw: pd.DataFrame) -> pd.DataFrame:
        """Concatenate the PDS and RAW catalogs (each tagged with its `source`) into the single combined `state["df"]`."""
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
            "site",
            "drive",
            "pose",
            "sclk",
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
        """Load one catalog parquet (PDS or RAW) with only its minimal required columns, indexed and source-tagged."""
        if not path.exists():
            return pd.DataFrame()
        df = self._prepare_catalog_index(self._load_catalog(str(path), columns=self.catalog_min_columns(source)))
        return self.with_source(df, source)

    def preload_heavy_state_worker(self) -> None:
        """Background-thread entry point: load both catalogs + intent config and stash them in `_preload_state`. Run via `kickoff_login_preload`, never called directly."""
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
        """Start the background preload thread, if it hasn't started yet for this process (idempotent)."""
        with self._preload_lock:
            if self._preload_state.get("started"):
                return
            self._preload_state["started"] = True
        t = threading.Thread(target=self.preload_heavy_state_worker, name="dwnapp-preload", daemon=True)
        t.start()

    def ensure_heavy_state(self, state: dict[str, Any]) -> None:
        """Make sure `state` has a loaded, up-to-date catalog (df/df_pds/df_raw), filtered views, selection, and intent config.

        Adopts the background-preloaded snapshot when this is the session's
        first load and the catalog hasn't changed on disk since preload ran;
        otherwise loads synchronously. Also re-detects (via an mtime+size
        token) whether the catalog changed on disk since this session last
        loaded it -- e.g. another process ran an update/repair while this
        session stayed open -- and reloads if so.
        """
        used_preload = False

        # Compute the on-disk catalog token up front so we can detect not only
        # "never loaded in this session" but also "catalog changed on disk since
        # we last loaded it" (e.g. the user ran "Aggiorna catalogo"/"Ripara" in
        # another process while this session stayed open). Without this second
        # check, state["df"]/df_pds/df_raw were loaded once and then kept
        # forever for the life of the session, even though the token was being
        # recomputed every call -- the token only ever invalidated the
        # *filtered-results* cache in catalog_apply_filters_service, which just
        # re-filtered the same stale source data.
        try:
            p_pds = self._resolve_catalog_parquet()
            p_raw = self._resolve_catalog_parquet_raw()
            pds_mtime = p_pds.stat().st_mtime if p_pds.exists() else 0.0
            pds_size = p_pds.stat().st_size if p_pds.exists() else 0
            raw_mtime = p_raw.stat().st_mtime if p_raw.exists() else 0.0
            raw_size = p_raw.stat().st_size if p_raw.exists() else 0
            fresh_token = f"{p_pds.name}:{pds_mtime:.6f}:{pds_size}|{p_raw.name}:{raw_mtime:.6f}:{raw_size}"
        except Exception:
            fresh_token = ""

        catalog_changed_on_disk = (
            bool(fresh_token) and "_catalog_token" in state and state.get("_catalog_token") != fresh_token
        )

        with self._preload_lock:
            preload_done = bool(self._preload_state.get("done"))
            preload_df = self._preload_state.get("catalog_df")
            preload_df_pds = self._preload_state.get("catalog_df_pds")
            preload_df_raw = self._preload_state.get("catalog_df_raw")
            preload_source = self._normalize_text(self._preload_state.get("data_source"))
            preload_intent = self._preload_state.get("intent_cfg")
            preload_intent_mtime = float(self._preload_state.get("intent_cfg_mtime") or 0.0)

        needs_initial_load = ("df" not in state) or ("df_pds" not in state) or ("df_raw" not in state)
        if needs_initial_load or catalog_changed_on_disk:
            # The preload snapshot is a one-time capture from app startup: useful
            # for the very first load, meaningless once we already know the
            # catalog moved on since -- in that case always re-read the parquet.
            if (
                needs_initial_load
                and not catalog_changed_on_disk
                and preload_done
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

        # Stable token used for caching filtered results, and (see above) to
        # detect catalog changes on disk across reruns of the same session.
        state["_catalog_token"] = fresh_token or self._normalize_text(state.get("data_source"))

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

