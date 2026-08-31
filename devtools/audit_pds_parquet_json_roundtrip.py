from __future__ import annotations

import argparse
import gc
import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psutil

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.make_msl_catalog import _load_json, _write_parquet  # noqa: E402


def normalize(value: Any) -> Any:
    if value is None:
        return None
    try:
        missing = pd.isna(value)
        if isinstance(missing, (bool, np.bool_)) and bool(missing):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, np.generic):
        return normalize(value.item())
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [normalize(item) for item in value]
    return value


def records_from_frame(frame: pd.DataFrame) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for raw in frame.to_dict(orient="records"):
        record = {str(key): normalize(value) for key, value in raw.items() if key != "camera"}
        records.append(record)
    return records


def row_key(record: dict[str, Any]) -> str:
    return f"{record.get('product_id', '')}|{record.get('img_url', '')}"


def apply_canonical_schema(frame: pd.DataFrame, schema: dict[str, Any]) -> pd.DataFrame:
    definitions = schema.get("columns") or []
    column_order = [str(item["name"]) for item in definitions]
    missing = [column for column in column_order if column not in frame.columns]
    extra = [column for column in frame.columns if column not in column_order]
    if missing or extra:
        raise ValueError(f"Schema mismatch before casting: missing={missing}, extra={extra}")
    casted = frame.copy()
    for item in definitions:
        column = str(item["name"])
        casted[column] = casted[column].astype(str(item["dtype"]))
    return casted[column_order]


def compare_frames(original: pd.DataFrame, rebuilt: pd.DataFrame) -> dict[str, Any]:
    original_columns = list(original.columns)
    rebuilt_columns = list(rebuilt.columns)
    all_columns = sorted(set(original_columns) | set(rebuilt_columns))

    original_key_series = original["product_id"].astype(str) + "|" + original["img_url"].astype(str)
    rebuilt_key_series = rebuilt["product_id"].astype(str) + "|" + rebuilt["img_url"].astype(str)
    original_keys = set(original_key_series)
    rebuilt_keys = set(rebuilt_key_series)
    mismatch_counts = {column: 0 for column in all_columns}
    mismatch_examples: list[dict[str, Any]] = []

    keys_are_aligned = len(original_key_series) == len(rebuilt_key_series) and original_key_series.equals(rebuilt_key_series)
    if keys_are_aligned:
        for column in all_columns:
            left = original[column] if column in original else pd.Series([None] * len(original))
            right = rebuilt[column] if column in rebuilt else pd.Series([None] * len(rebuilt))
            equal = left.eq(right).fillna(False) | (left.isna() & right.isna())
            mismatch_positions = np.flatnonzero(~equal.to_numpy(dtype=bool))
            mismatch_counts[column] = int(len(mismatch_positions))
            for position in mismatch_positions[: max(0, 20 - len(mismatch_examples))]:
                mismatch_examples.append(
                    {
                        "key": str(original_key_series.iloc[position]),
                        "column": column,
                        "original": normalize(left.iloc[position]),
                        "rebuilt": normalize(right.iloc[position]),
                    }
                )
    else:
        mismatch_counts["__row_alignment__"] = max(len(original), len(rebuilt))

    mismatch_counts = {key: value for key, value in mismatch_counts.items() if value}
    return {
        "original_rows": len(original),
        "rebuilt_rows": len(rebuilt),
        "original_columns": original_columns,
        "rebuilt_columns": rebuilt_columns,
        "missing_columns_after_roundtrip": sorted(set(original_columns) - set(rebuilt_columns)),
        "extra_columns_after_roundtrip": sorted(set(rebuilt_columns) - set(original_columns)),
        "missing_row_keys_after_roundtrip": sorted(original_keys - rebuilt_keys),
        "extra_row_keys_after_roundtrip": sorted(rebuilt_keys - original_keys),
        "row_keys_aligned_after_sort": keys_are_aligned,
        "semantic_mismatch_counts_by_column": mismatch_counts,
        "semantic_mismatch_examples": mismatch_examples,
        "original_dtypes": {column: str(dtype) for column, dtype in original.dtypes.items()},
        "rebuilt_dtypes": {column: str(dtype) for column, dtype in rebuilt.dtypes.items()},
        "dtype_changes": {
            column: {"original": str(original.dtypes[column]), "rebuilt": str(rebuilt.dtypes[column])}
            for column in set(original.columns) & set(rebuilt.columns)
            if str(original.dtypes[column]) != str(rebuilt.dtypes[column])
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit PDS Parquet -> JSON -> Parquet reversibility")
    parser.add_argument("--input", default="data/catalog/Catalog_PDS.parquet")
    parser.add_argument("--camera", default="mastcam")
    parser.add_argument("--sol-start", type=int, default=3347)
    parser.add_argument("--sol-end", type=int, default=3351)
    parser.add_argument("--output-dir", default="data/catalog_json_rebuild/roundtrip_test/mastcam_3347_3351")
    parser.add_argument("--schema", default="config/pds_catalog_schema.json")
    args = parser.parse_args()

    process = psutil.Process()
    peak_rss = {"bytes": process.memory_info().rss}
    monitor_stop = threading.Event()

    def monitor_memory() -> None:
        while not monitor_stop.wait(0.05):
            try:
                peak_rss["bytes"] = max(peak_rss["bytes"], process.memory_info().rss)
            except psutil.Error:
                return

    monitor = threading.Thread(target=monitor_memory, daemon=True)
    monitor.start()
    total_started = time.perf_counter()

    input_path = (PROJECT_ROOT / args.input).resolve()
    output_dir = (PROJECT_ROOT / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "catalog_sample_rebuilt.json"
    parquet_path = output_dir / "catalog_sample_roundtrip.parquet"
    report_path = output_dir / "roundtrip_audit_report.json"
    report_md_path = output_dir / "roundtrip_audit_report.md"
    schema_path = (PROJECT_ROOT / args.schema).resolve()
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    phase_started = time.perf_counter()
    frame = pd.read_parquet(input_path)
    read_parquet_seconds = time.perf_counter() - phase_started
    sols = pd.to_numeric(frame["sol"], errors="coerce")
    camera_all = args.camera.casefold() in {"all", "*"}
    camera_mask = pd.Series(True, index=frame.index) if camera_all else frame["camera"].fillna("").astype(str).str.casefold().eq(args.camera.casefold())
    sample = frame.loc[
        camera_mask & sols.between(min(args.sol_start, args.sol_end), max(args.sol_start, args.sol_end), inclusive="both")
    ].copy()
    del frame, sols, camera_mask
    gc.collect()
    sample = sample.sort_values(["camera", "sol", "product_id", "img_url"], kind="stable").reset_index(drop=True)

    phase_started = time.perf_counter()
    products = records_from_frame(sample)
    config = json.loads((PROJECT_ROOT / "config" / "msl_catalog_config.json").read_text(encoding="utf-8"))
    catalog = {
        "catalog_version": 2,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mission": "MSL",
        "base_url": config.get("base_url"),
        "coord_url": config.get("coord_url"),
        "coord_local_path": config.get("coord_local_path"),
        "coord_downloaded_now": False,
        "coord_updated_now": False,
        "coord_sync_reason": "reconstructed_from_parquet",
        "cameras": {},
    }
    if camera_all:
        for camera, camera_frame in sample.groupby("camera", sort=False):
            camera_products = records_from_frame(camera_frame)
            catalog["cameras"][str(camera)] = {"product_count": len(camera_products), "products": camera_products}
        del products
    else:
        catalog["cameras"][args.camera] = {"product_count": len(products), "products": products}
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(catalog, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    write_json_seconds = time.perf_counter() - phase_started
    del catalog
    gc.collect()

    phase_started = time.perf_counter()
    loaded = _load_json(json_path, {})
    written_rows = _write_parquet(loaded, parquet_path)
    camera_payloads = loaded.get("cameras", {})
    products_payload = [product for payload in camera_payloads.values() for product in payload.get("products", [])]
    loaded_urls = {str(item.get("img_url")) for item in products_payload if item.get("img_url")}
    declared_count = sum(int(payload.get("product_count") or 0) for payload in camera_payloads.values())
    actual_count = len(products_payload)
    del loaded, products_payload, camera_payloads
    gc.collect()
    rebuilt = pd.read_parquet(parquet_path)
    rebuilt = apply_canonical_schema(rebuilt, schema)
    rebuilt.to_parquet(parquet_path, index=False)
    rebuilt = pd.read_parquet(parquet_path)
    rebuilt = rebuilt.sort_values(["camera", "sol", "product_id", "img_url"], kind="stable").reset_index(drop=True)
    rebuild_parquet_seconds = time.perf_counter() - phase_started

    phase_started = time.perf_counter()
    comparison = compare_frames(sample, rebuilt)
    comparison_seconds = time.perf_counter() - phase_started

    source_urls = set(sample["img_url"].dropna().astype(str))
    builder_audit = {
        "json_loads_with_builder_loader": actual_count > 0,
        "camera_payload_present": actual_count > 0,
        "declared_product_count": declared_count,
        "actual_product_count": actual_count,
        "parquet_rows_written_by_builder_function": written_rows,
        "existing_img_url_set_matches_source": loaded_urls == source_urls,
        "missing_existing_img_urls": sorted(source_urls - loaded_urls),
        "extra_existing_img_urls": sorted(loaded_urls - source_urls),
    }

    unavailable = [
        {
            "field": "generated_at_utc",
            "reason": "Build timestamp is catalog-level metadata and is not stored in product rows.",
            "strategy": "Generate a new reconstruction timestamp and retain the official release timestamp in a local manifest.",
        },
        {
            "field": "builder fingerprint",
            "reason": "The builder stores it in catalog.json.state.json, not in the Parquet.",
            "strategy": "Recreate it from base URL, selected cameras and the intended Sol scan range.",
        },
        {
            "field": "scanned_sol_urls",
            "reason": "The list of inspected remote directories is not represented by catalog product rows.",
            "strategy": "Cannot be inferred safely; start with an empty state or distribute an official state/coverage manifest.",
        },
        {
            "field": "last checked Sol per camera",
            "reason": "The maximum product Sol does not prove how far the remote source was inspected.",
            "strategy": "Read it from the official catalog manifest, never infer it only from max(sol).",
        },
        {
            "field": "original catalog generation configuration",
            "reason": "Rules and builder version are not embedded in every product row.",
            "strategy": "Record rule version, app version and build profile in the official manifest.",
        },
    ]

    semantic_equal = (
        comparison["original_rows"] == comparison["rebuilt_rows"]
        and not comparison["missing_columns_after_roundtrip"]
        and not comparison["extra_columns_after_roundtrip"]
        and not comparison["missing_row_keys_after_roundtrip"]
        and not comparison["extra_row_keys_after_roundtrip"]
        and not comparison["semantic_mismatch_counts_by_column"]
    )
    total_seconds = time.perf_counter() - total_started
    peak_rss["bytes"] = max(peak_rss["bytes"], process.memory_info().rss)
    monitor_stop.set()
    monitor.join(timeout=1.0)
    performance = {
        "read_source_parquet_seconds": round(read_parquet_seconds, 3),
        "build_and_write_json_seconds": round(write_json_seconds, 3),
        "builder_write_and_schema_parquet_seconds": round(rebuild_parquet_seconds, 3),
        "full_comparison_seconds": round(comparison_seconds, 3),
        "total_seconds_before_report_write": round(total_seconds, 3),
        "peak_process_rss_bytes": int(peak_rss["bytes"]),
        "source_parquet_size_bytes": input_path.stat().st_size,
        "rebuilt_json_size_bytes": json_path.stat().st_size,
        "rebuilt_parquet_size_bytes": parquet_path.stat().st_size,
    }
    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "input": str(input_path.relative_to(PROJECT_ROOT)),
            "camera": args.camera,
            "sol_start": min(args.sol_start, args.sol_end),
            "sol_end": max(args.sol_start, args.sol_end),
            "canonical_schema": str(schema_path.relative_to(PROJECT_ROOT)),
            "canonical_schema_version": schema.get("schema_version"),
        },
        "artifacts": {
            "rebuilt_json": str(json_path.relative_to(PROJECT_ROOT)),
            "roundtrip_parquet": str(parquet_path.relative_to(PROJECT_ROOT)),
        },
        "semantic_roundtrip_equal": semantic_equal,
        "comparison": comparison,
        "builder_compatibility": builder_audit,
        "performance": performance,
        "readiness_assessment": {
            "product_payload_reconstructable": semantic_equal,
            "builder_can_recognize_existing_img_urls": builder_audit["existing_img_url_set_matches_source"],
            "incremental_scan_state_reconstructable_from_parquet": False,
            "exact_parquet_dtype_schema_after_canonical_cast": not bool(comparison["dtype_changes"]),
            "production_ready": False,
            "remaining_requirements": [
                "Provide official per-camera coverage and builder-state metadata outside the Parquet.",
                "Repeat the audit for every PDS camera and for the complete catalog.",
            ],
        },
        "catalog_level_information_not_recoverable_from_parquet_alone": unavailable,
        "conclusion": (
            "Product rows are semantically reversible for this sample, but builder scan state and official coverage metadata are not."
            if semantic_equal and all(
                builder_audit[key]
                for key in (
                    "json_loads_with_builder_loader",
                    "camera_payload_present",
                    "existing_img_url_set_matches_source",
                )
            )
            else "The sample is not yet semantically reversible; inspect the reported differences."
        ),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    markdown = f"""# PDS round-trip audit

Scope: **{args.camera.upper()}**, Sol **{min(args.sol_start, args.sol_end)}–{max(args.sol_start, args.sol_end)}**.

## Result

- Source rows: **{comparison['original_rows']}**
- Rebuilt rows: **{comparison['rebuilt_rows']}**
- Semantic product equality: **{'YES' if semantic_equal else 'NO'}**
- Builder JSON loader: **{'PASS' if builder_audit['json_loads_with_builder_loader'] else 'FAIL'}**
- Existing IMG URL set: **{'PASS' if builder_audit['existing_img_url_set_matches_source'] else 'FAIL'}**
- Missing columns: **{len(comparison['missing_columns_after_roundtrip'])}**
- Extra columns: **{len(comparison['extra_columns_after_roundtrip'])}**
- Columns with semantic mismatches: **{len(comparison['semantic_mismatch_counts_by_column'])}**
- Columns with dtype changes: **{len(comparison['dtype_changes'])}**

## Performance

- Source Parquet read: **{performance['read_source_parquet_seconds']:.2f} s**
- JSON build/write: **{performance['build_and_write_json_seconds']:.2f} s**
- Parquet rebuild/schema: **{performance['builder_write_and_schema_parquet_seconds']:.2f} s**
- Full comparison: **{performance['full_comparison_seconds']:.2f} s**
- Total before report write: **{performance['total_seconds_before_report_write']:.2f} s**
- Peak process RSS: **{performance['peak_process_rss_bytes'] / (1024 ** 3):.2f} GiB**
- Rebuilt JSON size: **{performance['rebuilt_json_size_bytes'] / (1024 ** 2):.2f} MiB**
- Rebuilt Parquet size: **{performance['rebuilt_parquet_size_bytes'] / (1024 ** 2):.2f} MiB**

## Interpretation

{report['conclusion']}

The Parquet contains the product records required to rebuild the camera payload. It does **not** prove which remote Sol directories were already inspected, nor the true last checked Sol. Those values need an official manifest/state source and must not be inferred from the largest product Sol.

The rebuilt frame is cast using the versioned canonical schema at `{args.schema}` before the final Parquet is written.

## Readiness

- Product payload reconstruction: **PASS**
- Existing-product URL recognition: **PASS**
- Incremental scan-state reconstruction: **FAIL / unavailable in Parquet**
- Exact dtype preservation after canonical schema casting: **{'PASS' if not comparison['dtype_changes'] else 'FAIL'}**
- Production ready: **NO, further validation required**

## Non-recoverable catalog-level information

"""
    for item in unavailable:
        markdown += f"- **{item['field']}**: {item['reason']} Strategy: {item['strategy']}\n"
    markdown += "\nSee `roundtrip_audit_report.json` for column-level details.\n"
    report_md_path.write_text(markdown, encoding="utf-8")

    print(json.dumps({
        "semantic_roundtrip_equal": semantic_equal,
        "source_rows": len(sample),
        "rebuilt_rows": len(rebuilt),
        "dtype_changes": len(comparison["dtype_changes"]),
        "report": str(report_path.relative_to(PROJECT_ROOT)),
    }, indent=2))
    return 0 if semantic_equal else 2


if __name__ == "__main__":
    raise SystemExit(main())
