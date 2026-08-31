#!/usr/bin/env python3
"""Audit: does the catalog builder's product filter agree with the downloader
app's live filter?

Two independent implementations decide "does this PDS product belong to
camera X per config/camera_rules.json":

- core/make_msl_catalog_pre3000.py::_record_is_allowed -- runs during catalog
  scanning/update/repair. Row-by-row. Always enforces a camera's PDS
  constraints unconditionally (that IS the decision of what enters the
  catalog).
- app/services/catalog_filter_service.py (compiled via catalog_rules_service)
  -- runs when a user browses/filters the already-built catalog in the
  downloader app. Vectorized (pandas) for UI responsiveness. Only enforces a
  camera's constraints when a matching boolean "filter_key" flag is present
  and True in the filters dict passed in -- an opt-in gate the builder side
  has no equivalent of.

Both read the same field names from the same config/camera_rules.json, so an
ordinary content edit (which suffixes/tokens are allowed) already reaches
both sides correctly. What this script actually checks:

1. For each camera with a PDS rule, and using the REAL installed
   Catalog_PDS.parquet: does _record_is_allowed's per-row decision agree
   with catalog_filter_service's decision, when the live filter's opt-in
   gate for that camera is forced on (i.e. "if the same rule were applied
   for real, would the two sides select the same set of rows")?
2. Whether the filter_key each compiled rule actually expects matches the
   flag names the chat command parser (local_command_handler_service.py)
   hardcodes and sets when a user selects that camera -- a mismatch here
   means the live filter's gate for that camera can never be turned on
   through the app's own chat interface, independently of whether the
   underlying constraint logic agrees.

Read-only: loads the real catalog and config, never writes anything.

Usage:
    python devtools/audit_camera_rules_consistency.py
    python devtools/audit_camera_rules_consistency.py --camera mahli --sample 5000
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
APP_DIR = ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import pandas as pd  # noqa: E402

from core.make_msl_catalog_pre3000 import _record_is_allowed  # noqa: E402
import catalog as app_catalog  # noqa: E402
from services.catalog_io_service import CatalogIOService  # noqa: E402

# The flag names the chat command parser actually sets when a user selects a
# camera (app/services/local_command_handler_service.py::_block_filters_from_text).
# Kept here as a literal snapshot to compare against, not imported, precisely
# because the point of this check is to catch it drifting out of sync with
# what's really in config/camera_rules.json.
PARSER_HARDCODED_FILTER_KEYS: dict[str, str] = {
    "mastcam": "mastcam_only_drcl",
    "mahli": "mahli_only_drcl",
    "mardi": "mardi_only_e01_drcx",
    "navcam": "navcam_only_iltlf",
    "hazcam": "hazcam_only_lb_edr",
}


def build_record(row: pd.Series) -> dict[str, Any]:
    """Minimal shape _record_is_allowed actually reads (see
    _record_matches_constraints): product_id, img_name, img_size_bytes.

    _record_is_allowed is written for plain dicts from the scanner (a
    missing size is a real Python None there); a pandas nullable column
    yields pd.NA instead, which blows up `size_value or ""` inside
    _record_matches_constraints (bool(pd.NA) is not defined). Normalize it
    here so this script measures a real disagreement, not a type mismatch
    of its own making.
    """
    img_size = row.get("img_size_bytes")
    if pd.isna(img_size):
        img_size = None
    return {
        "product_id": str(row.get("product_id") or ""),
        "img_name": str(row.get("_file_name") or ""),
        "img_size_bytes": img_size,
    }


def audit_camera(
    camera: str,
    df_cam: pd.DataFrame,
    rules_cfg: dict[str, Any],
    filter_service: Any,
    normalize_text: Any,
) -> dict[str, Any]:
    # 1) Builder side: one decision per row.
    builder_allowed = df_cam.apply(lambda row: _record_is_allowed(camera, build_record(row), rules_cfg)[0], axis=1)
    builder_ids = set(df_cam.loc[builder_allowed, "_row_id"])

    # 2) Live-filter side: force this camera's opt-in gate on, so the
    # comparison reflects "if the rule were actually applied", not "the
    # rule happens to be off by default".
    compiled = app_catalog.load_compiled_camera_rules()
    filter_key = ""
    for item in compiled.get("items", []):
        if item.get("camera_key") == camera:
            pds_source = item.get("sources", {}).get("pds") or {}
            filter_key = normalize_text(pds_source.get("filter_key"))
            break
    filters = {"cameras": [camera], "source_pds": True, "source_raw": False}
    if filter_key:
        filters[filter_key] = True

    filtered = filter_service.filter_dataframe(df_cam.copy(), filters)
    live_ids = set(filtered["_row_id"]) if "_row_id" in filtered.columns else set()

    only_in_builder = sorted(builder_ids - live_ids)
    only_in_live = sorted(live_ids - builder_ids)

    parser_key = PARSER_HARDCODED_FILTER_KEYS.get(camera, "")
    parser_key_matches = (not filter_key) or (parser_key == filter_key)

    return {
        "camera": camera,
        "rows_checked": len(df_cam),
        "builder_allowed": len(builder_ids),
        "live_allowed": len(live_ids),
        "only_in_builder": only_in_builder,
        "only_in_live": only_in_live,
        "agree": not only_in_builder and not only_in_live,
        "compiled_filter_key": filter_key,
        "parser_hardcoded_key": parser_key,
        "parser_key_matches_compiled": parser_key_matches,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--catalog", default=str(ROOT / "data" / "catalog" / "Catalog_PDS.parquet"))
    parser.add_argument("--camera", action="append", help="Limit to one or more cameras (repeatable). Default: all PDS-ruled cameras.")
    parser.add_argument("--sample", type=int, default=0, help="Row cap per camera for speed (0 = no cap, use the full catalog).")
    args = parser.parse_args()

    normalize_text = app_catalog.normalize_text
    rules_cfg = app_catalog.load_camera_rules()
    filter_service = app_catalog._get_catalog_filter_service()
    io_service = CatalogIOService()

    df = io_service.load_catalog(args.catalog)
    df = io_service.prepare_catalog_index(df)
    if "camera" not in df.columns:
        print("Il catalogo non ha una colonna 'camera'; niente da controllare.")
        return 1

    compiled = app_catalog.load_compiled_camera_rules()
    all_pds_cameras = sorted(
        item["camera_key"]
        for item in compiled.get("items", [])
        if isinstance(item.get("sources"), dict) and "pds" in item["sources"]
    )
    cameras = args.camera or all_pds_cameras

    print(f"Catalogo: {args.catalog}")
    print(f"Camere con regola PDS da controllare: {cameras}")
    print()

    any_mismatch = False
    for camera in cameras:
        cam_mask = df["camera"].fillna("").astype(str).str.lower() == camera
        df_cam = df.loc[cam_mask]
        if args.sample > 0 and len(df_cam) > args.sample:
            df_cam = df_cam.sample(n=args.sample, random_state=0)
        if df_cam.empty:
            print(f"[{camera}] nessuna riga nel catalogo, salto.")
            continue

        result = audit_camera(camera, df_cam, rules_cfg, filter_service, normalize_text)

        status = "OK" if result["agree"] and result["parser_key_matches_compiled"] else "DIVERGENZA"
        print(f"[{camera}] {status}")
        print(f"  righe controllate: {result['rows_checked']}")
        print(f"  ammessi dal builder (_record_is_allowed): {result['builder_allowed']}")
        print(f"  ammessi dal filtro live (catalog_filter_service, regola forzata attiva): {result['live_allowed']}")
        if result["only_in_builder"]:
            any_mismatch = True
            sample_ids = result["only_in_builder"][:5]
            print(f"  -> {len(result['only_in_builder'])} righe ammesse dal builder ma NON dal filtro live (es. _row_id={sample_ids})")
        if result["only_in_live"]:
            any_mismatch = True
            sample_ids = result["only_in_live"][:5]
            print(f"  -> {len(result['only_in_live'])} righe ammesse dal filtro live ma NON dal builder (es. _row_id={sample_ids})")
        print(f"  filter_key nella regola compilata: {result['compiled_filter_key'] or '(nessuno)'}")
        print(f"  filter_key che il parser chat imposta: {result['parser_hardcoded_key'] or '(nessuno)'}")
        if not result["parser_key_matches_compiled"]:
            any_mismatch = True
            print(
                "  -> DISALLINEATO: il parser chat imposta un flag diverso da quello che la regola compilata "
                "si aspetta -- selezionando questa camera in chat, il vincolo camera_rules.json lato app "
                "non scatta mai (il gate resta sempre spento)."
            )
        print()

    if any_mismatch:
        print("Risultato: trovate divergenze. Vedi dettagli sopra.")
        return 1
    print("Risultato: nessuna divergenza trovata tra builder e filtro live.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
