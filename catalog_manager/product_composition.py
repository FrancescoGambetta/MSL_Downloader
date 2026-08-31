"""Read-only product-segment inventory derived from the local Parquet catalogs."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq


KNOWN_SUFFIXES = {"DRCL", "DRCX", "DRLX", "DRXX", "DXXX"}
KNOWN_PROCESSING_MARKERS = ("ILTLF", "MXYLF", "ILT_F")
PREFIX_CAMERAS = {"navcam", "hazcam"}
MMM_CAMERAS = {"mastcam", "mahli", "mardi"}


def _segments(camera: str, product_id: str) -> set[tuple[str, str]]:
    """Return distinct structural markers without assigning unverified meanings."""
    value = product_id.rsplit(".", 1)[0]
    first = value.split("_", 1)[0]
    found: set[tuple[str, str]] = set()

    # MMM single-frame products use fixed fields. Positions 23–25 are,
    # respectively, product type, GOP counter, and version.
    if camera in MMM_CAMERAS and len(first) >= 2:
        if len(first) >= 25:
            descriptor = first[-3:].upper()
            found.add(("product_type", descriptor[0]))
            found.add(("gop_counter", descriptor[1]))
            found.add(("version", descriptor[2]))
        else:
            # Early RAW MAHLI products use an abbreviated two-character tail
            # (product type + version) and do not expose a GOP field.
            descriptor = first[-2:].upper()
            found.add(("product_type", descriptor[0]))
            found.add(("version", descriptor[1]))
        found.add(("product_variant", descriptor))
    if camera in PREFIX_CAMERAS and len(first) >= 3:
        found.add(("camera_prefix", first[:3].upper()))
    if camera == "chemcam" and len(first) >= 3:
        found.add(("instrument_product", first[:3].upper()))
        if "PRC" in value.upper():
            found.add(("processing_marker", "PRC"))

    final = value.rsplit("_", 1)[-1].upper()
    if final in KNOWN_SUFFIXES:
        found.add(("suffix", final))
    upper = value.upper()
    for marker in KNOWN_PROCESSING_MARKERS:
        if marker in upper:
            found.add(("processing_marker", marker))
    return found


def build_inventory(
    parquet_path: Path, catalog: str = "pds"
) -> dict[str, dict[str, int | list[dict[str, int | str]]]]:
    """Count filename segments per camera using only two Parquet columns.

    RAW products don't follow the PDS filename convention _segments() parses
    (no LBL, no per-camera suffix codes) -- the only dimension NASA's RAW
    manifest actually verifies is sample_type. For catalog="raw", skip the
    PDS-shaped filename parsing entirely rather than present guessed-at
    codes as if they were confirmed, and tabulate sample_type instead
    (including an explicit "unknown" bucket for the many older records that
    predate this field, so segment counts always add up to the true total).
    """
    is_raw = catalog == "raw"
    available = set(pq.ParquetFile(parquet_path).schema_arrow.names)
    optional = ["sample_type"] if is_raw else [name for name in ("img_name", "tif_name", "sample_type") if name in available]
    optional = [name for name in optional if name in available]
    table = pq.read_table(parquet_path, columns=["camera", "product_id", *optional])
    row_count = len(table)
    values = {name: table[name].to_pylist() for name in table.column_names}
    empty_column = [None] * row_count
    img_names = values.get("img_name", empty_column)
    tif_names = values.get("tif_name", empty_column)
    sample_types = values.get("sample_type", empty_column)
    counters: dict[str, Counter[tuple[str, str]]] = defaultdict(Counter)
    totals: Counter[str] = Counter()
    for index in range(row_count):
        camera = values["camera"][index]
        product_id = values["product_id"][index]
        camera_key = str(camera or "unknown").lower()
        totals[camera_key] += 1
        if is_raw:
            sample_type = str(sample_types[index] or "").strip().upper()
            counters[camera_key][("sample_type", sample_type or "UNKNOWN")] += 1
            continue
        for segment in _segments(camera_key, str(product_id or "")):
            counters[camera_key][segment] += 1
        image_name = str(tif_names[index] or img_names[index] or "")
        if "." in image_name:
            counters[camera_key][("file_format", image_name.rsplit(".", 1)[-1].upper())] += 1
        sample_type = str(sample_types[index] or "").strip().lower()
        if sample_type:
            counters[camera_key][("sample_type", sample_type.upper())] += 1
    return {
        camera: {
            "total_products": totals[camera],
            "segments": [
                {"dimension": dimension, "code": code, "count": count}
                for (dimension, code), count in sorted(values.items(), key=lambda item: (-item[1], item[0]))
            ],
        }
        for camera, values in sorted(counters.items())
    }
