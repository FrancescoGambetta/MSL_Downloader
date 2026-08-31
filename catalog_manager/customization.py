"""Camera-customization domain logic: which product-type/processing-level (or
camera-prefix/marker) combinations exist for a camera, and translating a user's
checkbox selection into the `--include-*` CLI flags `core/make_msl_catalog.py`
understands.

Two camera "shapes" are handled, each with its own config data file:
- MMM cameras (mastcam/mahli/mardi): `primary` = product type, `secondary` =
  processing level, from `data/pds_camera_compatibility.json`'s `"mmm"` section.
- Engineering cameras (navcam/hazcam/chemcam): `primary` = camera-name prefix,
  `secondary` = processing marker, from the same file's `"engineering"` section
  (navcam additionally has its own `data/pds_navcam_compatibility.json`).

Used by `workers/customization_worker.py` (apply a selection to a fresh scan) and
`workers/pds_update_worker.py` (apply the camera's already-saved selection to a
routine update, via `current_include_args`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import re

import pyarrow.parquet as pq


NAVCAM_PREFIXES = ("NAA", "NAB", "NLA", "NLB", "NRA", "NRB")
NAVCAM_COMPATIBILITY: dict[str, dict[str, list[str]]] = json.loads(
    (Path(__file__).parent / "data" / "pds_navcam_compatibility.json").read_text(encoding="utf-8")
)
NAVCAM_MARKERS = tuple(sorted({
    f"{family}{variant}"
    for family, prefixes in NAVCAM_COMPATIBILITY.items()
    for variants in prefixes.values()
    for variant in variants
}))
PDS_CAMERA_COMPATIBILITY: dict[str, Any] = json.loads(
    (Path(__file__).parent / "data" / "pds_camera_compatibility.json").read_text(encoding="utf-8")
)


def _mmm_config(camera: str) -> dict[str, Any]:
    """Build `camera`'s option config from the `"mmm"` section of `PDS_CAMERA_COMPATIBILITY`: primary=product types, secondary=processing levels (union across all product types)."""
    values = PDS_CAMERA_COMPATIBILITY["mmm"][camera]
    return {
        "primary_dimension": "product_types",
        "secondary_dimension": "processing_levels",
        "primary": tuple(values),
        "secondary": tuple(sorted({level for levels in values.values() for level in levels})),
    }


def _engineering_config(camera: str) -> dict[str, Any]:
    """Build `camera`'s option config from the `"engineering"` section of `PDS_CAMERA_COMPATIBILITY`: primary=camera-name prefixes, secondary=processing markers (union across all prefixes)."""
    families = PDS_CAMERA_COMPATIBILITY["engineering"][camera]
    prefixes = sorted({prefix for values in families.values() for prefix in values})
    markers = sorted({f"{family}{variant}" for family, values in families.items() for variants in values.values() for variant in variants})
    return {
        "primary_dimension": "camera_prefixes",
        "secondary_dimension": "processing_markers",
        "primary": tuple(prefixes),
        "secondary": tuple(markers),
    }

CAMERA_OPTIONS: dict[str, dict[str, Any]] = {
    "mastcam": _mmm_config("mastcam"),
    "mahli": _mmm_config("mahli"),
    "mardi": _mmm_config("mardi"),
    "navcam": {"primary_dimension": "camera_prefixes", "secondary_dimension": "processing_markers", "primary": NAVCAM_PREFIXES, "secondary": NAVCAM_MARKERS},
    "hazcam": _engineering_config("hazcam"),
    "chemcam": _engineering_config("chemcam"),
}
CUSTOMIZABLE_CAMERAS = tuple(CAMERA_OPTIONS)
KNOWN_SUFFIXES = {"DXXX", "DRXX", "DRCX", "DRLX", "DRCL"}


def _mmm_type(camera: str, product_id: str) -> str | None:
    """Extract an MMM camera's product-type code (e.g. `E01`) from the tail of `product_id`, or `None` if it doesn't match the expected pattern."""
    match = re.search(r"([A-Z][0-9]{2})_D[A-Z]{3}$", product_id.upper().rsplit(".", 1)[0])
    return match.group(1) if match else None


def product_pair(camera: str, product_id: object) -> tuple[str, str] | None:
    """Parse `product_id` into `(primary, secondary)` per `camera`'s shape (MMM product-type+level, or engineering prefix+marker), returning `None` if it doesn't parse or the parsed values aren't in `CAMERA_OPTIONS[camera]`."""
    value = str(product_id or "").rsplit(".", 1)[0]
    upper = value.upper()
    if camera in {"mastcam", "mahli", "mardi"}:
        primary = _mmm_type(camera, value)
        secondary = value.rsplit("_", 1)[-1].upper()
    elif camera in {"navcam", "hazcam", "chemcam"}:
        match = re.match(r"^([A-Z0-9]{3})_\d+([A-Z0-9_]{5})", upper)
        if not match:
            return None
        primary, secondary = match.groups()
    else:
        return None
    if primary in CAMERA_OPTIONS[camera]["primary"] and secondary in CAMERA_OPTIONS[camera]["secondary"]:
        return primary, secondary
    return None


def current_camera_options(parquet_path: Path) -> dict[str, dict[str, set[str]]]:
    """Scan `parquet_path` and, for every camera, group the secondary values actually present in the catalog under each primary value -- the live "what combinations exist today" picture the customization UI's checkboxes are built from."""
    table = pq.read_table(parquet_path, columns=["camera", "product_id"])
    result = {camera: {primary: set() for primary in config["primary"]} for camera, config in CAMERA_OPTIONS.items()}
    for camera_value, product_id in zip(table["camera"].to_pylist(), table["product_id"].to_pylist()):
        camera = str(camera_value or "").casefold()
        if camera in result and (pair := product_pair(camera, product_id)):
            result[camera][pair[0]].add(pair[1])
    return result


def include_args_for_camera(camera: str, combinations: dict[str, list[str]]) -> list[str]:
    """Translate a {primary: [secondary, ...]} selection into the --include-*
    CLI flags core/make_msl_catalog.py understands. Shared by the
    customization worker and the single-camera update worker, so both build
    the same filter the same way."""
    config = CAMERA_OPTIONS[camera]
    primary_argument = "--include-product-types" if config["primary_dimension"] == "product_types" else "--include-camera-prefixes"
    secondary_argument = "--include-suffixes" if config["secondary_dimension"] == "processing_levels" else "--include-processing-markers"
    primary_values = [str(value) for value in combinations if combinations.get(value)]
    secondary_values = sorted({str(value) for values in combinations.values() for value in values})
    if not primary_values or not secondary_values:
        return []
    return [primary_argument, *primary_values, secondary_argument, *secondary_values]


_CAMERA_RULES_PATH = Path(__file__).resolve().parent.parent / "config" / "camera_rules.json"


def _camera_rules() -> dict[str, Any]:
    return json.loads(_CAMERA_RULES_PATH.read_text(encoding="utf-8"))


def current_include_args(camera: str) -> list[str]:
    """Build the --include-* args core/make_msl_catalog.py's scanner
    understands, translated from this camera's config/camera_rules.json PDS
    rule -- the same hand-maintained rule the integrity check already
    verifies against (via _record_is_allowed in
    core/make_msl_catalog_pre3000.py). Both now read one source, so widening
    camera_rules.json (e.g. to admit a new product-type NASA started
    publishing) takes effect on the next update automatically.

    Previously this mirrored whatever was already in the local Parquet
    instead -- correct only as long as nobody edited camera_rules.json
    without also re-running a scan to match, since the two would then
    silently disagree with no update ever reflecting the edit."""
    if camera not in CAMERA_OPTIONS:
        return []
    rule = _camera_rules().get(camera) or {}
    pds_rule = (rule.get("rules") or {}).get("pds") or {}
    if not pds_rule:
        return []

    config = CAMERA_OPTIONS[camera]
    if config["primary_dimension"] == "product_types":
        primary_flag, primary_values = "--include-product-types", [
            str(v).rstrip("_").upper() for v in (pds_rule.get("filename_contains_any") or [])
        ]
    else:
        primary_flag, primary_values = "--include-camera-prefixes", [
            str(v).rstrip("_").upper() for v in (pds_rule.get("filename_prefix_any") or [])
        ]
    if config["secondary_dimension"] == "processing_levels":
        secondary_flag, secondary_values = "--include-suffixes", [
            str(v).upper() for v in (pds_rule.get("suffix_equals_any") or [])
        ]
    else:
        secondary_flag, secondary_values = "--include-processing-markers", [
            str(v).upper() for v in (pds_rule.get("filename_contains_any") or [])
        ]

    args: list[str] = []
    if primary_values:
        args += [primary_flag, *primary_values]
    if secondary_values:
        args += [secondary_flag, *secondary_values]
    return args


def filter_camera_selection(
    payload: dict[str, Any], camera: str, combinations: dict[str, list[str]]
) -> tuple[int, dict[str, set[str]]]:
    """Drop `camera`'s products in `payload` (a loaded catalog JSON) whose `(primary, secondary)` pair isn't in `combinations`, in place.

    Returns `(dropped_count, existing)` where `existing` is what combinations
    were present before filtering (for the UI to show what changed).
    """
    section = payload["cameras"][camera]
    original = list(section.get("products") or [])
    existing = {primary: set() for primary in CAMERA_OPTIONS[camera]["primary"]}
    for row in original:
        if pair := product_pair(camera, row.get("product_id")):
            existing[pair[0]].add(pair[1])
    desired = {primary: {str(value).upper() for value in values} for primary, values in combinations.items()}
    kept = [row for row in original if (pair := product_pair(camera, row.get("product_id"))) and pair[1] in desired.get(pair[0], set())]
    section["products"] = kept
    section["product_count"] = len(kept)
    return len(original) - len(kept), existing
