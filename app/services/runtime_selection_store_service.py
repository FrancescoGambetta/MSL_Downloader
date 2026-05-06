from __future__ import annotations

import hashlib
import pickle
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd


class RuntimeSelectionStoreService:
    def __init__(
        self,
        *,
        resolve_selection_store: Callable[[], Path],
        normalize_text: Callable[[Any], str],
        now: Callable[[], datetime],
    ) -> None:
        self._resolve_selection_store = resolve_selection_store
        self._normalize_text = normalize_text
        self._now = now

    def load_selected_row_ids(self) -> list[int]:
        p = self._resolve_selection_store()
        if not p.exists():
            return []
        try:
            with p.open("rb") as f:
                payload = pickle.load(f)
            if isinstance(payload, dict):
                ids = payload.get("row_ids", [])
            else:
                ids = payload
            if not isinstance(ids, list):
                return []
            return [int(x) for x in ids]
        except Exception:
            return []

    def save_selected_row_ids(self, state: dict[str, Any], row_ids: list[int]) -> None:
        p = self._resolve_selection_store()
        p.parent.mkdir(parents=True, exist_ok=True)
        ids_sorted = sorted(set(int(x) for x in row_ids))

        # Avoid rewriting the same selection repeatedly (can be large, and causes UI stalls).
        h = hashlib.sha1()
        for v in ids_sorted:
            h.update(str(v).encode("utf-8", errors="ignore"))
            h.update(b",")
        digest = h.hexdigest()
        if p.exists() and self._normalize_text(state.get("_selection_row_ids_hash")) == digest:
            return

        state["_selection_row_ids_hash"] = digest
        payload = {
            "saved_at": self._now().isoformat(timespec="seconds"),
            "row_ids": ids_sorted,
        }
        with p.open("wb") as f:
            pickle.dump(payload, f)

    def get_selected_images_df(self, state: dict[str, Any]) -> pd.DataFrame:
        df = state.get("df")
        if not isinstance(df, pd.DataFrame) or len(df) == 0 or "_row_id" not in df.columns:
            return pd.DataFrame()
        ids = self.load_selected_row_ids()
        if not ids:
            return pd.DataFrame(columns=df.columns.tolist())
        out = df[df["_row_id"].astype(int).isin(set(ids))].copy()
        if "img_url" in out.columns:
            out = out.drop_duplicates(subset=["img_url"], keep="first")
        return out.reset_index(drop=True)

    def persist_selection_from_filtered(self, state: dict[str, Any]) -> int:
        df = state.get("df_filtered")
        if not isinstance(df, pd.DataFrame) or len(df) == 0 or "_row_id" not in df.columns:
            self.save_selected_row_ids(state, [])
            state["selected_df"] = pd.DataFrame()
            return 0
        ids = df["_row_id"].astype(int).tolist()
        self.save_selected_row_ids(state, ids)
        selected_df = self.get_selected_images_df(state)
        state["selected_df"] = selected_df
        return len(selected_df)

