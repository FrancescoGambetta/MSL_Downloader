#!/usr/bin/env python3
"""Completa le anteprime MARDI usando gli URL già indicizzati nel Parquet PDS."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from download_pds_product_examples import _build_one, _key_from_product


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "catalog" / "Catalog_PDS.parquet"
COMPATIBILITY = ROOT / "catalog_manager" / "data" / "pds_camera_compatibility.json"
OUTPUT = ROOT / "catalog_manager" / "assets" / "pds_product_examples"


def main() -> int:
    manifest_path = OUTPUT / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    existing_pairs = {
        (str(item.get("combination", ["", "", "", ""])[2]),
         str(item.get("combination", ["", "", "", ""])[3]))
        for item in payload.get("examples", [])
        if item.get("camera") == "mardi" and item.get("status") in {"ok", "existing"}
    }
    compatibility = json.loads(COMPATIBILITY.read_text(encoding="utf-8"))["mmm"]["mardi"]
    frame = pd.read_parquet(
        CATALOG, columns=["product_id", "sol", "camera", "img_url", "lbl_url"]
    )
    frame = frame[frame["camera"] == "mardi"]
    candidates: list[dict] = []
    for kind, levels in compatibility.items():
        for level in levels:
            if (kind, level) in existing_pairs:
                continue
            rows = frame[frame["product_id"].str.endswith(f"{kind}_{level}", na=False)]
            if rows.empty:
                print(f"Non presente nel catalogo: {kind}|{level}", flush=True)
                continue
            row = rows.iloc[len(rows) // 2]
            source_url = str(row["img_url"])
            extension = Path(source_url.split("?", 1)[0]).suffix.lstrip(".").upper() or "IMG"
            candidates.append({
                "key": _key_from_product("mardi", str(row["product_id"]), extension),
                "camera": "mardi", "sol": int(row["sol"]),
                "product_id": str(row["product_id"]), "extension": extension,
                "source_url": source_url,
                "label_url": "" if pd.isna(row["lbl_url"]) else str(row["lbl_url"]),
            })

    print(f"Anteprime MARDI da aggiungere: {len(candidates)}", flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_build_one, item, OUTPUT, 60, 1200, 88, 3) for item in candidates]
        for index, future in enumerate(as_completed(futures), 1):
            result = future.result()
            results.append(result)
            print(f"{index}/{len(candidates)} {result['product_id']} {result['status']}", flush=True)

    by_key = {tuple(item.get("combination", [])): item for item in payload.get("examples", [])}
    for result in results:
        by_key[tuple(result.get("combination", []))] = result
    payload["examples"] = list(by_key.values())
    ready_pairs = {
        (str(item.get("combination", ["", "", "", ""])[2]),
         str(item.get("combination", ["", "", "", ""])[3]))
        for item in payload["examples"]
        if item.get("camera") == "mardi" and item.get("status") in {"ok", "existing"}
    }
    payload["examples"] = [
        item for item in payload["examples"]
        if not (
            item.get("camera") == "mardi"
            and item.get("status") == "error"
            and (str(item.get("combination", ["", "", "", ""])[2]),
                 str(item.get("combination", ["", "", "", ""])[3])) in ready_pairs
        )
    ]
    payload["summary"] = {
        "requested": len(payload["examples"]), "candidates_found": len(payload["examples"]),
        "previews_ready": sum(x.get("status") in {"ok", "existing"} for x in payload["examples"]),
        "conversion_errors": sum(x.get("status") == "error" for x in payload["examples"]),
        "not_found_in_range": 0,
    }
    temporary = manifest_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(manifest_path)
    return 1 if any(item.get("status") == "error" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
