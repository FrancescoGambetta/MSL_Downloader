from __future__ import annotations

from typing import Any, Callable

import pandas as pd


class CatalogDataframeOpsService:
    def __init__(
        self,
        *,
        normalize_text: Callable[[Any], str],
        norm_ascii: Callable[[str], str],
    ) -> None:
        self._normalize_text = normalize_text
        self._norm_ascii = norm_ascii

    def deduplicate_with_source_priority(self, df: pd.DataFrame) -> pd.DataFrame:
        if len(df) == 0:
            return df.copy()

        out = df.copy()
        out["_dedup_key"] = self._dedup_key_series(out)
        if "source" in out.columns:
            prio = out["source"].fillna("").astype(str).str.lower().map({"pds": 0, "raw": 1}).fillna(9).astype(int)
        else:
            prio = pd.Series([9] * len(out), index=out.index, dtype="int64")
        out["_source_prio"] = prio

        out = out.sort_values(by=["_source_prio"], ascending=True, kind="stable")
        out = out.drop_duplicates(subset=["_dedup_key"], keep="first")
        out = out.drop(columns=["_source_prio", "_dedup_key"], errors="ignore")
        return out.reset_index(drop=True)

    def reduce_raw_burst_sequences(self, df: pd.DataFrame, *, keep_per_group: int = 1) -> pd.DataFrame:
        if len(df) == 0 or keep_per_group <= 0:
            return df.copy()
        if "source" not in df.columns:
            return df.copy()

        out = df.copy()
        is_raw = out["source"].fillna("").astype(str).str.lower().eq("raw")
        if not bool(is_raw.any()):
            return out

        raw = out[is_raw].copy()
        raw["_burst_group_key"] = self._raw_burst_group_key(raw)
        has_key = raw["_burst_group_key"].astype(str).str.len() > 0
        raw["_burst_rank"] = 0
        if bool(has_key.any()):
            raw.loc[has_key, "_burst_rank"] = raw.loc[has_key].groupby("_burst_group_key", sort=False).cumcount()
        kept_raw = raw[(~has_key) | (raw["_burst_rank"] < int(keep_per_group))].drop(
            columns=["_burst_group_key", "_burst_rank"], errors="ignore"
        )

        out_non_raw = out[~is_raw]
        out = pd.concat([out_non_raw, kept_raw], axis=0).sort_index(kind="stable")
        return out.reset_index(drop=True)

    def _dedup_key_series(self, df: pd.DataFrame) -> pd.Series:
        key = pd.Series([""] * len(df), index=df.index, dtype="object")

        if "product_id" in df.columns:
            s = df["product_id"].fillna("").astype(str).str.strip()
            mask = (key == "") & (s != "")
            key.loc[mask] = "p:" + s.loc[mask].str.upper()

        if "image_id" in df.columns:
            s = df["image_id"].fillna("").astype(str).str.strip()
            mask = (key == "") & (s != "")
            key.loc[mask] = "i:" + s.loc[mask].str.upper()

        if "img_url" in df.columns:
            s = (
                df["img_url"]
                .fillna("")
                .astype(str)
                .str.strip()
                .str.replace(r"\\?.*$", "", regex=True)
                .str.lower()
            )
            mask = (key == "") & (s != "")
            key.loc[mask] = "u:" + s.loc[mask]

        # Keep rows with missing identifiers distinct.
        fallback = key == ""
        if bool(fallback.any()):
            key.loc[fallback] = "__row__:" + key.index[fallback].astype(str)
        return key

    def _raw_burst_group_key(self, df: pd.DataFrame) -> pd.Series:
        if len(df) == 0:
            return pd.Series([], dtype="object")

        if "_file_name" in df.columns:
            name = df["_file_name"].fillna("").astype(str).str.upper()
        elif "img_url" in df.columns:
            name = (
                df["img_url"]
                .fillna("")
                .astype(str)
                .str.upper()
                .str.replace(r"^.*/", "", regex=True)
            )
        else:
            name = pd.Series([""] * len(df), index=df.index, dtype="object")

        stem = name.str.replace(r"\.[A-Z0-9]+$", "", regex=True)
        tail_from_edr = stem.str.extract(r"EDR_([A-Z0-9_]+)$", expand=False).fillna("")
        tail_generic = stem.str.replace(r"^[A-Z]{2,6}_[0-9]+", "", regex=True)
        tail = tail_from_edr.where(tail_from_edr.str.len() > 0, tail_generic).str.strip("_-")

        if "camera" in df.columns:
            cam = df["camera"].astype(str).apply(self._norm_ascii).str.replace(r"[^a-z0-9]+", "", regex=True)
        else:
            cam = pd.Series([""] * len(df), index=df.index, dtype="object")

        if "sol" in df.columns:
            sol_num = pd.to_numeric(df["sol"], errors="coerce")
            sol = sol_num.fillna(-1).astype("int64").astype(str)
        else:
            sol = pd.Series(["-1"] * len(df), index=df.index, dtype="object")

        return cam + "|" + sol + "|" + tail
