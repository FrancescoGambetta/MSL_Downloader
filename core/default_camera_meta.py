"""
Hard-coded calibration defaults used when no per-image calibration is available.

These defaults are intentionally minimal and camera-scoped, to support:
- RAW archive JPG downloads (no .LBL): still write Metashape-friendly EXIF
- future catalog enrichment where only camera identity is known

Units:
- focal_length_mm: millimeters
- pixel_size_um: micrometers (optional; used to derive focal-plane resolution)
"""

from __future__ import annotations

from typing import Any, Optional


CAMERA_DEFAULTS: dict[str, dict[str, Any]] = {
    # User-provided values (to be validated against reference datasets).
    "navcam": {"focal_length_mm": 14.67, "pixel_size_um": 12.0},
    "mastcam_left": {"focal_length_mm": 34.0, "pixel_size_um": 12.5},
    "mastcam_right": {"focal_length_mm": 100.0, "pixel_size_um": 12.5},
    "hazcam": {"focal_length_mm": 16.0, "pixel_size_um": 12.0},
    "mahli": {"focal_length_mm": 18.0, "pixel_size_um": 12.0},
    "mardi": {"focal_length_mm": 18.0, "pixel_size_um": 12.0},
}


def camera_key_from_ids(
    *,
    camera: Optional[str] = None,
    instrument_id: Optional[str] = None,
    product_id: Optional[str] = None,
) -> Optional[str]:
    cam = (camera or "").strip().lower()
    inst = (instrument_id or "").strip().upper()
    pid = (product_id or "").strip().upper()

    if cam in {"navcam", "hazcam", "mahli", "mardi"}:
        return cam

    if cam == "mastcam":
        # Common instrument ids seen in labels / catalogs.
        if inst.startswith(("MST_B", "MAST_B")):
            return "mastcam_right"
        if inst.startswith(("MST_A", "MAST_A")):
            return "mastcam_left"
        if "RIGHT" in inst or inst.endswith("_RIGHT") or inst in {"MAST_RIGHT", "MASTCAM_RIGHT"}:
            return "mastcam_right"
        if "LEFT" in inst or inst.endswith("_LEFT") or inst in {"MAST_LEFT", "MASTCAM_LEFT"}:
            return "mastcam_left"
        # RAW archive naming: 0001ML... / 0001MR...
        if "MR" in pid and "ML" not in pid:
            return "mastcam_right"
        if "ML" in pid and "MR" not in pid:
            return "mastcam_left"
        return "mastcam_left"

    # Instrument-based fallback (covers RAW archive instrument_id values).
    if inst.startswith(("NAV", "NAVCAM")):
        return "navcam"
    if inst.startswith(("MST_A", "MAST_A")):
        return "mastcam_left"
    if inst.startswith(("MST_B", "MAST_B")):
        return "mastcam_right"
    if inst.startswith(("MAST", "MASTCAM")):
        return "mastcam_right" if "RIGHT" in inst else "mastcam_left"
    if inst.startswith(("FHAZ", "RHAZ", "HAZ")) or "HAZ" in inst:
        return "hazcam"
    if inst.startswith(("MAHLI", "MAH")):
        return "mahli"
    if inst.startswith(("MARDI", "MAR", "MD")):
        return "mardi"

    return None


def defaults_for_record(
    *,
    camera: Optional[str] = None,
    instrument_id: Optional[str] = None,
    product_id: Optional[str] = None,
) -> dict[str, Any]:
    key = camera_key_from_ids(camera=camera, instrument_id=instrument_id, product_id=product_id)
    if not key:
        return {}
    return dict(CAMERA_DEFAULTS.get(key) or {})
