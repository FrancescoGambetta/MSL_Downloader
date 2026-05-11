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
        # Extract the suffix code from the filename. This is used by filters (e.g. DRCL, DXXX).
        # Support both PDS (.IMG) and RAW archive (.JPG/.JPEG) and keep the regex case-insensitive.
        out["_suffix_code"] = (
            file_name.str.extract(r"(?i)_([A-Za-z0-9]+)\.(?:IMG|JPG|JPEG|PNG|LBL)$", expand=False)
            .fillna("")
            .str.upper()
        )
        stem = file_name.str.replace(r"(?i)\.(?:IMG|JPG|JPEG|PNG|LBL)$", "", regex=True)
        # Normalize "variants" by stripping the trailing suffix segment (anything after the last underscore).
        # This matches the catalog builder logic in `core/make_msl_catalog.py:_family_key`.
        out["_family_key"] = stem.where(~stem.str.contains("_", regex=False), stem.str.rsplit("_", n=1).str[0])
        return out
