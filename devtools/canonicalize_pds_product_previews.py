#!/usr/bin/env python3
"""Keep one verified preview for every product combination exposed by the UI.

The command is deliberately transactional: it builds a staging directory,
validates it, and only then replaces the preview asset directory.  Without
``--install`` it only writes an audit report and never changes assets.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ASSETS = ROOT / "catalog_manager" / "assets" / "pds_product_examples"
DEFAULT_COMBINATIONS = ROOT / "analysis_output" / "pds_ui_combination_verification.json"
DEFAULT_REPORT = ROOT / "analysis_output" / "pds_preview_canonicalization.json"

MMM_CAMERAS = {"mastcam", "mahli", "mardi"}


def ui_key(camera: str, combination: str) -> tuple[str, str]:
    return camera.lower(), combination.upper()


def preview_key(item: dict[str, Any]) -> tuple[str, str] | None:
    camera = str(item.get("camera", "")).lower()
    combination = list(item.get("combination") or [])
    if camera in MMM_CAMERAS and len(combination) >= 4:
        return camera, f"{str(combination[2]).upper()}_{str(combination[3]).upper()}"
    product_id = str(item.get("product_id", "")).upper()
    match = re.match(r"^([A-Z0-9]{3})_\d+([A-Z0-9_]{5})", product_id)
    if match:
        return camera, f"{match.group(1)}:{match.group(2)}"
    return None


def image_score(path: Path) -> tuple[int, int, int]:
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
        return (1, width * height, path.stat().st_size)
    except Exception:  # noqa: BLE001
        return (0, 0, 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument("--combinations", type=Path, default=DEFAULT_COMBINATIONS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()

    assets = args.assets.resolve()
    manifest_path = assets / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verification = json.loads(args.combinations.resolve().read_text(encoding="utf-8"))
    expected = {
        ui_key(str(row["camera"]), str(row["combination"]))
        for row in verification.get("confirmed_combinations", [])
    }

    candidates: dict[tuple[str, str], list[tuple[tuple[int, int, int], dict[str, Any]]]] = defaultdict(list)
    unclassified: list[str] = []
    for item in manifest.get("examples", []):
        key = preview_key(item)
        relative = Path(str(item.get("preview", "")))
        path = assets / relative
        if key is None:
            unclassified.append(str(item.get("product_id", "")))
            continue
        score = image_score(path)
        if key in expected and score[0]:
            candidates[key].append((score, item))

    selected: dict[tuple[str, str], dict[str, Any]] = {}
    for key, items in candidates.items():
        selected[key] = max(items, key=lambda pair: (pair[0], str(pair[1].get("product_id", ""))))[1]
    missing = sorted(expected - set(selected))
    duplicates_removed = sum(max(0, len(items) - 1) for items in candidates.values())

    report = {
        "generated_at_unix": time.time(),
        "expected": len(expected),
        "selected": len(selected),
        "missing_count": len(missing),
        "missing": [{"camera": camera, "combination": combination} for camera, combination in missing],
        "surplus_manifest_entries": len(manifest.get("examples", [])) - len(selected),
        "duplicates_within_expected": duplicates_removed,
        "unclassified": unclassified,
        "installed": False,
    }

    if args.install:
        if missing:
            raise SystemExit(f"Installazione rifiutata: mancano {len(missing)} anteprime")
        staging = assets.parent / f".{assets.name}.staging"
        previous = assets.parent / f".{assets.name}.previous"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        canonical_examples: list[dict[str, Any]] = []
        for key in sorted(selected):
            item = dict(selected[key])
            source = assets / str(item["preview"])
            destination = staging / str(item["preview"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            canonical_examples.append(item)
        canonical_manifest = dict(manifest)
        canonical_manifest["examples"] = canonical_examples
        canonical_manifest["missing_combinations"] = []
        canonical_manifest["summary"] = {
            "requested": len(expected),
            "candidates_found": len(expected),
            "previews_ready": len(expected),
            "conversion_errors": 0,
            "not_found_in_range": 0,
            "elapsed_seconds": 0,
        }
        (staging / "manifest.json").write_text(
            json.dumps(canonical_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        staged_files = list(staging.rglob("*.jpg"))
        if len(staged_files) != len(expected):
            raise SystemExit(f"Validazione staging fallita: {len(staged_files)} file per {len(expected)} combinazioni")
        if previous.exists():
            shutil.rmtree(previous)
        assets.replace(previous)
        staging.replace(assets)
        shutil.rmtree(previous)
        report["installed"] = True

    args.report.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.report.resolve().write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("expected", "selected", "missing_count", "surplus_manifest_entries", "installed")}, indent=2))
    print(f"Report: {args.report.resolve()}")
    return 0 if not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
