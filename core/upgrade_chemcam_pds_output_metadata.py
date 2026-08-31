#!/usr/bin/env python3
"""Upgrade existing ChemCam PDS output metadata to the standard rich schema.

One-off migration script, run manually: for every already-downloaded
ChemCam CR0 product under `output/PDS`, re-fetches its `.LBL`, re-runs
rover-CSV GPS matching, rewrites its EXIF (now including GPS if a match was
found), and rebuilds its `.meta.json` via the same `build_meta_payload` the
live download pipeline uses -- bringing older, thinner metadata up to the
current schema.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import piexif
import requests

from core.default_camera_meta import defaults_for_record
from core.engine_pipeline import _build_piexif_bytes_for_metashape
from core.metashape_engine import (
    MatchInfo,
    build_meta_payload,
    build_product_from_lbl,
    load_rover_csv,
    match_rover_row,
)


def as_float(value):
    """Coerce `value` to a float, or None if it's blank/unparseable."""
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def main() -> int:
    """Re-derive and rewrite `.meta.json`+EXIF for every ChemCam CR0 product under output/PDS. Returns 0 unless some product failed."""
    output_root = Path("output/PDS")
    csv_path = Path("data/reference/geo/localized_interp_demv2.csv").resolve()
    csv_url = "https://planetarydata.jpl.nasa.gov/w10n/msl/msl_places/data_localizations/localized_interp_demv2.csv"
    rows = load_rover_csv(csv_path)
    catalog = pd.read_parquet(
        "data/catalog/Catalog_PDS.parquet",
        columns=["product_id", "img_url", "lbl_url", "sol_url"],
    )
    by_id = {str(row.product_id).casefold(): row for row in catalog.itertuples(index=False)}
    pixel_um = float(defaults_for_record(camera="chemcam")["pixel_size_um"])
    resolution = 10000.0 / pixel_um
    updated = 0
    failed = 0

    with requests.Session() as session:
        session.headers.update({"User-Agent": "MSL-Downloader-ChemCam-Metadata/1.0"})
        for meta_path in output_root.rglob("*.meta.json"):
            old = json.loads(meta_path.read_text(encoding="utf-8"))
            old_product = old.get("product") if isinstance(old.get("product"), dict) else {}
            product_id = str(old.get("product_id") or old_product.get("product_id") or meta_path.name.removesuffix(".meta.json"))
            if not product_id.casefold().startswith("cr0_"):
                continue
            row = by_id.get(product_id.casefold())
            if row is None:
                failed += 1
                continue
            try:
                response = session.get(str(row.lbl_url), timeout=60)
                response.raise_for_status()
                lbl_text = response.text
                product = build_product_from_lbl(lbl_text, str(row.img_url), str(row.lbl_url), str(row.sol_url))
                csv_row, match_info = match_rover_row(product, rows)
                if match_info is None:
                    match_info = MatchInfo("none", False, False, 0, None)

                latitude = as_float((csv_row or {}).get("planetocentric_latitude"))
                longitude = as_float((csv_row or {}).get("longitude"))
                altitude = as_float((csv_row or {}).get("elevation"))
                exif_written = {
                    "PixelSizeMicrometers": pixel_um,
                    "FocalPlaneXResolution": resolution,
                    "FocalPlaneYResolution": resolution,
                    "FocalPlaneResolutionUnit": 3,
                    "calibration_kind": "chemcam_rmi_fixed_detector",
                }
                if latitude is not None:
                    exif_written["GPSLatitude"] = latitude
                if longitude is not None:
                    exif_written["GPSLongitude"] = longitude
                if altitude is not None:
                    exif_written["GPSAltitude"] = altitude

                jpg_candidates = [
                    meta_path.parent / f"{product_id}.jpg",
                    meta_path.parent.parent / f"{product_id}.jpg",
                    meta_path.parent.parent.parent / f"{product_id}.jpg",
                ]
                jpg_path = next(path for path in jpg_candidates if path.exists())
                piexif.insert(
                    _build_piexif_bytes_for_metashape(
                        focal_length_mm=None,
                        focal_plane_x_resolution=resolution,
                        focal_plane_y_resolution=resolution,
                        focal_plane_resolution_unit=3,
                        latitude=latitude,
                        longitude=longitude,
                        altitude=altitude,
                    ),
                    str(jpg_path),
                )
                payload = build_meta_payload(
                    product=product,
                    lbl_text=lbl_text,
                    csv_row=csv_row,
                    match_info=match_info,
                    img_url=str(row.img_url),
                    lbl_url=str(row.lbl_url),
                    rover_csv_url=csv_url,
                    rover_csv_local_path=str(csv_path),
                    output_jpg=str(jpg_path),
                    output_meta_json=str(meta_path),
                    exif_written=exif_written,
                    warnings=[] if csv_row is not None else ["No rover localisation row found. JPG created without GPS fields."],
                    errors=[],
                    engine_version="app-0.1.0",
                )
                payload["post_processing"] = old.get("processing") or old.get("post_processing") or {
                    "kind": "chemcam_rmi_to_jpeg"
                }
                temp = meta_path.with_suffix(meta_path.suffix + ".tmp")
                temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                temp.replace(meta_path)
                updated += 1
            except Exception as exc:
                failed += 1
                print(f"[failed] {product_id}: {exc}")
    print(f"updated={updated} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
