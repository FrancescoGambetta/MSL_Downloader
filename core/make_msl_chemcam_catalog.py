#!/usr/bin/env python3
"""Discovery and construction of the ChemCam RMI RDR PDS catalog.

Identifies RMI PRC images in TIF format and their PDS label, enriches them
from the PDS labels, and writes the ChemCam JSON/Parquet catalog (with
incremental per-Sol checkpoints), which `make_msl_pds_catalog.py` then merges
into the application's unified PDS catalog.

Honours `STOP_EVENT` (from `core.make_msl_catalog`) cooperatively, checked once
per Sol before that Sol's own scan starts -- same granularity and the same
shared event the standard-camera scanner already uses, so a cancel request
from `catalog_manager`'s UI (which just sets this event from a watcher thread)
stops a ChemCam update within about one Sol's worth of work instead of running
to completion regardless. Whatever was already scanned this run is still
checkpointed before returning, same as a normal finish.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import pandas as pd

try:
    from core.make_msl_catalog import (
        STOP_EVENT,
        PDSClient,
        _extract_links_with_sizes,
        _is_under_base,
        _load_json,
        _normalise_url,
        _parse_sol_dir_name,
        _write_json,
    )
    from core.metashape_engine import build_product_from_lbl
except Exception:  # pragma: no cover - direct execution from the core folder
    from make_msl_catalog import (  # type: ignore
        STOP_EVENT,
        PDSClient,
        _extract_links_with_sizes,
        _is_under_base,
        _load_json,
        _normalise_url,
        _parse_sol_dir_name,
        _write_json,
    )
    from metashape_engine import build_product_from_lbl  # type: ignore


CHEMCAM_RDR_DATA_URL = (
    "https://pds-geosciences.wustl.edu/msl/"
    "msl-m-chemcam-libs-4_5-rdr-v1/mslccm_1xxx/data/"
)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JSON_OUTPUT = PROJECT_ROOT / "data" / "catalog" / "chemcam_catalog.json"
DEFAULT_PARQUET_OUTPUT = PROJECT_ROOT / "data" / "catalog" / "chemcam_catalog.parquet"


def discover_sol_urls(client: PDSClient, data_url: str) -> dict[int, str]:
    """Return the sol -> Sol-directory-URL map for every Sol directory available under `data_url`."""
    html = client.get_text(data_url)
    sols: dict[int, str] = {}
    for entry in _extract_links_with_sizes(html):
        href = str(entry.get("href", "")).strip()
        sol_dir_name = Path(urlparse(href).path.rstrip("/")).name
        sol = _parse_sol_dir_name(sol_dir_name)
        if sol is None:
            continue
        sol_url = _normalise_url(urljoin(data_url, f"{href.rstrip('/')}/"))
        if _is_under_base(sol_url, data_url):
            sols[sol] = sol_url
    return sols


def discover_rmi_products(client: PDSClient, sol: int, sol_url: str) -> list[dict[str, Any]]:
    """Find only ChemCam RMI PRC TIF+LBL product pairs in `sol_url`'s directory listing (skips LIBS and other non-RMI-PRC filenames)."""
    html = client.get_text(sol_url)
    entries = _extract_links_with_sizes(html)
    names = {
        Path(str(entry.get("href", ""))).name.lower()
        for entry in entries
        if str(entry.get("href", "")).strip()
    }

    products: list[dict[str, Any]] = []
    for entry in entries:
        href = str(entry.get("href", "")).strip()
        filename = Path(href).name
        lower = filename.lower()

        # RMI RDR: cr0_<sclk>prc_...tif. Other prefixes are LIBS products.
        if not lower.startswith("cr0_") or "prc_" not in lower or not lower.endswith(".tif"):
            continue

        stem = Path(filename).stem
        lbl_name = f"{stem}.lbl"
        if lbl_name.lower() not in names:
            continue

        tif_url = _normalise_url(urljoin(sol_url, filename))
        lbl_url = _normalise_url(urljoin(sol_url, lbl_name))
        if not _is_under_base(tif_url, CHEMCAM_RDR_DATA_URL):
            continue

        products.append(
            {
                "product_id": stem,
                "sol": sol,
                "camera": "chemcam",
                "instrument_id": "CHEMCAM_RMI",
                "processing_level": "RDR_PRC",
                "image_format": "TIFF",
                # Aliases kept compatible with the PDS catalog and the existing pipeline.
                "img_url": tif_url,
                "tif_url": tif_url,
                "lbl_url": lbl_url,
                "img_name": filename,
                "tif_name": filename,
                "lbl_name": lbl_name,
                "img_size_bytes": entry.get("size_bytes"),
                "tif_size_bytes": entry.get("size_bytes"),
                "sol_url": sol_url,
                "image_id": None,
                "instrument_name": "CHEMISTRY CAMERA REMOTE MICRO-IMAGER",
                "start_time": None,
                "image_time": None,
                "site": None,
                "drive": None,
                "pose": None,
                "sclk": None,
                "lbl_parse_error": None,
            }
        )
    return products


def enrich_from_labels(client: PDSClient, products: list[dict[str, Any]]) -> None:
    """Fetch and parse each product's `.LBL` in place, filling in the fields shared with the standard MSL catalog schema (or recording `lbl_parse_error` on failure)."""
    for product in products:
        try:
            lbl_text = client.get_text(str(product["lbl_url"]))
            parsed = build_product_from_lbl(
                lbl_text=lbl_text,
                img_url=str(product["img_url"]),
                lbl_url=str(product["lbl_url"]),
                base_url=str(product["sol_url"]),
            )
            product["image_id"] = parsed.image_id
            product["instrument_id"] = parsed.instrument_id or "CHEMCAM_RMI"
            product["instrument_name"] = parsed.instrument_name or product["instrument_name"]
            product["start_time"] = parsed.start_time
            product["image_time"] = parsed.image_time
            product["site"] = parsed.site
            product["drive"] = parsed.drive
            product["pose"] = parsed.pose
            # The canonical schema (config/pds_catalog_schema.json) declares
            # sclk as a string; parsed.sclk is a float. Keep it a string here
            # too, otherwise merging with the standard-camera sections (which
            # already store sclk as text) gives PyArrow a mixed str/float
            # column it can't infer a single type for.
            product["sclk"] = str(parsed.sclk) if parsed.sclk is not None else None
        except Exception as exc:  # noqa: BLE001
            product["lbl_parse_error"] = f"{type(exc).__name__}: {exc}"


def build_catalog(products: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap `products` in the standard single-camera ("chemcam") catalog JSON envelope."""
    return {
        "catalog_version": 2,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mission": "MSL",
        "base_url": CHEMCAM_RDR_DATA_URL,
        "catalog_kind": "chemcam_rmi_rdr",
        "cameras": {
            "chemcam": {
                "product_count": len(products),
                "products": products,
            }
        },
    }


def write_parquet(products: list[dict[str, Any]], output: Path) -> None:
    """Write `products` to `output` as parquet."""
    output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(products).to_parquet(output, index=False)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse this builder's CLI arguments."""
    parser = argparse.ArgumentParser(description="Discover PDS ChemCam RMI RDR products")
    parser.add_argument("--sol-start", type=int, default=0)
    parser.add_argument("--sol-end", type=int, default=None)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--output", default=str(DEFAULT_JSON_OUTPUT))
    parser.add_argument("--parquet-output", default=str(DEFAULT_PARQUET_OUTPUT))
    parser.add_argument("--checkpoint-every-sols", type=int, default=25)
    parser.add_argument(
        "--refresh-scanned-sols",
        action="store_true",
        help="Also rescan Sols already recorded in the state file",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Discover, enrich, and checkpoint ChemCam RMI PRC products for every not-yet-scanned Sol in `--sol-start`..`--sol-end`.

    Prompts interactively for `--sol-end` if not given on the command line
    (this is `catalog_manager/workers/customization_worker.py`'s hard stop for
    ChemCam customization -- see its `ValueError` when `camera == "chemcam"`
    -- so this script is only ever invoked standalone, never from a
    worker without `--sol-end`).
    """
    args = parse_args(argv)
    if args.sol_end is None:
        args.sol_end = int(input("Final ChemCam Sol to index: ").strip())
    if args.sol_end < args.sol_start:
        raise SystemExit("--sol-end must be greater than or equal to --sol-start")

    client = PDSClient(timeout=args.timeout, retries=args.retries)
    sol_urls = discover_sol_urls(client, CHEMCAM_RDR_DATA_URL)
    requested = range(args.sol_start, args.sol_end + 1)

    output = Path(args.output).expanduser().resolve()
    parquet_output = Path(args.parquet_output).expanduser().resolve()
    state_output = output.with_suffix(output.suffix + ".state.json")

    existing_catalog = _load_json(output, {})
    existing_products: list[dict[str, Any]] = []
    if isinstance(existing_catalog, dict):
        cameras = existing_catalog.get("cameras", {})
        if isinstance(cameras, dict):
            chemcam = cameras.get("chemcam", {})
            if isinstance(chemcam, dict) and isinstance(chemcam.get("products"), list):
                existing_products = list(chemcam["products"])

    products_by_url = {
        str(product.get("img_url") or product.get("tif_url")): product
        for product in existing_products
        if product.get("img_url") or product.get("tif_url")
    }
    state = _load_json(state_output, {})
    scanned_sols = {
        int(sol)
        for sol in (state.get("scanned_sols", []) if isinstance(state, dict) else [])
    }
    if args.refresh_scanned_sols:
        scanned_sols.clear()

    def checkpoint(reason: str) -> None:
        saved_products = sorted(
            products_by_url.values(),
            key=lambda item: (int(item["sol"]), str(item["product_id"])),
        )
        _write_json(output, build_catalog(saved_products))
        write_parquet(saved_products, parquet_output)
        _write_json(
            state_output,
            {
                "base_url": CHEMCAM_RDR_DATA_URL,
                "scanned_sols": sorted(scanned_sols),
                "saved_at_utc": datetime.now(timezone.utc).isoformat(),
                "reason": reason,
            },
        )
        print(
            f"[checkpoint] reason={reason} | products={len(saved_products)} "
            f"| scanned_sols={len(scanned_sols)}"
        )

    scanned_now = 0
    added_now = 0
    interrupted = False
    for sol in requested:
        if STOP_EVENT.is_set():
            interrupted = True
            break
        if sol in scanned_sols:
            continue
        sol_url = sol_urls.get(sol)
        if sol_url is None:
            print(f"[chemcam_sol_missing] sol={sol}")
            scanned_sols.add(sol)
            scanned_now += 1
            if args.checkpoint_every_sols > 0 and scanned_now % args.checkpoint_every_sols == 0:
                checkpoint(f"every_{args.checkpoint_every_sols}_sols")
            continue
        products = discover_rmi_products(client, sol, sol_url)
        enrich_from_labels(client, products)
        print(f"[chemcam_sol] sol={sol} | rmi_products={len(products)}")
        for product in products:
            print(f"[chemcam_product] {product['product_id']} | {product['tif_url']}")
            key = str(product["img_url"])
            if key not in products_by_url:
                added_now += 1
            products_by_url[key] = product
        scanned_sols.add(sol)
        scanned_now += 1
        if args.checkpoint_every_sols > 0 and scanned_now % args.checkpoint_every_sols == 0:
            checkpoint(f"every_{args.checkpoint_every_sols}_sols")

    checkpoint("interrupted" if interrupted else "final")
    print(f"[done] rmi_products={len(products_by_url)}")
    print(f"[done] new_products={added_now}")
    print(f"[done] sols_scanned_now={scanned_now}")
    print(f"[done] json={output}")
    print(f"[done] parquet={parquet_output}")
    print(f"[done] state={state_output}")
    return 2 if interrupted else 0


if __name__ == "__main__":
    raise SystemExit(main())
