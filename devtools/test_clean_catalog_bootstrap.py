from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from catalog_manager.distribution import install_remote_pds_release, install_remote_raw_release
from core.pds_json_rebuild import rebuild_pds_json
from core.raw_json_rebuild import rebuild_raw_json_streaming


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _catalog_summary(path: Path) -> dict[str, Any]:
    frame = pd.read_parquet(path, columns=["camera", "img_url"])
    return {
        "rows": int(len(frame)),
        "camera_counts": {str(k): int(v) for k, v in frame["camera"].value_counts().sort_index().items()},
        "unique_img_urls": int(frame["img_url"].nunique(dropna=True)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="End-to-end clean catalog bootstrap test")
    parser.add_argument(
        "--target",
        type=Path,
        default=ROOT / "data" / "catalog_json_rebuild" / "clean_bootstrap_test",
    )
    args = parser.parse_args()
    target = args.target.resolve()
    allowed = (ROOT / "data" / "catalog_json_rebuild").resolve()
    if allowed not in target.parents:
        raise RuntimeError("Test target must remain below data/catalog_json_rebuild")
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    started = time.perf_counter()

    pds_install = install_remote_pds_release(ROOT, target_dir=target, timeout=240)
    raw_install = install_remote_raw_release(ROOT, target_dir=target, timeout=240)

    pds_json = target / "Catalog_PDS.json"
    raw_json = target / "Catalog_RawArch.json"
    pds_rebuild = rebuild_pds_json(
        target / "Catalog_PDS.parquet",
        pds_json,
        ROOT / "config" / "msl_catalog_config.json",
    )
    raw_rebuild = rebuild_raw_json_streaming(
        target / "Catalog_RawArch.parquet",
        raw_json,
        ROOT / "config" / "raw_catalog_schema.json",
    )

    local_pds = ROOT / "data" / "catalog" / "Catalog_PDS.parquet"
    local_raw = ROOT / "data" / "catalog" / "Catalog_RawArch.parquet"
    checks = {
        "pds_parquet_hash_matches": _sha256(target / "Catalog_PDS.parquet") == _sha256(local_pds),
        "raw_parquet_hash_matches": _sha256(target / "Catalog_RawArch.parquet") == _sha256(local_raw),
        "pds_json_exists": pds_json.exists() and pds_json.stat().st_size > 0,
        "raw_json_exists": raw_json.exists() and raw_json.stat().st_size > 0,
        "pds_rows_match": int(pds_rebuild["rows"]) == 387276,
        "raw_rows_match": int(raw_rebuild["rows"]) == 1449239,
    }
    report = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "elapsed_seconds": time.perf_counter() - started,
        "pds": {
            "install": pds_install["status"],
            "summary": _catalog_summary(target / "Catalog_PDS.parquet"),
            "json_size_bytes": pds_json.stat().st_size,
        },
        "raw": {
            "install": raw_install["status"],
            "summary": _catalog_summary(target / "Catalog_RawArch.parquet"),
            "json_size_bytes": raw_json.stat().st_size,
            "record_sha256": raw_rebuild["record_sha256"],
        },
    }
    (target / "clean_bootstrap_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
