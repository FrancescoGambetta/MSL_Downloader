#!/usr/bin/env python3
"""Incrementally update the canonical MSL RAW Archive catalog.

CLI entry point for `catalog_manager/workers/raw_update_worker.py` and
`raw_repair_worker.py`. Fetches the RAW image manifest (the mars.nasa.gov
raw-images JSON API, not a PDS-style directory listing), scans each
requested Sol's `catalog_url` in a thread pool, and merges new/changed
products into the existing catalog by `img_url` -- unlike the PDS builder,
RAW products have no `.LBL` at all, so their metadata comes entirely from
the manifest JSON's own fields (no localization/geo enrichment).

`--repair-locations-file` mirrors `core/make_msl_catalog.py`'s repair mode:
skip the manifest fetch and requested Sol range entirely, and scan only the
exact Sol `catalog_url`s an integrity check already flagged as missing
products.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd
import requests

from catalog_manager.services import RAW_MANIFEST_URLS, _raw_camera


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALL_CAMERAS = ("mastcam", "mahli", "navcam", "hazcam", "mardi", "chemcam")

# Cooperative interruption flag, mirroring core/make_msl_catalog.py's
# STOP_EVENT. This builder previously had no way to stop mid-scan at all.
STOP_EVENT = threading.Event()


def first(item: dict[str, Any], *keys: str) -> Any:
    """Return the first non-empty value found in `item` among `keys` (the RAW manifest API uses inconsistent key naming across endpoints)."""
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return value
    return None


def get_json(urls: tuple[str, ...] | list[str], timeout: int, retries: int) -> tuple[dict[str, Any], str]:
    """Fetch and JSON-decode the first URL in `urls` that succeeds (retrying each with a short backoff), trying fallback URLs in order. Raises with every attempt's error if all fail."""
    errors: list[str] = []
    with requests.Session() as session:
        session.headers.update({"User-Agent": "MSL-Catalog-Manager/1.1"})
        for url in urls:
            for attempt in range(1, retries + 1):
                try:
                    response = session.get(url, timeout=timeout)
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict):
                        raise ValueError("JSON root is not an object")
                    return payload, response.url
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{url} attempt {attempt}: {type(exc).__name__}: {exc}")
                    if attempt < retries:
                        time.sleep(min(2 * attempt, 4))
    raise RuntimeError("; ".join(errors))


def raw_record(item: dict[str, Any], sol: int, catalog_url: str) -> tuple[str, dict[str, Any]] | None:
    """Build one canonical-schema RAW catalog row from a manifest `item`, or None if it's not a recognized camera or has no image URL."""
    camera = _raw_camera(item)
    if camera is None:
        return None
    img_url = str(first(item, "urlList", "url", "img_url") or "").strip()
    if not img_url:
        return None
    name = Path(urlparse(img_url).path).name
    product_id = Path(name).stem
    instrument = str(first(item, "instrument", "instrument_id") or camera.upper())
    image_time = first(item, "dateTaken", "imageTime", "image_time", "startTime", "start_time")
    sample_type = first(item, "sampleType", "sample_type")
    record = {
        "product_id": product_id, "sol": int(sol),
        "collection": "raw-images-web-manifest", "data_root": "image_manifest/catalog_url",
        "sol_dir_name": f"SOL{sol}", "sol_url": catalog_url, "img_url": img_url,
        "lbl_url": None, "img_name": name, "lbl_name": None, "img_size_bytes": None,
        "image_id": str(first(item, "imageid", "imageId", "image_id") or product_id),
        "instrument_id": instrument, "instrument_name": instrument,
        "start_time": image_time, "image_time": image_time,
        "site": first(item, "site"), "drive": first(item, "drive"), "pose": first(item, "pose"),
        "sclk": str(first(item, "sclk", "spacecraftClock") or ""),
        "sample_type": sample_type, "is_thumbnail": False,
        "geo_match_strategy": "not_available_raw_manifest_api", "geo_found": False,
        "geo_parse_error": "lbl_not_available", "record_complete": False,
        "geo_latitude": None, "geo_longitude": None, "geo_elevation": None, "geo_frame": None,
    }
    return camera, record


def load_catalog(path: Path) -> dict[str, Any]:
    """Load and sanity-check the existing RAW catalog JSON at `path` (must have a `cameras` dict)."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("cameras"), dict):
        raise ValueError(f"Invalid RAW catalog JSON: {path}")
    return payload


def canonical_frame(catalog: dict[str, Any], schema_path: Path) -> pd.DataFrame:
    """Flatten the nested `catalog["cameras"]` JSON into the canonical parquet DataFrame, cast to the schema's declared dtypes, sorted and de-duplicated by `img_url`."""
    rows: list[dict[str, Any]] = []
    for camera, section in catalog["cameras"].items():
        for product in section.get("products", []):
            row = dict(product); row["camera"] = camera; rows.append(row)
    frame = pd.DataFrame(rows)
    specs = json.loads(schema_path.read_text(encoding="utf-8"))["columns"]
    columns = [item["name"] for item in specs]
    for column in columns:
        if column not in frame:
            frame[column] = pd.NA
    frame = frame[columns]
    for item in specs:
        name, dtype = item["name"], item["dtype"]
        if dtype in {"bool", "boolean"}:
            values = frame[name].astype("boolean").fillna(False)
            frame[name] = values if dtype == "boolean" else values.astype(bool)
        elif dtype == "int64":
            frame[name] = pd.to_numeric(frame[name], errors="raise").astype("int64")
        elif dtype == "Float64":
            frame[name] = pd.to_numeric(frame[name], errors="coerce").astype("Float64")
        else:
            frame[name] = frame[name].astype("string")
    if frame.empty or frame["img_url"].isna().any() or frame["img_url"].duplicated().any():
        raise ValueError("RAW catalog has invalid canonical identities")
    return frame.sort_values(["camera", "sol", "product_id", "img_url"], kind="stable").reset_index(drop=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse this builder's CLI arguments (see the module docstring for `--repair-locations-file`'s special behavior)."""
    parser = argparse.ArgumentParser(description="Build/update the unified MSL RAW Archive catalog")
    parser.add_argument("--output", default=str(PROJECT_ROOT / "data/catalog/Catalog_RawArch.json"))
    parser.add_argument("--parquet-output", default=str(PROJECT_ROOT / "data/catalog/Catalog_RawArch.parquet"))
    parser.add_argument("--schema", default=str(PROJECT_ROOT / "config/raw_catalog_schema.json"))
    parser.add_argument("--cameras", nargs="+", choices=ALL_CAMERAS, default=list(ALL_CAMERAS))
    parser.add_argument("--sol-start", type=int, required=True)
    parser.add_argument("--sol-end", type=int, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--repair-locations-file", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Scan the requested Sol range (or repair locations) for each `--cameras` entry and merge new/updated products into the RAW catalog.

    Scans run concurrently in a thread pool (bounded by `--workers`, capped
    at 12); `STOP_EVENT` lets the caller (`raw_update_worker.py`/
    `raw_repair_worker.py`) interrupt cooperatively between Sols -- on
    cancellation, nothing is written (return code 2), so the installed
    catalog is never left half-updated. On success, writes JSON+parquet to
    `.incoming` siblings, re-reads the parquet to validate it, then
    atomically replaces both real files.
    """
    args = parse_args(argv)
    output = Path(args.output).expanduser().resolve()
    parquet = Path(args.parquet_output).expanduser().resolve()
    schema = Path(args.schema).expanduser().resolve()
    catalog = load_catalog(output)
    if args.validate_only:
        frame = canonical_frame(catalog, schema)
        print(f"[validated] rows={len(frame)} cameras={','.join(sorted(frame['camera'].unique()))}")
        return 0
    selected = set(args.cameras)
    by_url: dict[str, dict[str, dict[str, Any]]] = {}
    for camera, section in catalog["cameras"].items():
        by_url[camera] = {str(row["img_url"]): row for row in section.get("products", []) if row.get("img_url")}

    if args.repair_locations_file:
        # Repair mode: the caller (an integrity check's missing-products
        # list) already knows exactly which Sol catalog_urls need a fresh
        # look -- skip the manifest fetch and the full requested range
        # entirely, and scope selection to just the camera(s) being
        # repaired instead of --cameras (mirrors core/make_msl_catalog.py's
        # --repair-locations-file behaviour for the PDS builder).
        repair_locations = json.loads(Path(args.repair_locations_file).expanduser().resolve().read_text(encoding="utf-8"))
        selected = selected & set(repair_locations.keys())
        entries: dict[int, str] = {}
        for locations in repair_locations.values():
            for item in locations:
                sol_url = str(item.get("sol_url") or "")
                if sol_url:
                    entries[int(item["sol"])] = sol_url
        manifest_url = str(catalog.get("base_url") or "")
    else:
        if args.sol_end < args.sol_start:
            raise ValueError("--sol-end must be greater than or equal to --sol-start")
        manifest, manifest_url = get_json(tuple(RAW_MANIFEST_URLS), args.timeout, args.retries)
        entries = {
            int(item["sol"]): str(item.get("catalog_url") or "")
            for item in manifest.get("sols", []) if isinstance(item, dict) and item.get("sol") is not None
            and args.sol_start <= int(item["sol"]) <= args.sol_end and item.get("catalog_url")
        }

    def scan(sol: int, url: str) -> tuple[int, list[tuple[str, dict[str, Any]]]]:
        payload, resolved = get_json((url,), args.timeout, args.retries)
        records = []
        for item in payload.get("images", []):
            if isinstance(item, dict) and (parsed := raw_record(item, sol, resolved)) is not None and parsed[0] in selected:
                records.append(parsed)
        return sol, records

    additions = {camera: 0 for camera in selected}
    cancelled = False
    with ThreadPoolExecutor(max_workers=max(1, min(int(args.workers), 12))) as executor:
        futures = [executor.submit(scan, sol, url) for sol, url in entries.items()]
        for index, future in enumerate(as_completed(futures), start=1):
            sol, records = future.result()
            for camera, record in records:
                target = by_url.setdefault(camera, {})
                if record["img_url"] not in target:
                    additions[camera] += 1
                target[record["img_url"]] = record
            print(f"[raw_sol] {index}/{len(futures)} sol={sol} products={len(records)}", flush=True)
            if STOP_EVENT.is_set():
                cancelled = True
                for pending in futures:
                    pending.cancel()
                break

    if cancelled:
        # Never write a partial RAW catalog: the caller must treat this as
        # "no update happened" and leave the installed catalog untouched.
        print("[stop] interruzione richiesta: aggiornamento RAW annullato", flush=True)
        return 2

    for camera, products in by_url.items():
        ordered = sorted(products.values(), key=lambda row: (int(row["sol"]), str(row["product_id"])))
        catalog["cameras"][camera] = {"product_count": len(ordered), "products": ordered}
    catalog["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    catalog["base_url"] = manifest_url
    frame = canonical_frame(catalog, schema)
    incoming_json = output.with_suffix(output.suffix + ".incoming")
    incoming_parquet = parquet.with_suffix(parquet.suffix + ".incoming")
    incoming_json.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    frame.to_parquet(incoming_parquet, index=False)
    check = pd.read_parquet(incoming_parquet)
    if len(check) != len(frame) or check["img_url"].duplicated().any():
        raise RuntimeError("RAW post-write validation failed")
    os.replace(incoming_json, output); os.replace(incoming_parquet, parquet)
    print(f"[done] rows={len(frame)} additions={additions}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
