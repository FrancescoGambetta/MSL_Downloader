#!/usr/bin/env python3
"""Add documented nominal ChemCam RMI optics to existing JPG/meta outputs.

One-off migration script, run manually: `python -m core.backfill_chemcam_fixed_exif`
from the project root (it walks `output/` relative to the current working
directory). For ChemCam RMI products already downloaded before pixel-size
EXIF was written at download time, this backfills the same fixed-detector
focal-plane-resolution values into their JPGs and records the fact in each
product's `.meta.json`.
"""

from __future__ import annotations

import json
from pathlib import Path

import piexif

from core.default_camera_meta import defaults_for_record
from core.engine_pipeline import _build_piexif_bytes_for_metashape


def main() -> int:
    """Walk `output/` for ChemCam `.meta.json` files, write EXIF into their JPG, and record it. Returns 0 if every match had a JPG, else 1."""
    root = Path("output")
    defaults = defaults_for_record(camera="chemcam", instrument_id="CHEMCAM_RMI")
    pixel_um = float(defaults["pixel_size_um"])
    resolution = 10000.0 / pixel_um
    exif_bytes = _build_piexif_bytes_for_metashape(
        focal_length_mm=None,
        focal_plane_x_resolution=resolution,
        focal_plane_y_resolution=resolution,
        focal_plane_resolution_unit=3,
        latitude=None,
        longitude=None,
        altitude=None,
    )
    values = {
        "PixelSizeMicrometers": pixel_um,
        "FocalPlaneXResolution": resolution,
        "FocalPlaneYResolution": resolution,
        "FocalPlaneResolutionUnit": 3,
        "calibration_kind": "chemcam_rmi_fixed_detector",
    }

    updated = 0
    missing_jpg = 0
    for meta_path in root.rglob("*.meta.json"):
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
        camera = str(payload.get("camera") or (payload.get("product") or {}).get("camera") or "").casefold()
        product_id = str(payload.get("product_id") or (payload.get("product") or {}).get("product_id") or "")
        if camera != "chemcam" and not product_id.casefold().startswith("cr0_"):
            continue
        candidates = [
            meta_path.parent / f"{product_id}.jpg",
            meta_path.parent.parent / f"{product_id}.jpg",
            meta_path.parent.parent.parent / f"{product_id}.jpg",
        ]
        jpg_path = next((path for path in candidates if path.exists()), None)
        if jpg_path is None:
            missing_jpg += 1
            continue
        piexif.insert(exif_bytes, str(jpg_path))
        payload["exif_written"] = values
        temp = meta_path.with_suffix(meta_path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(meta_path)
        updated += 1
    print(f"updated={updated} missing_jpg={missing_jpg}")
    return 0 if missing_jpg == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
