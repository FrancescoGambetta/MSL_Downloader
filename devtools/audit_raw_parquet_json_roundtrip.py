from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.make_msl_catalog import _load_json, _write_parquet  # noqa: E402
from devtools.audit_pds_parquet_json_roundtrip import (  # noqa: E402
    apply_canonical_schema,
    compare_frames,
    records_from_frame,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit RAW Parquet -> JSON -> Parquet reversibility")
    parser.add_argument("--input", default="data/catalog/Catalog_RawArch.parquet")
    parser.add_argument("--camera", required=True)
    parser.add_argument("--sol-start", type=int, required=True)
    parser.add_argument("--sol-end", type=int, required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--schema", default="config/raw_catalog_schema.json")
    args = parser.parse_args()
    started = time.perf_counter()
    input_path = (ROOT / args.input).resolve()
    output_dir = (ROOT / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "catalog_sample_rebuilt.json"
    parquet_path = output_dir / "catalog_sample_roundtrip.parquet"
    report_path = output_dir / "roundtrip_audit_report.json"
    schema = json.loads((ROOT / args.schema).read_text(encoding="utf-8"))

    frame = pd.read_parquet(input_path)
    sols = pd.to_numeric(frame["sol"], errors="coerce")
    camera_all = args.camera.casefold() in {"all", "*"}
    camera_mask = pd.Series(True, index=frame.index) if camera_all else frame["camera"].astype(str).str.casefold().eq(args.camera.casefold())
    sample = frame.loc[camera_mask & sols.between(min(args.sol_start, args.sol_end), max(args.sol_start, args.sol_end))].copy()
    sample = apply_canonical_schema(sample, schema)
    sample = sample.sort_values(["camera", "sol", "product_id", "img_url"], kind="stable").reset_index(drop=True)

    config = json.loads((ROOT / "config" / "catalog_distribution_sources.json").read_text(encoding="utf-8"))
    catalog = {
        "catalog_version": 2,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mission": "MSL",
        "base_url": config.get("raw", {}).get("manifest_url", "https://mars.jpl.nasa.gov/msl-raw-images/image/image_manifest.json"),
        "catalog_kind": "raw_archive_reconstructed_from_parquet",
        "cameras": {},
    }
    for camera, camera_frame in sample.groupby("camera", sort=False):
        products = records_from_frame(camera_frame)
        catalog["cameras"][str(camera)] = {"product_count": len(products), "products": products}
    json_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    loaded = _load_json(json_path, {})
    written_rows = _write_parquet(loaded, parquet_path)
    rebuilt = apply_canonical_schema(pd.read_parquet(parquet_path), schema)
    rebuilt = rebuilt.sort_values(["camera", "sol", "product_id", "img_url"], kind="stable").reset_index(drop=True)
    comparison = compare_frames(sample, rebuilt)
    pass_result = (
        written_rows == len(sample)
        and not comparison["missing_columns_after_roundtrip"]
        and not comparison["extra_columns_after_roundtrip"]
        and not comparison["missing_row_keys_after_roundtrip"]
        and not comparison["extra_row_keys_after_roundtrip"]
        and not comparison["semantic_mismatch_counts_by_column"]
        and not comparison["dtype_changes"]
    )
    report = {
        "status": "PASS" if pass_result else "FAIL",
        "camera": args.camera,
        "sol_start": args.sol_start,
        "sol_end": args.sol_end,
        "source_rows": len(sample),
        "written_rows": written_rows,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "comparison": comparison,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{report['status']} camera={args.camera} rows={len(sample):,} elapsed={report['elapsed_seconds']:.2f}s")
    if not pass_result:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
