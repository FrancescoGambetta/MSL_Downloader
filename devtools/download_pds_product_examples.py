#!/usr/bin/env python3
"""Scarica una piccola anteprima per ogni combinazione di prodotto PDS censita.

Lo script usa il censimento JSON come elenco delle combinazioni, visita le
directory NASA del range richiesto e sceglie un prodotto casuale per ciascuna
combinazione. I file scientifici originali sono scaricati solo temporaneamente;
in output restano JPEG leggeri e un manifest utilizzabile dalla UI.

Esempio:
    python devtools/download_pds_product_examples.py --sol-start 3347 --sol-end 3351

Test rapido:
    python devtools/download_pds_product_examples.py --max-combinations 3
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from devtools.census_nasa_pds_products import (  # noqa: E402
    ALL_CAMERAS,
    IMAGE_EXTENSIONS,
    HttpClient,
    _hrefs,
    _locations,
    _structural_fields,
)
from devtools.tools.DecodeIMGFromUrl import (  # noqa: E402
    _read_band_sequential,
    _to_png,
    parse_lbl,
)

DEFAULT_CENSUS = PROJECT_ROOT / "analysis_output" / "pds_product_census_test" / "pds_product_census.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "analysis_output" / "pds_product_examples"


def _key_from_row(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("camera", "")).lower(),
        str(row.get("camera_prefix", "")).upper(),
        str(row.get("descriptor_or_tokens", "")).upper(),
        str(row.get("processing_suffix", "")).upper(),
        str(row.get("extension", "")).upper(),
    )


def _key_from_product(camera: str, product_id: str, extension: str) -> tuple[str, str, str, str, str]:
    fields = _structural_fields(camera, product_id)
    return (
        camera.lower(),
        str(fields.get("camera_prefix", "")).upper(),
        str(fields.get("descriptor") or fields.get("product_code") or fields.get("underscore_tokens", "")).upper(),
        str(fields.get("processing_suffix", "")).upper(),
        extension.upper().lstrip("."),
    )


def _download(url: str, destination: Path, timeout: int, retries: int = 3) -> None:
    last_error: Exception | None = None
    for attempt in range(max(1, retries)):
        request = Request(url, headers={"User-Agent": "MSL-PDS-example-builder/1.0"})
        try:
            with urlopen(request, timeout=timeout) as response, destination.open("wb") as handle:  # noqa: S310
                shutil.copyfileobj(response, handle, length=1024 * 256)
            return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt + 1 < max(1, retries):
                time.sleep(min(8.0, 1.5 * (2**attempt)))
    assert last_error is not None
    raise last_error


def _img_to_png(img_path: Path, lbl_path: Path, png_path: Path) -> None:
    meta = parse_lbl(str(lbl_path))
    if str(meta.get("storage", "")).strip().upper() != "BAND_SEQUENTIAL":
        raise ValueError(f"BAND_STORAGE_TYPE non supportato: {meta.get('storage')}")
    bands = _read_band_sequential(str(img_path), meta)
    _to_png(png_path, int(meta["lines"]), int(meta["samples"]), int(meta["bands"]), bands)


def _make_preview(source: Path, destination: Path, max_side: int, quality: int) -> None:
    with Image.open(source) as image:
        image.load()
        if image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        if image.mode == "L":
            image = image.convert("RGB")
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination, "JPEG", quality=quality, optimize=True)


def _safe_name(key: tuple[str, str, str, str, str], product_id: str) -> str:
    readable = "_".join(part for part in key[1:4] if part)[:90].strip("_") or "product"
    digest = hashlib.sha1("|".join(key).encode("utf-8")).hexdigest()[:10]  # noqa: S324
    return f"{readable}_{digest}_{product_id[:24]}.jpg".replace("|", "-")


def _scan_location(
    client: HttpClient,
    location: tuple[str, int, str],
    targets: set[tuple[str, str, str, str, str]],
    example_to_key: dict[str, tuple[str, str, str, str, str]],
) -> list[dict[str, Any]]:
    camera, sol, directory_url = location
    found: list[dict[str, Any]] = []
    html = client.get_text(directory_url)
    for href in _hrefs(html):
        if not href or href.endswith("/"):
            continue
        path = Path(href)
        extension = path.suffix.upper()
        if extension not in IMAGE_EXTENSIONS:
            continue
        key = example_to_key.get(path.stem.upper()) or _key_from_product(camera, path.stem, extension)
        if key in targets:
            found.append(
                {
                    "key": key,
                    "camera": camera,
                    "sol": sol,
                    "product_id": path.stem,
                    "extension": extension.lstrip("."),
                    "source_url": urljoin(directory_url, href),
                    "label_url": urljoin(directory_url, path.stem + ".LBL"),
                }
            )
    return found


def _build_one(
    candidate: dict[str, Any],
    output_dir: Path,
    timeout: int,
    max_side: int,
    quality: int,
    retries: int = 3,
    force: bool = False,
) -> dict[str, Any]:
    key = tuple(candidate["key"])
    filename = _safe_name(key, str(candidate["product_id"]))
    relative = Path(str(candidate["camera"])) / filename
    preview_path = output_dir / relative
    result = {k: v for k, v in candidate.items() if k != "key"}
    result.update({"combination": list(key), "preview": relative.as_posix(), "status": "pending"})
    if not force and preview_path.exists() and preview_path.stat().st_size > 0:
        result["status"] = "existing"
        return result
    try:
        with tempfile.TemporaryDirectory(prefix="msl_product_example_") as temporary:
            tmp = Path(temporary)
            extension = str(candidate["extension"]).upper()
            scientific = tmp / f"source.{extension.lower()}"
            _download(str(candidate["source_url"]), scientific, timeout, retries)
            display_source = scientific
            if extension == "IMG":
                label = tmp / "source.lbl"
                _download(str(candidate["label_url"]), label, timeout, retries)
                display_source = tmp / "decoded.png"
                _img_to_png(scientific, label, display_source)
            _make_preview(display_source, preview_path, max_side, quality)
        result["status"] = "ok"
        result["bytes"] = preview_path.stat().st_size
    except Exception as exc:  # noqa: BLE001
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--census", type=Path, default=DEFAULT_CENSUS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cameras", nargs="+", choices=ALL_CAMERAS, default=list(ALL_CAMERAS))
    parser.add_argument("--sol-start", type=int, help="Sol preferito iniziale; predefinito dal censimento")
    parser.add_argument("--sol-end", type=int, help="Sol preferito finale; predefinito dal censimento")
    parser.add_argument("--seed", type=int, default=42, help="Seed della scelta casuale, per risultati ripetibili")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--max-side", type=int, default=1200)
    parser.add_argument("--jpeg-quality", type=int, default=82)
    parser.add_argument("--max-combinations", type=int, default=0, help="Limite utile per test; 0 = tutte")
    parser.add_argument(
        "--retry-errors",
        action="store_true",
        help="Ritenta solo gli errori registrati nel manifest di output, senza una nuova scansione NASA",
    )
    return parser.parse_args()


def _retry_manifest_errors(args: argparse.Namespace, output_dir: Path) -> int:
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"Manifest non trovato: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    previous = list(payload.get("examples", []))
    failures = [item for item in previous if item.get("status") == "error"]
    if args.max_combinations > 0:
        failures = failures[: args.max_combinations]
    if not failures:
        print("Nessuna conversione fallita da ritentare.")
        return 0

    candidates: list[dict[str, Any]] = []
    for item in failures:
        candidate = {key: value for key, value in item.items() if key not in {"status", "error", "bytes", "preview"}}
        candidate["key"] = tuple(item["combination"])
        candidates.append(candidate)

    print(f"Conversioni da ritentare: {len(candidates)}", flush=True)
    started = time.monotonic()
    replacements: dict[tuple[str, str], dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = [
            executor.submit(
                _build_one,
                candidate,
                output_dir,
                args.timeout,
                args.max_side,
                args.jpeg_quality,
                args.retries,
            )
            for candidate in candidates
        ]
        for index, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            replacements[(str(result["camera"]), str(result["product_id"]))] = result
            print(f"[{index}/{len(futures)}] {result['camera']} {result['product_id']}: {result['status']}", flush=True)

    merged = [replacements.get((str(item["camera"]), str(item["product_id"])), item) for item in previous]
    payload["examples"] = sorted(merged, key=lambda item: (item["camera"], item["product_id"]))
    summary = payload.setdefault("summary", {})
    summary["previews_ready"] = sum(item.get("status") in {"ok", "existing"} for item in merged)
    summary["conversion_errors"] = sum(item.get("status") == "error" for item in merged)
    summary["elapsed_seconds"] = round(time.monotonic() - started, 3)
    payload["generated_at_unix"] = time.time()
    temporary_path = manifest_path.with_suffix(".json.tmp")
    temporary_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary_path.replace(manifest_path)
    print(f"Manifest aggiornato: {manifest_path}", flush=True)
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
    return 0 if summary["conversion_errors"] == 0 else 2


def main() -> int:
    args = parse_args()
    census_path = args.census.resolve()
    output_dir = args.output_dir.resolve()
    if args.retry_errors:
        return _retry_manifest_errors(args, output_dir)
    census = json.loads(census_path.read_text(encoding="utf-8"))
    cameras = {str(camera).lower() for camera in args.cameras}
    rows = [row for row in census.get("combinations", []) if str(row.get("camera", "")).lower() in cameras]
    if args.max_combinations > 0:
        rows = rows[: args.max_combinations]
    targets = {_key_from_row(row) for row in rows}
    if not targets:
        raise SystemExit("Nessuna combinazione da elaborare.")
    active_cameras = {key[0] for key in targets}
    example_to_key: dict[str, tuple[str, str, str, str, str]] = {}
    for row in rows:
        row_key = _key_from_row(row)
        for product_id in row.get("examples", []):
            example_to_key[str(product_id).upper()] = row_key

    ranges = census.get("sol_ranges", {})
    known_mins = [int(value["min"]) for camera, value in ranges.items() if camera in active_cameras and value.get("min") is not None]
    known_maxs = [int(value["max"]) for camera, value in ranges.items() if camera in active_cameras and value.get("max") is not None]
    sol_start = args.sol_start if args.sol_start is not None else min(known_mins)
    sol_end = args.sol_end if args.sol_end is not None else max(known_maxs)
    if sol_start > sol_end:
        raise SystemExit("--sol-start non può essere maggiore di --sol-end")

    config = json.loads((PROJECT_ROOT / "config" / "msl_catalog_config.json").read_text(encoding="utf-8"))
    client = HttpClient(timeout=args.timeout, retries=args.retries)
    print(f"Combinazioni richieste: {len(targets)}", flush=True)
    print(f"Ricerca NASA: Sol {sol_start}-{sol_end}", flush=True)
    locations = _locations(client, config, sorted(active_cameras), sol_start, sol_end, args.workers, 1, 0, True)
    print(f"Directory da leggere: {len(locations)}", flush=True)

    candidates: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = {key: [] for key in targets}
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = [executor.submit(_scan_location, client, location, targets, example_to_key) for location in locations]
        for index, future in enumerate(as_completed(futures), start=1):
            try:
                found = future.result()
                with lock:
                    for candidate in found:
                        candidates[tuple(candidate["key"])].append(candidate)
            except Exception as exc:  # noqa: BLE001
                print(f"[directory non letta] {type(exc).__name__}: {exc}", flush=True)
            if index == 1 or index % 10 == 0 or index == len(futures):
                covered = sum(bool(items) for items in candidates.values())
                print(f"[{index}/{len(futures)}] combinazioni trovate={covered}/{len(targets)}", flush=True)

    rng = random.Random(args.seed)
    selected = [rng.choice(items) for items in candidates.values() if items]
    missing = [list(key) for key, items in candidates.items() if not items]
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = [
            executor.submit(
                _build_one,
                item,
                output_dir,
                args.timeout,
                args.max_side,
                args.jpeg_quality,
                args.retries,
            )
            for item in selected
        ]
        for index, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            print(f"[{index}/{len(futures)}] {result['camera']} {result['product_id']}: {result['status']}", flush=True)

    payload = {
        "schema_version": 1,
        "generated_at_unix": time.time(),
        "source_census": str(census_path),
        "preferred_sol_range": {"start": sol_start, "end": sol_end},
        "random_seed": args.seed,
        "preview_settings": {"max_side": args.max_side, "jpeg_quality": args.jpeg_quality},
        "summary": {
            "requested": len(targets),
            "candidates_found": len(selected),
            "previews_ready": sum(item["status"] in {"ok", "existing"} for item in results),
            "conversion_errors": sum(item["status"] == "error" for item in results),
            "not_found_in_range": len(missing),
            "elapsed_seconds": round(time.monotonic() - started, 3),
        },
        "examples": sorted(results, key=lambda item: (item["camera"], item["product_id"])),
        "missing_combinations": missing,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Manifest: {manifest_path}", flush=True)
    print(json.dumps(payload["summary"], indent=2, ensure_ascii=False), flush=True)
    return 0 if not any(item["status"] == "error" for item in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
