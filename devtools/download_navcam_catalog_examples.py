#!/usr/bin/env python3
"""Scarica un prodotto PDS Navcam di esempio per ogni combinazione nel catalogo.

Questo strumento e' completamente indipendente da MSL Downloader: legge un
catalogo Parquet o un checkpoint JSON, usa gli URL gia' presenti e converte gli
IMG scientifici in PNG usando il relativo LBL.

Esempi:
  python devtools/download_navcam_catalog_examples.py --dry-run
  python devtools/download_navcam_catalog_examples.py --sol-start 3320 --sol-end 3380
  python devtools/download_navcam_catalog_examples.py --sol-start 3320 --sol-end 3380 --include-labels
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from devtools.download_pds_product_examples import _download, _img_to_png

DEFAULT_CATALOG = ROOT / "data" / "catalog" / "Catalog_PDS.parquet"
DEFAULT_OUTPUT = ROOT / "analysis_output" / "navcam_catalog_examples"


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sol-start", type=int, default=None)
    parser.add_argument("--sol-end", type=int, default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--include-labels", action="store_true", help="Conserva anche IMG e LBL originali")
    parser.add_argument("--force", action="store_true", help="Riscarica anche i file gia' presenti")
    parser.add_argument("--dry-run", action="store_true", help="Crea il piano e il manifest senza scaricare")
    parser.add_argument("--max-combinations", type=int, default=0, help="Limite diagnostico; 0 significa tutte")
    return parser.parse_args()


def navcam_combination(product_id: str) -> tuple[str, str] | None:
    """Restituisce (camera, prodotto+variante), usando la nomenclatura PDS Navcam."""
    value = product_id.upper().rsplit(".", 1)[0]
    if "_" not in value:
        return None
    camera = value.split("_", 1)[0][:3]
    tail = value.split("_", 1)[1]
    # Dopo lo SCLK iniziano famiglia (3 caratteri) e variante tecnica.
    index = 0
    while index < len(tail) and tail[index].isdigit():
        index += 1
    marker = tail[index:index + 5].rstrip("_")
    if camera not in {"NAA", "NAB", "NLA", "NLB", "NRA", "NRB"} or len(marker) < 3:
        return None
    return camera, marker


def read_candidates(path: Path, sol_start: int | None, sol_end: int | None) -> list[dict[str, Any]]:
    columns = ["camera", "product_id", "sol", "img_url", "img_name", "lbl_url", "lbl_name"]
    if path.suffix.casefold() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        camera_data = (payload.get("cameras") or {}).get("navcam") or {}
        rows = camera_data.get("products") or []
        for row in rows:
            row.setdefault("camera", "navcam")
    else:
        import pyarrow.parquet as pq

        rows = pq.read_table(path, columns=columns).to_pylist()
    result: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("camera") or "").casefold() != "navcam":
            continue
        sol = int(row.get("sol") or 0)
        if sol_start is not None and sol < sol_start:
            continue
        if sol_end is not None and sol > sol_end:
            continue
        combination = navcam_combination(str(row.get("product_id") or ""))
        if combination and row.get("img_url"):
            row["combination"] = combination
            result.append(row)
    return result


def choose_examples(rows: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(tuple(row["combination"]), []).append(row)
    rng = random.Random(seed)
    return [rng.choice(grouped[key]) for key in sorted(grouped)]


def download(url: str, destination: Path, timeout: int, retries: int, force: bool) -> str:
    if not force and destination.exists() and destination.stat().st_size > 0:
        return "existing"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    last_error: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            request = Request(url, headers={"User-Agent": "MSL-Navcam-catalog-example-downloader/1.0"})
            with urlopen(request, timeout=timeout) as response, temporary.open("wb") as handle:  # noqa: S310
                shutil.copyfileobj(response, handle, length=256 * 1024)
            temporary.replace(destination)
            return "downloaded"
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            last_error = exc
            temporary.unlink(missing_ok=True)
            if attempt + 1 < max(1, retries):
                time.sleep(min(8.0, 1.5 * (2**attempt)))
    assert last_error is not None
    raise last_error


def fetch_one(row: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    camera, marker = row["combination"]
    folder = args.output_dir / camera / marker
    result = {
        "camera": camera,
        "product_variant": marker,
        "product_id": row["product_id"],
        "sol": row["sol"],
        "img_url": row["img_url"],
        "lbl_url": row.get("lbl_url"),
        "status": "planned" if args.dry_run else "pending",
    }
    if args.dry_run:
        return result
    try:
        product_id = str(row["product_id"])
        png_path = folder / f"{product_id}.png"
        if not args.force and png_path.exists() and png_path.stat().st_size > 0:
            result["status"] = "existing"
        else:
            import tempfile

            with tempfile.TemporaryDirectory(prefix="msl_navcam_preview_") as temporary:
                temporary_dir = Path(temporary)
                img_path = temporary_dir / "source.img"
                lbl_path = temporary_dir / "source.lbl"
                _download(str(row["img_url"]), img_path, args.timeout, args.retries)
                if not row.get("lbl_url"):
                    raise ValueError("LBL URL mancante: impossibile convertire IMG")
                _download(str(row["lbl_url"]), lbl_path, args.timeout, args.retries)
                png_path.parent.mkdir(parents=True, exist_ok=True)
                _img_to_png(img_path, lbl_path, png_path)
                if args.include_labels:
                    shutil.copy2(img_path, folder / f"{product_id}.IMG")
                    shutil.copy2(lbl_path, folder / f"{product_id}.LBL")
            result["status"] = "downloaded"
        result["preview"] = png_path.relative_to(args.output_dir).as_posix()
        result["folder"] = folder.relative_to(args.output_dir).as_posix()
    except Exception as exc:  # noqa: BLE001
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def write_manifest(args: argparse.Namespace, results: list[dict[str, Any]], elapsed: float) -> Path:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / "manifest.json"
    payload = {
        "schema_version": 1,
        "source_catalog": str(args.catalog.resolve()),
        "camera": "navcam",
        "sol_range": {"start": args.sol_start, "end": args.sol_end},
        "summary": {
            "combinations": len(results),
            "downloaded": sum(row["status"] == "downloaded" for row in results),
            "existing": sum(row["status"] == "existing" for row in results),
            "errors": sum(row["status"] == "error" for row in results),
            "planned": sum(row["status"] == "planned" for row in results),
            "elapsed_seconds": round(elapsed, 3),
        },
        "examples": sorted(results, key=lambda row: (row["camera"], row["product_variant"])),
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def main() -> int:
    args = arguments()
    args.catalog = args.catalog.resolve()
    args.output_dir = args.output_dir.resolve()
    if args.sol_start is not None and args.sol_end is not None and args.sol_start > args.sol_end:
        raise SystemExit("--sol-start non puo' essere maggiore di --sol-end")
    if not args.catalog.exists():
        raise SystemExit(f"Catalogo non trovato: {args.catalog}")

    rows = read_candidates(args.catalog, args.sol_start, args.sol_end)
    selected = choose_examples(rows, args.seed)
    if args.max_combinations > 0:
        selected = selected[:args.max_combinations]
    print(f"Righe Navcam candidate: {len(rows)}", flush=True)
    print(f"Combinazioni rappresentate: {len(selected)}", flush=True)

    started = time.monotonic()
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = [executor.submit(fetch_one, row, args) for row in selected]
        for index, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            print(f"[{index}/{len(futures)}] {result['camera']} {result['product_variant']}: {result['status']}", flush=True)

    manifest = write_manifest(args, results, time.monotonic() - started)
    errors = sum(row["status"] == "error" for row in results)
    print(f"Manifest: {manifest}", flush=True)
    print(f"Errori: {errors}", flush=True)
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
