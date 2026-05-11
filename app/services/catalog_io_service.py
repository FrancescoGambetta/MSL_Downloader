from __future__ import annotations

from typing import Optional

import pandas as pd


class CatalogIOService:
    def load_catalog(self, path: str, *, columns: Optional[list[str]] = None) -> pd.DataFrame:
        """
        Load catalog parquet.
        `columns` is used as a performance knob to avoid reading unused fields at startup.
        """
        cols = columns if isinstance(columns, list) and columns else None
        return pd.read_parquet(path, columns=cols)

    def prepare_catalog_index(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        if "_row_id" not in out.columns:
            out["_row_id"] = out.index.astype(int)
        if "img_url" in out.columns:
            file_name = out["img_url"].fillna("").astype(str).str.rsplit("/", n=1).str[-1]
        else:
            file_name = pd.Series([""] * len(out), index=out.index)
        out["_file_name"] = file_name
        out["_suffix_code"] = (
            file_name.str.extract(r"_([A-Za-z0-9]+)\.(?:IMG|img)$", expand=False)
            .fillna("")
            .str.upper()
        )
        stem = file_name.str.replace(r"\.(?:IMG|img)$", "", regex=True)
        out["_family_key"] = stem.str.replace(r"_DR[A-Z0-9]{2}$", "", regex=True)
        return out
