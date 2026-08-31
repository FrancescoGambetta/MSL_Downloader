#!/usr/bin/env python3
"""Unified and atomic PDS catalog builder for all MSL imaging cameras.

The public command is unified, while the two proven discovery strategies stay
separate internally: IMG/LBL for the traditional cameras and TIF/LBL for
ChemCam RMI. Canonical outputs are replaced only after full validation.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from core.make_msl_catalog import _load_json, _write_json, main as build_img_catalog
from core.make_msl_chemcam_catalog import main as build_chemcam_catalog


PROJECT_ROOT = Path(__file__).resolve().parent.parent
STANDARD_CAMERAS = ("mastcam", "mahli", "navcam", "mardi", "hazcam")
ALL_CAMERAS = (*STANDARD_CAMERAS, "chemcam")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse this builder's CLI arguments (mostly pass-through to the underlying standard-camera and ChemCam builders)."""
    parser = argparse.ArgumentParser(description="Build/update the unified MSL PDS catalog")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "msl_catalog_config.json"))
    parser.add_argument("--output", default=str(PROJECT_ROOT / "data" / "catalog" / "Catalog_PDS.json"))
    parser.add_argument("--parquet-output", default=str(PROJECT_ROOT / "data" / "catalog" / "Catalog_PDS.parquet"))
    parser.add_argument("--schema", default=str(PROJECT_ROOT / "config" / "pds_catalog_schema.json"))
    parser.add_argument("--cameras", nargs="+", choices=ALL_CAMERAS, default=list(ALL_CAMERAS))
    parser.add_argument("--sol-start", type=int, default=None)
    parser.add_argument("--sol-end", type=int, default=None)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--timeout", type=int, default=None)
    parser.add_argument("--retries", type=int, default=None)
    parser.add_argument("--min-img-size-bytes-for-lbl", type=int, default=None)
    parser.add_argument("--checkpoint-every-products", type=int, default=None)
    parser.add_argument("--checkpoint-write-parquet", action="store_true")
    parser.add_argument("--refresh-sol-index", action="store_true")
    parser.add_argument("--include-suffixes", nargs="+", default=None)
    parser.add_argument("--include-product-types", nargs="+", default=None)
    parser.add_argument("--include-camera-prefixes", nargs="+", default=None)
    parser.add_argument("--include-processing-markers", nargs="+", default=None)
    parser.add_argument("--use-camera-rules", action="store_true")
    parser.add_argument("--repair-locations-file", default=None)
    parser.add_argument("--refresh-chemcam-sols", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument(
        "--work-dir", default=None,
        help=(
            "Use this directory for the intermediate standard/chemcam scan files instead of a "
            "throwaway temp dir that gets deleted on any exit (including an interrupted scan). "
            "Callers that want a stoppable/resumable run pass the same stable path back in on the "
            "next attempt; the scanner's own checkpoint (inside core.make_msl_catalog) then picks "
            "up where it left off. Cleaned up automatically once a run completes successfully."
        ),
    )
    return parser.parse_args(argv)


def _empty_catalog(source: dict[str, Any]) -> dict[str, Any]:
    """Copy `source`'s top-level metadata (everything except `cameras`) with an empty `cameras` dict."""
    return {
        key: value for key, value in source.items()
        if key != "cameras"
    } | {"cameras": {}}


def _camera_payload(source: dict[str, Any], camera: str) -> dict[str, Any]:
    """Extract `{"product_count": ..., "products": [...]}` for one camera from `source`, or an empty payload if absent."""
    payload = (source.get("cameras") or {}).get(camera, {})
    products = payload.get("products", []) if isinstance(payload, dict) else []
    products = list(products) if isinstance(products, list) else []
    return {"product_count": len(products), "products": products}


def _write_seed(path: Path, source: dict[str, Any], cameras: list[str]) -> None:
    """Write a per-sub-builder working JSON at `path`, containing only `cameras`' existing data from `source` -- the starting point each sub-builder scans forward from."""
    seed = _empty_catalog(source)
    seed["cameras"] = {camera: _camera_payload(source, camera) for camera in cameras}
    _write_json(path, seed)


def _catalog_rows(catalog: dict[str, Any]) -> pd.DataFrame:
    """Flatten `catalog["cameras"]`'s nested products into a flat DataFrame with a `camera` column."""
    rows: list[dict[str, Any]] = []
    for camera, payload in (catalog.get("cameras") or {}).items():
        for product in payload.get("products", []):
            row = dict(product)
            row["camera"] = camera
            rows.append(row)
    return pd.DataFrame(rows)


def _canonical_frame(catalog: dict[str, Any], schema_path: Path) -> pd.DataFrame:
    """Flatten+cast `catalog` to the canonical parquet schema, validating it's non-empty with unique, complete `img_url`/`product_id`/`camera` identities."""
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    specs = schema.get("columns") or []
    columns = [str(item["name"]) for item in specs]
    frame = _catalog_rows(catalog)
    for column in columns:
        if column not in frame:
            frame[column] = pd.NA
    frame = frame[columns]
    if frame.empty:
        raise ValueError("The unified PDS catalog cannot be empty")
    for item in specs:
        name, dtype = str(item["name"]), str(item["dtype"])
        if dtype == "bool":
            frame[name] = frame[name].fillna(False).astype(bool)
        elif dtype == "int64":
            frame[name] = pd.to_numeric(frame[name], errors="raise").astype("int64")
        elif dtype == "Float64":
            frame[name] = pd.to_numeric(frame[name], errors="coerce").astype("Float64")
        else:
            frame[name] = frame[name].astype("string")
    if frame["img_url"].isna().any():
        raise ValueError("Unified PDS catalog contains products without img_url")
    if frame["img_url"].duplicated().any():
        raise ValueError("Unified PDS catalog contains duplicate img_url values")
    if frame["product_id"].isna().any() or frame["camera"].isna().any():
        raise ValueError("Unified PDS catalog contains incomplete canonical identities")
    return frame.sort_values(["camera", "sol", "product_id", "img_url"], kind="stable").reset_index(drop=True)


def _validate_pair(catalog: dict[str, Any], frame: pd.DataFrame) -> None:
    """Cross-check `catalog` (JSON) and `frame` (parquet) agree on row count and that every one of `ALL_CAMERAS` is still present."""
    json_rows = sum(
        len(payload.get("products", []))
        for payload in (catalog.get("cameras") or {}).values()
        if isinstance(payload, dict)
    )
    if json_rows != len(frame):
        raise RuntimeError(f"JSON/Parquet row mismatch: {json_rows} != {len(frame)}")
    expected = set(ALL_CAMERAS)
    present = set(frame["camera"].dropna().astype(str).str.casefold())
    missing = sorted(expected - present)
    if missing:
        raise RuntimeError(f"Unified PDS catalog lost camera sections: {missing}")


def main(
    argv: list[str] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> int:
    """Run the standard-camera and/or ChemCam sub-builders for the requested cameras/Sol range, then merge their results into one validated, atomically-installed unified catalog.

    Each sub-builder scans into its own working JSON/parquet pair under a
    temp (or, with `--work-dir`, a caller-supplied stable) directory,
    seeded from the current catalog's existing data for cameras not being
    touched this run. Returns 2 without writing anything if either
    sub-builder's scan was interrupted (`STOP_EVENT`, checked by both the
    standard-camera and the ChemCam scanner); 0 on success after both JSON
    and the just-written parquet (re-read to confirm) pass
    `_canonical_frame`/`_validate_pair`.
    """
    args = parse_args(argv)
    output = Path(args.output).expanduser().resolve()
    parquet_output = Path(args.parquet_output).expanduser().resolve()
    schema_path = Path(args.schema).expanduser().resolve()
    source = _load_json(output, {})
    if not source or not isinstance(source.get("cameras"), dict):
        raise FileNotFoundError(f"A valid canonical PDS JSON is required: {output}")

    if args.validate_only:
        frame = _canonical_frame(source, schema_path)
        _validate_pair(source, frame)
        print(f"[validated] rows={len(frame)} cameras={','.join(sorted(frame['camera'].unique()))}")
        return 0

    if args.sol_end is None:
        raise ValueError("--sol-end is required for a non-interactive unified update")
    sol_start = 0 if args.sol_start is None else int(args.sol_start)
    selected = list(dict.fromkeys(args.cameras))
    standard_selected = [camera for camera in selected if camera in STANDARD_CAMERAS]

    output.parent.mkdir(parents=True, exist_ok=True)
    stable_work_dir = Path(args.work_dir).expanduser().resolve() if args.work_dir else None
    temp_ctx: tempfile.TemporaryDirectory | None = None
    if stable_work_dir is not None:
        stable_work_dir.mkdir(parents=True, exist_ok=True)
        work = stable_work_dir
    else:
        temp_ctx = tempfile.TemporaryDirectory(prefix="pds-unified-", dir=str(output.parent))
        work = Path(temp_ctx.name)

    try:
        updated_payloads: dict[str, dict[str, Any]] = {}

        if standard_selected:
            standard_json = work / "standard.json"
            standard_parquet = work / "standard.parquet"
            if not standard_json.exists():
                # Fresh attempt (an ephemeral work dir never has this file
                # yet either, so this always runs there too). A resumed
                # attempt with a stable work dir leaves an existing file
                # alone: it already holds whatever an interrupted scan had
                # merged in, and reseeding here would silently discard that
                # progress while the scanner's own checkpoint still thinks
                # those Sols are done.
                _write_seed(standard_json, source, standard_selected)
            standard_args = [
                "--config", str(Path(args.config).expanduser().resolve()),
                "--output", str(standard_json), "--parquet-output", str(standard_parquet),
                "--cameras", *standard_selected,
                "--sol-start", str(sol_start), "--sol-end", str(args.sol_end),
            ]
            if args.workers is not None:
                standard_args += ["--workers", str(args.workers)]
            if args.timeout is not None:
                standard_args += ["--timeout", str(args.timeout)]
            if args.retries is not None:
                standard_args += ["--retries", str(args.retries)]
            if args.min_img_size_bytes_for_lbl is not None:
                standard_args += ["--min-img-size-bytes-for-lbl", str(args.min_img_size_bytes_for_lbl)]
            if args.checkpoint_every_products is not None:
                standard_args += ["--checkpoint-every-products", str(args.checkpoint_every_products)]
            if args.checkpoint_write_parquet:
                standard_args.append("--checkpoint-write-parquet")
            if args.refresh_sol_index:
                standard_args.append("--refresh-sol-index")
            if args.include_suffixes:
                standard_args += ["--include-suffixes", *args.include_suffixes]
            if args.include_product_types:
                standard_args += ["--include-product-types", *args.include_product_types]
            if args.include_camera_prefixes:
                standard_args += ["--include-camera-prefixes", *args.include_camera_prefixes]
            if args.include_processing_markers:
                standard_args += ["--include-processing-markers", *args.include_processing_markers]
            if args.use_camera_rules:
                standard_args.append("--use-camera-rules")
            if args.repair_locations_file:
                standard_args += ["--repair-locations-file", args.repair_locations_file]
            standard_code = build_img_catalog(standard_args, progress_callback=progress_callback)
            if standard_code == 2:
                # Interrupted mid-scan: never build/validate/install a unified
                # catalog from a partial standard-camera result.
                return 2
            if standard_code != 0:
                raise RuntimeError("Traditional PDS camera update failed")
            standard_result = _load_json(standard_json, {})
            for camera in standard_selected:
                updated_payloads[camera] = _camera_payload(standard_result, camera)

        if "chemcam" in selected:
            chemcam_json = work / "chemcam.json"
            chemcam_parquet = work / "chemcam.parquet"
            if not chemcam_json.exists():
                _write_seed(chemcam_json, source, ["chemcam"])
            chemcam_args = [
                "--output", str(chemcam_json), "--parquet-output", str(chemcam_parquet),
                "--sol-start", str(sol_start), "--sol-end", str(args.sol_end),
            ]
            if args.timeout is not None:
                chemcam_args += ["--timeout", str(args.timeout)]
            if args.retries is not None:
                chemcam_args += ["--retries", str(args.retries)]
            if args.refresh_chemcam_sols:
                chemcam_args.append("--refresh-scanned-sols")
            chemcam_code = build_chemcam_catalog(chemcam_args)
            if chemcam_code == 2:
                # Same contract as the standard-camera branch above: an
                # interrupted sub-scan means no unified catalog gets built or
                # installed from a partial result, full stop.
                return 2
            if chemcam_code != 0:
                raise RuntimeError("ChemCam PDS update failed")
            updated_payloads["chemcam"] = _camera_payload(_load_json(chemcam_json, {}), "chemcam")

        unified = dict(source)
        unified["cameras"] = dict(source["cameras"])
        unified["cameras"].update(updated_payloads)
        for camera, payload in unified["cameras"].items():
            payload["product_count"] = len(payload.get("products", []))

        frame = _canonical_frame(unified, schema_path)
        _validate_pair(unified, frame)
        incoming_json = output.with_suffix(output.suffix + ".incoming")
        incoming_parquet = parquet_output.with_suffix(parquet_output.suffix + ".incoming")
        _write_json(incoming_json, unified)
        frame.to_parquet(incoming_parquet, index=False)
        check = pd.read_parquet(incoming_parquet)
        _validate_pair(unified, check)
        os.replace(incoming_json, output)
        os.replace(incoming_parquet, parquet_output)
    finally:
        if temp_ctx is not None:
            temp_ctx.cleanup()
        # A stable work_dir is deliberately NOT cleaned up here: an early
        # `return 2` (interrupted) or a raised exception both reach this
        # finally block too, and the whole point of a stable dir is that a
        # future resume attempt finds the partial scan (and its checkpoint)
        # still there. It is only removed below, once every step above has
        # actually completed and the real catalog has been installed.

    if stable_work_dir is not None:
        shutil.rmtree(stable_work_dir, ignore_errors=True)

    counts = {camera: len(payload.get("products", [])) for camera, payload in unified["cameras"].items()}
    print(f"[done] unified_json={output}")
    print(f"[done] unified_parquet={parquet_output}")
    print(f"[done] rows={sum(counts.values())} cameras={counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
