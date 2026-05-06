from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# ============================================================
# Data contracts
# ============================================================

@dataclass
class PdsProduct:
    """
    Represents a single PDS image product after parsing its LBL metadata.

    This is the canonical in-memory description of one product that the
    engine will later process into:
    - a clean JPG for Metashape
    - a rich .meta.json for the dashboard

    Fields in this class are intentionally limited to the most relevant
    identifiers and matching keys needed by the engine.
    """
    product_id: str
    image_id: Optional[str]
    instrument_id: Optional[str]
    instrument_name: Optional[str]
    sol: Optional[int]
    site: Optional[int]
    drive: Optional[int]
    pose: Optional[int]
    sclk: Optional[float]
    start_time: Optional[str]
    image_time: Optional[str]
    img_url: str
    lbl_url: str
    base_url: Optional[str] = None


@dataclass
class MatchInfo:
    """
    Describes how the rover position row was matched from the local CSV.

    This object is useful for:
    - traceability
    - debugging
    - dashboard display

    It records:
    - which strategy succeeded
    - whether GPS-related information was found
    - whether the CSV had to be refreshed
    - how many candidate rows were involved
    """
    strategy: str
    gps_found: bool
    csv_refreshed: bool
    csv_match_count: int
    frame: Optional[str] = None


@dataclass
class EngineResult:
    """
    Represents the final result of processing one product.

    This is the high-level structured output that the future dashboard
    can consume without needing to understand internal parsing logic.

    It includes:
    - product identity
    - output file paths
    - matching info
    - CSV row used
    - EXIF fields actually written
    - warnings and errors
    """
    product: PdsProduct
    output_jpg: str
    output_meta_json: str
    match_info: MatchInfo
    csv_row: Optional[dict[str, Any]]
    exif_written: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    status: str = "ok"


# ============================================================
# Internal regular expressions
# ============================================================

# Matches plain integer strings, including negative values.
_RE_INT = re.compile(r"^-?\d+$")

# Matches simple float strings, including negative values.
_RE_FLOAT = re.compile(r"^-?\d+(?:\.\d+)?$")

# Matches basic "KEY = VALUE" lines in PDS LBL files.
_RE_KEYVAL = re.compile(r"^\s*([A-Z0-9_]+)\s*=\s*(.+?)\s*$", re.IGNORECASE)


# ============================================================
# Basic parsing helpers
# ============================================================

def _clean_lbl_value(raw: str) -> str:
    """
    Normalises a raw LBL value string.

    Current behaviour:
    - strips surrounding whitespace
    - removes surrounding double quotes if present

    This helper is intentionally simple and conservative.
    """
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    return raw


def _parse_tuple_value(raw: str) -> list[str]:
    """
    Parses a simple tuple-like LBL value such as:
        (93, 3240, 12)

    Returns a list of string elements without surrounding quotes.

    If the input is not a parenthesised tuple, an empty list is returned.
    """
    raw = raw.strip()
    if not (raw.startswith("(") and raw.endswith(")")):
        return []

    inner = raw[1:-1].strip()
    if not inner:
        return []

    return [x.strip().strip('"') for x in inner.split(",")]


def _extract_tuple_from_lbl(lbl_text: str, key: str) -> list[str]:
    """
    Extracts tuple-like values from full LBL text, including multiline tuples.
    """
    m = re.search(
        rf"(?mis)^\s*{re.escape(key)}\s*=\s*\((.*?)\)\s*$",
        lbl_text,
    )
    if not m:
        return []

    inner = m.group(1).strip()
    if not inner:
        return []

    return [x.strip().strip('"') for x in inner.split(",") if x.strip()]


def _extract_scalar_from_lbl(lbl_text: str, key: str) -> Optional[str]:
    """
    Extracts a scalar KEY = VALUE from full LBL text.
    """
    m = re.search(
        rf"(?mi)^\s*{re.escape(key)}\s*=\s*(.+?)\s*$",
        lbl_text,
    )
    if not m:
        return None
    return _clean_lbl_value(m.group(1))


def _to_int(value: Any) -> Optional[int]:
    """
    Safely converts a value to int if it is a valid integer string.

    Returns:
    - int on success
    - None if conversion is not possible
    """
    if value is None:
        return None

    s = str(value).strip()
    if _RE_INT.match(s):
        try:
            return int(s)
        except Exception:
            return None
    return None


def _to_float(value: Any) -> Optional[float]:
    """
    Safely converts a value to float if it is a valid float string.

    Returns:
    - float on success
    - None if conversion is not possible
    """
    if value is None:
        return None

    s = str(value).strip()
    if _RE_FLOAT.match(s):
        try:
            return float(s)
        except Exception:
            return None
    return None


def _make_json_safe(value: Any) -> Any:
    """
    Recursively converts values into JSON-safe equivalents.

    This helper exists because some future CSV or parsing steps may return
    values that are not immediately serialisable by json.dump.
    """
    if isinstance(value, dict):
        return {str(k): _make_json_safe(v) for k, v in value.items()}

    if isinstance(value, list):
        return [_make_json_safe(v) for v in value]

    if isinstance(value, tuple):
        return [_make_json_safe(v) for v in value]

    if isinstance(value, Path):
        return str(value)

    return value


# ============================================================
# LBL parsing
# ============================================================

def parse_lbl_raw(lbl_text: str) -> dict[str, Any]:
    """
    Parses raw LBL text into a structured dictionary.

    This function performs three tasks:
    1. stores the full raw LBL text
    2. extracts simple KEY = VALUE pairs into a flat dictionary
    3. derives key matching fields needed by the engine

    Derived fields currently include:
    - product_id
    - image_id
    - instrument_id
    - instrument_name
    - sol
    - site
    - drive
    - pose
    - sclk
    - start_time
    - image_time

    Matching priority for site, drive and pose:
    - REFERENCE_COORD_SYSTEM_INDEX
    - ROVER_MOTION_COUNTER
    """
    kv: dict[str, str] = {}

    for line in lbl_text.splitlines():
        m = _RE_KEYVAL.match(line)
        if not m:
            continue

        key = m.group(1).upper()
        value = _clean_lbl_value(m.group(2))
        kv[key] = value

    # Prefer full-text tuple extraction because many LBL tuples span lines.
    ref_idx = _extract_tuple_from_lbl(lbl_text, "REFERENCE_COORD_SYSTEM_INDEX")
    motion = _extract_tuple_from_lbl(lbl_text, "ROVER_MOTION_COUNTER")
    if not ref_idx:
        ref_idx = _parse_tuple_value(kv.get("REFERENCE_COORD_SYSTEM_INDEX", ""))
    if not motion:
        motion = _parse_tuple_value(kv.get("ROVER_MOTION_COUNTER", ""))

    site = drive = pose = None

    # Prefer REFERENCE_COORD_SYSTEM_INDEX because it is directly intended
    # to describe the coordinate reference associated with the product.
    if len(ref_idx) >= 3:
        site = _to_int(ref_idx[0])
        drive = _to_int(ref_idx[1])
        pose = _to_int(ref_idx[2])

    # Fall back to ROVER_MOTION_COUNTER if needed.
    elif len(motion) >= 3:
        site = _to_int(motion[0])
        drive = _to_int(motion[1])
        pose = _to_int(motion[2])

    sclk_raw = _extract_scalar_from_lbl(lbl_text, "SPACECRAFT_CLOCK_START_COUNT") or kv.get("SPACECRAFT_CLOCK_START_COUNT")
    sclk = None
    if sclk_raw:
        sclk = _to_float(str(sclk_raw).replace('"', "").strip())

    parsed = {
        "product_id": kv.get("PRODUCT_ID"),
        "image_id": kv.get("IMAGE_ID"),
        "instrument_id": kv.get("INSTRUMENT_ID"),
        "instrument_name": kv.get("INSTRUMENT_NAME"),
        "sol": _to_int(kv.get("PLANET_DAY_NUMBER")),
        "site": site,
        "drive": drive,
        "pose": pose,
        "sclk": sclk,
        "start_time": kv.get("START_TIME"),
        "image_time": kv.get("IMAGE_TIME"),
        "reference_coord_system_index": [site, drive, pose] if site is not None else None,
        "rover_motion_counter": motion or None,
    }

    return {
        "raw": lbl_text,
        "fields": kv,
        "parsed": parsed,
    }

def build_product_from_lbl(
    lbl_text: str,
    img_url: str,
    lbl_url: str,
    base_url: Optional[str] = None,
) -> PdsProduct:
    """Builds a PdsProduct object from raw LBL text plus source URLs.

    This is the main constructor used after an LBL has been fetched and parsed.

    If PRODUCT_ID is missing, the IMG filename stem is used as a fallback.
    """
    lbl = parse_lbl_raw(lbl_text)["parsed"]

    return PdsProduct(
        product_id=lbl["product_id"] or Path(img_url).stem,
        image_id=lbl.get("image_id"),
        instrument_id=lbl.get("instrument_id"),
        instrument_name=lbl.get("instrument_name"),
        sol=lbl.get("sol"),
        site=lbl.get("site"),
        drive=lbl.get("drive"),
        pose=lbl.get("pose"),
        sclk=lbl.get("sclk"),
        start_time=lbl.get("start_time"),
        image_time=lbl.get("image_time"),
        img_url=img_url,
        lbl_url=lbl_url,
        base_url=base_url,
    )


# ============================================================
# Rover CSV loading and matching
# ============================================================

def load_rover_csv(csv_path: str | Path) -> list[dict[str, Any]]:
    """
    Loads the rover localisation CSV into a list of normalised dictionaries.

    Normalisation includes:
    - trimming strings
    - converting selected integer fields
    - converting sclk to float

    Fields currently normalised numerically:
    - site
    - drive
    - pose
    - sol
    - sclk
    """
    rows: list[dict[str, Any]] = []

    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            norm = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()}

            for key in ("site", "drive", "pose", "sol"):
                norm[key] = _to_int(norm.get(key))

            norm["sclk"] = _to_float(norm.get("sclk"))
            rows.append(norm)

    return rows


def _filter_rover_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Returns only rows whose frame is ROVER.

    The CSV may contain both SITE and ROVER rows.
    For image positioning, ROVER rows are the ones we want to prioritise.
    """
    return [r for r in rows if str(r.get("frame", "")).upper() == "ROVER"]


def match_rover_row(product: PdsProduct, rows: list[dict[str, Any]]) -> tuple[Optional[dict[str, Any]], MatchInfo]:
    """
    Matches a rover localisation row for a given product.

    Matching strategy priority:
    1. site + drive + pose
    2. site + drive + pose, narrowed by sol
    3. site + drive
    4. site + drive, narrowed by sol
    5. nearest sclk within same site + drive
    6. unique sol match

    Returns:
    - the matched CSV row, or None
    - a MatchInfo object describing the strategy used
    """
    rover_rows = _filter_rover_rows(rows)

    # --------------------------------------------------------
    # 1. Strongest match: site + drive + pose
    # --------------------------------------------------------
    strong = [
        r for r in rover_rows
        if r.get("site") == product.site
        and r.get("drive") == product.drive
        and r.get("pose") == product.pose
    ]

    if len(strong) == 1:
        return strong[0], MatchInfo(
            strategy="site_drive_pose",
            gps_found=True,
            csv_refreshed=False,
            csv_match_count=1,
            frame=strong[0].get("frame"),
        )

    if len(strong) > 1 and product.sol is not None:
        narrowed = [r for r in strong if r.get("sol") == product.sol]
        if len(narrowed) == 1:
            return narrowed[0], MatchInfo(
                strategy="site_drive_pose+sol",
                gps_found=True,
                csv_refreshed=False,
                csv_match_count=1,
                frame=narrowed[0].get("frame"),
            )

    # --------------------------------------------------------
    # 2. Fallback: site + drive
    # --------------------------------------------------------
    mid = [
        r for r in rover_rows
        if r.get("site") == product.site
        and r.get("drive") == product.drive
    ]

    if len(mid) == 1:
        return mid[0], MatchInfo(
            strategy="site_drive",
            gps_found=True,
            csv_refreshed=False,
            csv_match_count=1,
            frame=mid[0].get("frame"),
        )

    if len(mid) > 1 and product.sol is not None:
        narrowed = [r for r in mid if r.get("sol") == product.sol]
        if len(narrowed) == 1:
            return narrowed[0], MatchInfo(
                strategy="site_drive+sol",
                gps_found=True,
                csv_refreshed=False,
                csv_match_count=1,
                frame=narrowed[0].get("frame"),
            )

    # --------------------------------------------------------
    # 3. Fallback: nearest sclk within same site + drive
    # --------------------------------------------------------
    if product.sclk is not None and mid:
        with_sclk = [r for r in mid if r.get("sclk") is not None]
        if with_sclk:
            best = min(with_sclk, key=lambda r: abs(float(r["sclk"]) - float(product.sclk)))
            return best, MatchInfo(
                strategy="site_drive+sclk_nearest",
                gps_found=True,
                csv_refreshed=False,
                csv_match_count=len(with_sclk),
                frame=best.get("frame"),
            )

    # --------------------------------------------------------
    # 4. Weak fallback: unique sol match
    # --------------------------------------------------------
    if product.sol is not None:
        weak = [r for r in rover_rows if r.get("sol") == product.sol]
        if len(weak) == 1:
            return weak[0], MatchInfo(
                strategy="sol",
                gps_found=True,
                csv_refreshed=False,
                csv_match_count=1,
                frame=weak[0].get("frame"),
            )

    # --------------------------------------------------------
    # No match found
    # --------------------------------------------------------
    return None, MatchInfo(
        strategy="none",
        gps_found=False,
        csv_refreshed=False,
        csv_match_count=0,
        frame=None,
    )


# ============================================================
# meta.json helpers
# ============================================================

def _utc_now_iso() -> str:
    """
    Returns the current UTC timestamp in ISO 8601 format without microseconds.

    This is used for provenance metadata in the generated .meta.json.
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def derive_output_paths(output_dir: str | Path, product: PdsProduct) -> tuple[Path, Path]:
    """
    Derives the two canonical output paths for one processed product.

    Output contract:
    - product_id.jpg
    - product_id.meta.json
    """
    output_dir = Path(output_dir)
    product_id = product.product_id

    jpg_path = output_dir / f"{product_id}.jpg"
    meta_json_path = output_dir / f"{product_id}.meta.json"

    return jpg_path, meta_json_path


def build_meta_payload(
    *,
    product: PdsProduct,
    lbl_text: str,
    csv_row: Optional[dict[str, Any]],
    match_info: MatchInfo,
    img_url: str,
    lbl_url: str,
    rover_csv_url: str,
    rover_csv_local_path: str,
    output_jpg: str,
    output_meta_json: str,
    exif_written: Optional[dict[str, Any]] = None,
    warnings: Optional[list[str]] = None,
    errors: Optional[list[str]] = None,
    engine_version: str = "0.1.0",
) -> dict[str, Any]:
    """
    Builds the rich meta.json payload for one processed product.

    Fixed top-level contract:
    - product
    - sources
    - outputs
    - matching
    - csv_row
    - exif_written
    - lbl_parsed
    - lbl_fields
    - lbl_raw
    - provenance
    - warnings
    - errors
    """
    lbl_info = parse_lbl_raw(lbl_text)

    payload = {
        "product": {
            "product_id": product.product_id,
            "image_id": product.image_id,
            "instrument_id": product.instrument_id,
            "instrument_name": product.instrument_name,
            "sol": product.sol,
            "site": product.site,
            "drive": product.drive,
            "pose": product.pose,
            "sclk": product.sclk,
            "start_time": product.start_time,
            "image_time": product.image_time,
            "img_url": product.img_url,
            "lbl_url": product.lbl_url,
            "base_url": product.base_url,
        },
        "sources": {
            "base_url": product.base_url,
            "img_url": img_url,
            "lbl_url": lbl_url,
            "rover_csv_url": rover_csv_url,
            "rover_csv_local_path": rover_csv_local_path,
        },
        "outputs": {
            "jpg_path": output_jpg,
            "meta_json_path": output_meta_json,
        },
        "matching": {
            "strategy": match_info.strategy,
            "gps_found": match_info.gps_found,
            "csv_refreshed": match_info.csv_refreshed,
            "csv_match_count": match_info.csv_match_count,
            "frame": match_info.frame,
        },
        "csv_row": _make_json_safe(csv_row),
        "exif_written": _make_json_safe(exif_written or {}),
        "lbl_parsed": _make_json_safe(lbl_info["parsed"]),
        "lbl_fields": _make_json_safe(lbl_info["fields"]),
        "lbl_raw": lbl_info["raw"],
        "provenance": {
            "engine_version": engine_version,
            "built_at_utc": _utc_now_iso(),
        },
        "warnings": list(warnings or []),
        "errors": list(errors or []),
    }

    return payload


def write_meta_json(payload: dict[str, Any], output_path: str | Path) -> Path:
    """
    Writes the final meta.json payload to disk.

    The file is written with:
    - UTF-8 encoding
    - pretty indentation
    - stable key order disabled only where the original structure matters
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            _make_json_safe(payload),
            f,
            indent=2,
            ensure_ascii=False,
        )
        f.write("\n")

    return output_path
