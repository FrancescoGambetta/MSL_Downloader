#!/usr/bin/env python3
"""Retry only ChemCam catalog records whose PDS label could not be parsed.

Maintenance script, run manually (`python -m
core.repair_chemcam_catalog_labels`): re-fetches and re-parses just the
`.LBL` for every product currently flagged with a `lbl_parse_error` (a
transient network hiccup during the original scan, or a label the parser
choked on at the time), and clears the error flag on success.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

try:
    from core.make_msl_catalog import PDSClient, _write_json
    from core.metashape_engine import build_product_from_lbl
except ModuleNotFoundError:  # esecuzione diretta dalla cartella core
    from make_msl_catalog import PDSClient, _write_json  # type: ignore
    from metashape_engine import build_product_from_lbl  # type: ignore


def main() -> int:
    """Retry every ChemCam product with a recorded label-parse error and rewrite the catalog. Returns 0 unless some product is still failing."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default="data/catalog/chemcam_catalog.json")
    parser.add_argument("--parquet", default="data/catalog/chemcam_catalog.parquet")
    args = parser.parse_args()

    catalog_path = Path(args.catalog).resolve()
    parquet_path = Path(args.parquet).resolve()
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    products = catalog["cameras"]["chemcam"]["products"]
    failed = [product for product in products if product.get("lbl_parse_error")]
    client = PDSClient(timeout=30, retries=5)

    repaired = 0
    for product in failed:
        try:
            parsed = build_product_from_lbl(
                lbl_text=client.get_text(str(product["lbl_url"])),
                img_url=str(product["img_url"]),
                lbl_url=str(product["lbl_url"]),
                base_url=str(product["sol_url"]),
            )
            for field in (
                "image_id", "instrument_id", "instrument_name", "start_time",
                "image_time", "site", "drive", "pose", "sclk",
            ):
                value = getattr(parsed, field)
                if value is None:
                    continue
                if field == "sclk":
                    # The canonical schema stores sclk as a string (like every
                    # other builder/enrichment path does); parsed.sclk is a
                    # float. Writing the raw float here would leave a mixed
                    # str/float "sclk" column across repaired vs. untouched
                    # products, which PyArrow refuses to write to parquet.
                    value = str(value)
                product[field] = value
            product["lbl_parse_error"] = None
            repaired += 1
            print(f"[repaired] {product['product_id']}")
        except Exception as exc:  # noqa: BLE001
            product["lbl_parse_error"] = f"{type(exc).__name__}: {exc}"
            print(f"[still_failed] {product['product_id']}: {exc}")

    _write_json(catalog_path, catalog)
    parquet_tmp = parquet_path.with_suffix(".parquet.tmp")
    pd.DataFrame(products).to_parquet(parquet_tmp, index=False)
    parquet_tmp.replace(parquet_path)
    remaining = sum(bool(product.get("lbl_parse_error")) for product in products)
    print(f"repaired={repaired} remaining={remaining} products={len(products)}")
    return 0 if remaining == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
