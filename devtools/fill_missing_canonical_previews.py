#!/usr/bin/env python3
"""Fill preview combinations missing from the canonical UI set using the local PDS catalog."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "devtools") not in sys.path:
    sys.path.insert(0, str(ROOT / "devtools"))

from download_pds_product_examples import _build_one  # noqa: E402


ASSETS = ROOT / "catalog_manager" / "assets" / "pds_product_examples"
AUDIT = ROOT / "analysis_output" / "pds_preview_canonicalization.json"
PARQUET = ROOT / "data" / "catalog" / "Catalog_PDS.parquet"


def main() -> int:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    missing = list(audit.get("missing", []))
    if not missing:
        print("Nessuna anteprima mancante.")
        return 0
    manifest_path = ASSETS / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frame = pd.read_parquet(PARQUET, columns=["camera", "product_id", "sol", "img_url", "lbl_url"])
    results = []
    failures = []
    for row in missing:
        camera = str(row["camera"]).lower()
        prefix, marker = str(row["combination"]).upper().split(":", 1)
        pattern = re.compile(rf"^{re.escape(prefix)}_\d+{re.escape(marker)}", re.IGNORECASE)
        choices = frame[(frame["camera"].str.lower() == camera) & frame["product_id"].str.match(pattern, na=False)]
        if choices.empty:
            failures.append({**row, "error": "not_found_in_local_pds_catalog"})
            continue
        # Prefer a normal web image over a scientific IMG when both exist.
        choices = choices.assign(_url=choices["img_url"].fillna(""), _size=choices["img_url"].fillna("").str.len())
        selected = choices.sort_values(["_size", "sol"], ascending=[False, False]).iloc[0]
        source_url = str(selected["img_url"])
        extension = Path(urlparse(source_url).path).suffix.upper().lstrip(".")
        candidate = {
            "key": (camera, prefix, marker, "", extension),
            "camera": camera,
            "sol": int(selected["sol"]),
            "product_id": str(selected["product_id"]),
            "extension": extension,
            "source_url": source_url,
            "label_url": "" if pd.isna(selected["lbl_url"]) else str(selected["lbl_url"]),
        }
        result = _build_one(candidate, ASSETS, 60, 1200, 82, 4, True)
        print(f"{camera} {prefix}:{marker}: {result['status']}", flush=True)
        if result["status"] in {"ok", "existing"}:
            results.append(result)
        else:
            failures.append({**row, "error": result.get("error", "conversion_failed")})
    if results:
        manifest["examples"] = list(manifest.get("examples", [])) + results
        manifest["generated_at_unix"] = time.time()
        temporary = manifest_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(manifest_path)
    print(json.dumps({"added": len(results), "failures": failures}, indent=2, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
