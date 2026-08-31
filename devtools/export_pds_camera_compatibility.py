from __future__ import annotations

import json
import re
from pathlib import Path

import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
PARQUET = ROOT / "data" / "catalog" / "Catalog_PDS.parquet"
CENSUS = ROOT / "analysis_output" / "pds_product_census_test" / "pds_product_census.json"
OUTPUT = ROOT / "catalog_manager" / "data" / "pds_camera_compatibility.json"


def add_mmm(target: dict, camera: str, product_type: str, level: str) -> None:
    target.setdefault(camera, {}).setdefault(product_type, set()).add(level)


def add_engineering(target: dict, camera: str, prefix: str, marker: str) -> None:
    if len(prefix) == 3 and len(marker) == 5:
        target.setdefault(camera, {}).setdefault(marker[:3], {}).setdefault(prefix, set()).add(marker[3:])


def main() -> None:
    mmm: dict = {}
    engineering: dict = {}
    table = pq.read_table(PARQUET, columns=["camera", "product_id"])
    for camera_raw, product_raw in zip(table["camera"].to_pylist(), table["product_id"].to_pylist()):
        camera = str(camera_raw or "").casefold()
        product = str(product_raw or "").upper().rsplit(".", 1)[0]
        if camera in {"mastcam", "mahli", "mardi"}:
            match = re.search(r"([A-Z][0-9]{2})_(D[A-Z]{3})$", product)
            if match:
                add_mmm(mmm, camera, *match.groups())
        elif camera in {"navcam", "hazcam", "chemcam"}:
            match = re.match(r"^([A-Z0-9]{3})_\d+([A-Z0-9_]{5})", product)
            if match:
                add_engineering(engineering, camera, *match.groups())

    census = json.loads(CENSUS.read_text(encoding="utf-8"))
    for row in census.get("combinations", []):
        camera = str(row.get("camera") or "").casefold()
        descriptor = str(row.get("descriptor_or_tokens") or "").upper()
        level = str(row.get("processing_suffix") or "").upper()
        prefix = str(row.get("camera_prefix") or "").upper()
        if camera in {"mastcam", "mahli", "mardi"} and re.fullmatch(r"[A-Z][0-9]{2}", descriptor) and level:
            add_mmm(mmm, camera, descriptor, level)
        elif camera in {"navcam", "hazcam", "chemcam"}:
            markers = re.findall(r"(?:^|\|)([A-Z0-9_]{5})(?:\||$)", descriptor)
            for marker in markers:
                add_engineering(engineering, camera, prefix, marker)

    payload = {
        "mmm": {
            camera: {kind: sorted(levels) for kind, levels in sorted(kinds.items())}
            for camera, kinds in sorted(mmm.items())
        },
        "engineering": {
            camera: {
                family: {prefix: sorted(variants) for prefix, variants in sorted(prefixes.items())}
                for family, prefixes in sorted(families.items())
            }
            for camera, families in sorted(engineering.items())
        },
    }
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
