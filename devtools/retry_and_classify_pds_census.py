"""Riprova gli errori di un censimento PDS e classifica i codici osservati.

Non modifica il censimento sorgente né i cataloghi dell'applicazione. I prodotti
recuperati vengono salvati in un supplemento separato; la classificazione è
strutturale e non attribuisce significati scientifici non ancora verificati.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from devtools.census_nasa_pds_products import (  # noqa: E402
    HttpClient,
    Inventory,
    _parse_sol,
    _scan_listing,
)


def _family(code: str) -> tuple[str, str]:
    """Restituisce famiglia e variante senza inventarne il significato."""
    value = code.upper().strip()
    match = re.fullmatch(r"([A-Z]{3})_?([A-Z0-9_]{0,2})", value)
    if not match:
        return value or "UNKNOWN", ""
    return match.group(1), match.group(2)


def _retry_errors(source: dict[str, Any], client: HttpClient, workers: int, examples: int) -> tuple[Inventory, int]:
    inventory = Inventory(examples)
    tasks: list[tuple[str, int, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in source.get("errors", []):
        camera = str(item.get("camera", "")).lower()
        url = str(item.get("url", ""))
        sol = _parse_sol(url)
        key = (camera, url)
        if camera and url and sol is not None and key not in seen:
            seen.add(key)
            tasks.append((camera, sol, url))

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = [executor.submit(_scan_listing, client, inventory, *task) for task in tasks]
        completed = 0
        for future in as_completed(futures):
            future.result()
            completed += 1
            if completed == 1 or completed % 10 == 0 or completed == len(tasks):
                print(
                    f"[retry {completed}/{len(tasks)}] prodotti={sum(inventory.camera_totals.values())} "
                    f"errori={len(inventory.errors)}",
                    flush=True,
                )
    return inventory, len(tasks)


def _supplement_rows(inventory: Inventory) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, count in sorted(inventory.counts.items()):
        camera, prefix, code, suffix, extension = key
        sols = inventory.combination_sols[key]
        rows.append({
            "camera": camera,
            "camera_prefix": prefix,
            "descriptor_or_tokens": code,
            "processing_suffix": suffix,
            "extension": extension,
            "count": count,
            "first_sampled_sol": min(sols),
            "last_sampled_sol": max(sols),
            "sampled_sols_with_products": len(sols),
            "examples": inventory.examples[key],
        })
    return rows


def _classify(base_rows: list[dict[str, Any]], extra_rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[tuple[str, str, str, str, str]] = Counter()
    examples: dict[tuple[str, str, str, str, str], list[str]] = defaultdict(list)
    for row in [*base_rows, *extra_rows]:
        key = (
            str(row.get("camera", "")), str(row.get("camera_prefix", "")),
            str(row.get("descriptor_or_tokens", "")), str(row.get("processing_suffix", "")),
            str(row.get("extension", "")),
        )
        counts[key] += int(row.get("count", 0) or 0)
        for sample in row.get("examples", []):
            if sample not in examples[key] and len(examples[key]) < 5:
                examples[key].append(sample)

    cameras: dict[str, Any] = {}
    for camera in sorted({key[0] for key in counts}):
        camera_keys = [key for key in counts if key[0] == camera]
        if camera in {"navcam", "hazcam"}:
            families: dict[str, Any] = defaultdict(lambda: {"variants": Counter(), "prefixes": Counter(), "examples": []})
            for key in camera_keys:
                _, prefix, code, _, _ = key
                family, variant = _family(code)
                item = families[family]
                item["variants"][variant or "(none)"] += counts[key]
                item["prefixes"][prefix] += counts[key]
                for sample in examples[key]:
                    if sample not in item["examples"] and len(item["examples"]) < 5:
                        item["examples"].append(sample)
            cameras[camera] = {
                "classification_kind": "three_letter_family_plus_observed_variant",
                "warning": "Structural grouping only; descriptions must be verified against the official MSL Camera SIS.",
                "families": {
                    name: {
                        "variants": dict(sorted(data["variants"].items())),
                        "camera_prefixes": dict(sorted(data["prefixes"].items())),
                        "examples": data["examples"],
                    }
                    for name, data in sorted(families.items())
                },
            }
        else:
            combinations = []
            for key in sorted(camera_keys):
                _, prefix, descriptor, suffix, extension = key
                combinations.append({
                    "prefix": prefix, "descriptor": descriptor, "processing_suffix": suffix,
                    "extension": extension, "count": counts[key], "examples": examples[key],
                })
            cameras[camera] = {
                "classification_kind": "observed_exact_combinations",
                "combinations": combinations,
            }
    return cameras


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=40)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--examples", type=int, default=5)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--classify-only",
        action="store_true",
        help="Non riprova la rete: classifica immediatamente il censimento sorgente.",
    )
    args = parser.parse_args()

    source_path = args.input.resolve()
    output_dir = (args.output_dir or source_path.parent).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    source = json.loads(source_path.read_text(encoding="utf-8"))
    started = time.monotonic()
    if args.classify_only:
        inventory, attempted = Inventory(max(1, args.examples)), 0
    else:
        inventory, attempted = _retry_errors(
            source, HttpClient(args.timeout, args.retries), args.workers, max(1, args.examples)
        )
    rows = _supplement_rows(inventory)
    elapsed = time.monotonic() - started
    supplement = {
        "source": str(source_path), "generated_at_unix": time.time(),
        "elapsed_seconds": round(elapsed, 3), "directories_attempted": attempted,
        "directories_recovered": attempted - len(inventory.errors),
        "directories_still_unverified": len(inventory.errors),
        "products_recovered": sum(inventory.camera_totals.values()),
        "combinations": rows, "errors": inventory.errors,
    }
    classification = {
        "source": str(source_path),
        "includes_retry_supplement": not args.classify_only,
        "method": "Observed codes grouped structurally; semantic descriptions are intentionally pending official documentation review.",
        "cameras": _classify(list(source.get("combinations", [])), rows),
    }
    retry_path = output_dir / "pds_product_census_retry.json"
    class_path = output_dir / "pds_product_classification.json"
    retry_path.write_text(json.dumps(supplement, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    class_path.write_text(json.dumps(classification, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Retry completato in {elapsed:.1f} s: {attempted - len(inventory.errors)}/{attempted} directory recuperate")
    print(f"Supplemento: {retry_path}")
    print(f"Classificazione: {class_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
