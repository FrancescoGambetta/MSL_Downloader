#!/usr/bin/env python3
"""Build an incremental MSL Raw Archive catalog for ChemCam PRC images.

Standalone CLI tool, run manually (not invoked by `catalog_manager/`'s
workers -- those cover ChemCam RAW through the unified
`make_msl_raw_catalog.py` builder instead). Scans the RAW manifest API for
ChemCam PRC (processed RMI quicklook) products only, checkpointing progress
to a `.state.json` sidecar every `--checkpoint-every-sols` Sols so a long
scan can resume where it left off. Prompts interactively for `--sol-end` if
not passed on the command line.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd
import requests


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JSON_OUTPUT = PROJECT_ROOT / "data" / "catalog" / "chemcam_raw_catalog.json"
DEFAULT_PARQUET_OUTPUT = PROJECT_ROOT / "data" / "catalog" / "chemcam_raw_catalog.parquet"
MANIFEST_URLS = (
    "https://mars.jpl.nasa.gov/msl-raw-images/image/image_manifest.json",
    "http://mars.jpl.nasa.gov/msl-raw-images/image/image_manifest.json",
)


def load_json(path: Path, default: Any) -> Any:
    """Load and parse `path`, or return `default` if it's missing/invalid."""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    """Write `payload` to `path` atomically (temp file + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def request_json(session: requests.Session, urls: list[str] | tuple[str, ...], timeout: int, retries: int) -> tuple[dict[str, Any], str]:
    """Fetch and JSON-decode the first `urls` entry that succeeds, retrying each with a short backoff. Raises with every attempt's error if all fail."""
    errors: list[str] = []
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


def first_text(item: dict[str, Any], *keys: str) -> str:
    """Return the first non-empty stripped string value found among `keys`, or ""."""
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def chemcam_record(item: dict[str, Any], sol: int, catalog_url: str) -> dict[str, Any] | None:
    """Build a canonical RAW ChemCam PRC record from a manifest `item`, or None if it's not a ChemCam PRC product."""
    instrument = first_text(item, "instrument", "instrument_id")
    sample_type = first_text(item, "sampleType", "sample_type")
    img_url = first_text(item, "urlList", "url", "img_url")
    if "CHEMCAM" not in instrument.upper():
        return None
    if sample_type.casefold() != "chemcam prc":
        return None
    if not img_url:
        return None

    img_name = Path(urlparse(img_url).path).name
    product_id = Path(img_name).stem
    image_time = first_text(item, "dateTaken", "imageTime", "image_time", "startTime", "start_time")
    return {
        "product_id": product_id,
        "sol": sol,
        "collection": "raw-images-web-manifest",
        "data_root": "image_manifest/catalog_url",
        "sol_dir_name": f"SOL{sol}",
        "sol_url": catalog_url,
        "img_url": img_url,
        "lbl_url": None,
        "img_name": img_name,
        "lbl_name": None,
        "img_size_bytes": None,
        "image_id": product_id,
        "instrument_id": instrument,
        "instrument_name": instrument,
        "start_time": image_time or None,
        "image_time": image_time or None,
        "site": None,
        "drive": None,
        "pose": None,
        "sclk": "",
        "sample_type": sample_type,
        "is_thumbnail": False,
        "geo_match_strategy": "not_available_raw_manifest_api",
        "geo_found": False,
        "geo_parse_error": "lbl_not_available",
        "record_complete": False,
        "geo_latitude": None,
        "geo_longitude": None,
        "geo_elevation": None,
        "geo_frame": None,
        "camera": "chemcam",
    }


def build_catalog(products: list[dict[str, Any]], manifest_url: str) -> dict[str, Any]:
    """Wrap `products` in the standard single-camera ("chemcam") catalog JSON envelope."""
    return {
        "catalog_version": 2,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mission": "MSL",
        "base_url": manifest_url,
        "catalog_kind": "chemcam_raw_archive_prc",
        "cameras": {"chemcam": {"product_count": len(products), "products": products}},
    }


def write_parquet(products: list[dict[str, Any]], path: Path) -> None:
    """Write `products` to `path` as parquet (not atomic -- see the module docstring's checkpoint note; this is a low-volume standalone tool, unlike the main builders)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(products).to_parquet(path, index=False)


def parse_args() -> argparse.Namespace:
    """Parse this tool's CLI arguments."""
    parser = argparse.ArgumentParser(description="Build/update the MSL ChemCam Raw Archive catalog")
    parser.add_argument("--sol-start", type=int, default=0)
    parser.add_argument("--sol-end", type=int, default=None)
    parser.add_argument("--output", default=str(DEFAULT_JSON_OUTPUT))
    parser.add_argument("--parquet-output", default=str(DEFAULT_PARQUET_OUTPUT))
    parser.add_argument("--checkpoint-every-sols", type=int, default=25)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--refresh-scanned-sols", action="store_true")
    return parser.parse_args()


def main() -> int:
    """Scan every not-yet-scanned Sol in range for ChemCam PRC products, checkpointing periodically, and write the final catalog+state."""
    args = parse_args()
    if args.sol_end is None:
        args.sol_end = int(input("Final ChemCam RAW Sol to index: ").strip())
    if args.sol_end < args.sol_start:
        raise SystemExit("--sol-end deve essere maggiore o uguale a --sol-start")

    output = Path(args.output).expanduser().resolve()
    parquet_output = Path(args.parquet_output).expanduser().resolve()
    state_output = output.with_suffix(output.suffix + ".state.json")
    session = requests.Session()
    session.headers.update({"User-Agent": "dwnapp-chemcam-raw-catalog/1.0"})

    manifest, manifest_url = request_json(session, MANIFEST_URLS, args.timeout, args.retries)
    sol_entries: dict[int, dict[str, Any]] = {}
    for entry in manifest.get("sols", []):
        try:
            sol = int(entry.get("sol"))
        except (TypeError, ValueError):
            continue
        if args.sol_start <= sol <= args.sol_end:
            sol_entries[sol] = entry

    existing = load_json(output, {})
    old_products = (
        existing.get("cameras", {}).get("chemcam", {}).get("products", [])
        if isinstance(existing, dict)
        else []
    )
    products_by_url = {
        str(product.get("img_url")): product
        for product in old_products
        if isinstance(product, dict) and product.get("img_url")
    }
    state = load_json(state_output, {})
    scanned_sols = {int(sol) for sol in state.get("scanned_sols", [])} if isinstance(state, dict) else set()
    if args.refresh_scanned_sols:
        scanned_sols.clear()

    def checkpoint(reason: str) -> None:
        products = sorted(products_by_url.values(), key=lambda row: (int(row["sol"]), str(row["product_id"])))
        write_json(output, build_catalog(products, manifest_url))
        write_parquet(products, parquet_output)
        write_json(
            state_output,
            {
                "manifest_url": manifest_url,
                "scanned_sols": sorted(scanned_sols),
                "saved_at_utc": datetime.now(timezone.utc).isoformat(),
                "reason": reason,
            },
        )
        print(f"[checkpoint] reason={reason} | products={len(products)} | scanned_sols={len(scanned_sols)}")

    scanned_now = 0
    added_now = 0
    for sol in sorted(sol_entries):
        if sol in scanned_sols:
            continue
        catalog_url = first_text(sol_entries[sol], "catalog_url")
        found: list[dict[str, Any]] = []
        if catalog_url:
            payload, resolved_url = request_json(session, (catalog_url,), args.timeout, args.retries)
            for item in payload.get("images", []):
                if not isinstance(item, dict):
                    continue
                record = chemcam_record(item, sol, resolved_url)
                if record is not None:
                    found.append(record)
                    if record["img_url"] not in products_by_url:
                        added_now += 1
                    products_by_url[record["img_url"]] = record
        scanned_sols.add(sol)
        scanned_now += 1
        print(f"[chemcam_raw_sol] sol={sol} | products={len(found)}")
        if args.checkpoint_every_sols > 0 and scanned_now % args.checkpoint_every_sols == 0:
            checkpoint(f"every_{args.checkpoint_every_sols}_sols")

    checkpoint("final")
    print(f"[done] products={len(products_by_url)}")
    print(f"[done] new_products={added_now}")
    print(f"[done] sols_scanned_now={scanned_now}")
    print(f"[done] json={output}")
    print(f"[done] parquet={parquet_output}")
    print(f"[done] state={state_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
