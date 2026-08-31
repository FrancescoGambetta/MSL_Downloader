#!/usr/bin/env python3
"""Backfill ChemCam PDS output metadata from the official PDS catalog.

One-off migration script (run manually, `python -m
core.backfill_chemcam_pds_output_metadata`): for ChemCam `.meta.json`
outputs already saved before the catalog carried `site`/`drive`/`pose`/
`sclk`/`start_time` for CR0 products, this looks each product up in
`Catalog_PDS.parquet` and fills in whatever fields are missing/stale.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


FIELDS = ("site", "drive", "pose", "sclk", "start_time")


def json_value(value: Any) -> Any:
    """Coerce a pandas cell value to a JSON-safe Python value (NaN/NA -> None, numpy scalars -> native)."""
    if value is None or value is pd.NA:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    return value


def main() -> int:
    """Update every ChemCam CR0 `.meta.json` under `--output` with fresh values from `--catalog`. Returns 0 unless some product wasn't found in the catalog."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default="data/catalog/Catalog_PDS.parquet")
    parser.add_argument("--output", default="output/PDS")
    args = parser.parse_args()

    catalog = pd.read_parquet(args.catalog, columns=["product_id", *FIELDS])
    by_id = {
        str(row["product_id"]).casefold(): {field: json_value(row[field]) for field in FIELDS}
        for _, row in catalog.iterrows()
    }

    updated = 0
    missing = 0
    unchanged = 0
    for path in Path(args.output).rglob("*.meta.json"):
        if not path.name.casefold().startswith("cr0_"):
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        product_id = str(payload.get("product_id") or path.name.removesuffix(".meta.json"))
        values = by_id.get(product_id.casefold())
        if values is None:
            missing += 1
            continue
        changed = False
        for field, value in values.items():
            if payload.get(field) != value:
                payload[field] = value
                changed = True
        if not changed:
            unchanged += 1
            continue
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(path)
        updated += 1

    print(f"updated={updated} unchanged={unchanged} missing_in_catalog={missing}")
    return 0 if missing == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
