#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from core.make_msl_catalog import (  # type: ignore
        CAMERA_CONFIG_DEFAULT,
        DEFAULT_RETRIES,
        DEFAULT_TIMEOUT,
        PDSClient,
        PDS_MSL_BASE_URL,
        STOP_EVENT,
        _enrich_with_lbl_and_geo,
        _emit,
        _ensure_geo_csv_and_parquet,
        _install_controls,
        _load_geo_table,
        _load_json,
        _resolve_path,
        _select_lbl_candidates,
        _size_text_to_bytes,
        _write_json,
        _write_parquet,
        discover_collections_for_camera,
        discover_sol_locations,
        scan_products_in_sol,
    )
except Exception:  # pragma: no cover
    from make_msl_catalog import (  # type: ignore
        CAMERA_CONFIG_DEFAULT,
        DEFAULT_RETRIES,
        DEFAULT_TIMEOUT,
        PDSClient,
        PDS_MSL_BASE_URL,
        STOP_EVENT,
        _enrich_with_lbl_and_geo,
        _emit,
        _ensure_geo_csv_and_parquet,
        _install_controls,
        _load_geo_table,
        _load_json,
        _resolve_path,
        _select_lbl_candidates,
        _size_text_to_bytes,
        _write_json,
        _write_parquet,
        discover_collections_for_camera,
        discover_sol_locations,
        scan_products_in_sol,
    )


DEFAULT_PRE3000_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "pre3000_catalog_config.json"

PRE3000_SELECTION_RULES_FALLBACK: dict[str, Any] = {
    "raw_global_rules": {
        "drop_filename_contains_any": ["THUMBNAIL"],
    },
    "mastcam": {
        "filter_key": "pre3000_mastcam_only_e01",
        "rules": {
            "pds": {
                "suffix_equals_any": ["DRCL"],
                "filename_contains_any": ["E01", "E1_"],
                "min_img_size_bytes": 102400,
            }
        },
    },
    "mahli": {
        "filter_key": "pre3000_mahli_only_drcl",
        "rules": {
            "pds": {
                "suffix_equals_any": ["DRCL"],
            }
        },
    },
    "mardi": {
        "filter_key": "pre3000_mardi_only_e01",
        "rules": {
            "pds": {
                "suffix_equals_any": ["DRCL"],
                "filename_contains_any": ["E01", "E01_"],
                "min_img_size_bytes": 102400,
            }
        },
    },
}


def _norm_ascii(text: str) -> str:
    return (
        text.lower()
        .replace("à", "a")
        .replace("á", "a")
        .replace("â", "a")
        .replace("ä", "a")
        .replace("è", "e")
        .replace("é", "e")
        .replace("ê", "e")
        .replace("ë", "e")
        .replace("ì", "i")
        .replace("í", "i")
        .replace("î", "i")
        .replace("ï", "i")
        .replace("ò", "o")
        .replace("ó", "o")
        .replace("ô", "o")
        .replace("ö", "o")
        .replace("ù", "u")
        .replace("ú", "u")
        .replace("û", "u")
        .replace("ü", "u")
        .replace("ß", "ss")
    )


def _normalize_text(value: Any) -> str:
    return _norm_ascii(str(value).strip()) if value is not None else ""


def _sanitize_output_tag(value: str) -> str:
    txt = _normalize_text(value)
    out = []
    for ch in txt:
        if ch.isalnum() or ch in {"-", "_"}:
            out.append(ch)
        elif ch in {" ", "."}:
            out.append("_")
    tag = "".join(out).strip("_")
    return tag


def _with_output_tag(path: Path, tag: str) -> Path:
    return path.with_name(f"{path.stem}_{tag}{path.suffix}")


def _load_rules(cfg: dict[str, Any]) -> dict[str, Any]:
    raw = cfg.get("selection_rules")
    if isinstance(raw, dict) and raw:
        return raw
    return dict(PRE3000_SELECTION_RULES_FALLBACK)


def _camera_rule_items(rules_cfg: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    if not isinstance(rules_cfg, dict):
        return []
    reserved = {"raw_global_rules", "version", "schema_version", "cameras"}
    out: list[tuple[str, dict[str, Any]]] = []
    nested = rules_cfg.get("cameras")
    if isinstance(nested, dict):
        for k, v in nested.items():
            if isinstance(v, dict):
                out.append((str(k), v))
    for k, v in rules_cfg.items():
        if k in reserved:
            continue
        if isinstance(v, dict):
            out.append((str(k), v))
    return out


def _legacy_pds_constraints(rule: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "suffix_equals_any",
        "filename_prefix_any",
        "filename_contains_all",
        "filename_contains_any",
        "min_img_size_bytes",
        "min_img_size_exempt_markers_any",
    )
    out: dict[str, Any] = {}
    for k in keys:
        if k in rule:
            out[k] = rule.get(k)
    return out


def _source_constraints(rule: dict[str, Any], source_name: str) -> tuple[str, dict[str, Any]] | None:
    filter_key_default = _normalize_text(rule.get("filter_key"))
    rules_block = rule.get("rules")
    if isinstance(rules_block, dict):
        src_rule = rules_block.get(source_name)
        if not isinstance(src_rule, dict):
            return None
        filter_key = (
            _normalize_text(src_rule.get("apply_when_filter_key"))
            or _normalize_text(src_rule.get("filter_key"))
            or filter_key_default
        )
        return filter_key, src_rule

    if source_name == "pds":
        legacy = _legacy_pds_constraints(rule)
        if not legacy:
            return None
        return filter_key_default, legacy
    return None


def _record_matches_constraints(record: dict[str, Any], constraints: dict[str, Any]) -> bool:
    img_name = str(record.get("img_name", "")).upper()
    product_id = str(record.get("product_id", "")).upper()

    suffix_any = [str(x).upper() for x in (constraints.get("suffix_equals_any") or []) if _normalize_text(x)]
    if suffix_any:
        suffix = product_id.rsplit("_", 1)[-1] if "_" in product_id else product_id
        if suffix not in suffix_any:
            return False

    prefix_any = [str(x).upper() for x in (constraints.get("filename_prefix_any") or []) if _normalize_text(x)]
    if prefix_any and not img_name.startswith(tuple(prefix_any)):
        return False

    contains_all = [str(x).upper() for x in (constraints.get("filename_contains_all") or []) if _normalize_text(x)]
    for tok in contains_all:
        if tok not in img_name:
            return False

    contains_any = [str(x).upper() for x in (constraints.get("filename_contains_any") or []) if _normalize_text(x)]
    if contains_any and not any(tok in img_name for tok in contains_any):
        return False

    min_img_size_bytes = constraints.get("min_img_size_bytes")
    if min_img_size_bytes is not None:
        try:
            threshold = float(min_img_size_bytes)
        except Exception:
            threshold = -1.0
        if threshold >= 0:
            size_value = record.get("img_size_bytes")
            size_bytes = int(size_value) if isinstance(size_value, int) else _size_text_to_bytes(str(size_value or ""))
            if size_bytes is None or size_bytes < threshold:
                exempt_markers = [
                    str(x).upper()
                    for x in (constraints.get("min_img_size_exempt_markers_any") or [])
                    if _normalize_text(x)
                ]
                if not exempt_markers or not any(mk in img_name for mk in exempt_markers):
                    return False
    return True


def _record_is_allowed(camera: str, record: dict[str, Any], rules_cfg: dict[str, Any]) -> tuple[bool, str]:
    raw_rules = rules_cfg.get("raw_global_rules", {}) if isinstance(rules_cfg, dict) else {}
    if isinstance(raw_rules, dict):
        drop_tokens = [str(x).upper() for x in (raw_rules.get("drop_filename_contains_any") or []) if _normalize_text(x)]
        if drop_tokens:
            img_name = str(record.get("img_name", "")).upper()
            if any(tok in img_name for tok in drop_tokens):
                return False, f"raw_drop:{','.join(drop_tokens)}"

    cam_key = _norm_ascii(camera)
    rule = None
    for cam_name, cam_rule in _camera_rule_items(rules_cfg):
        if _norm_ascii(cam_name) == cam_key:
            rule = cam_rule
            break
    if rule is None:
        return False, f"missing_rule:{camera}"

    resolved = _source_constraints(rule, "pds")
    if resolved is None:
        return False, f"missing_pds_rule:{camera}"
    filter_key, constraints = resolved
    if filter_key and not bool(rule.get("enabled", True)):
        return False, f"disabled:{filter_key}"

    if not _record_matches_constraints(record, constraints):
        return False, f"rule_miss:{filter_key or camera}"
    return True, filter_key or camera


def _filter_products_for_pre3000(
    camera: str,
    products: list[dict[str, Any]],
    rules_cfg: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    reasons: dict[str, int] = {}
    for rec in products:
        ok, reason = _record_is_allowed(camera, rec, rules_cfg)
        if ok:
            kept.append(rec)
        else:
            reasons[reason] = reasons.get(reason, 0) + 1
    return kept, reasons


def _build_fingerprint(
    base_url: str,
    cameras: list[str],
    sol_start: Optional[int],
    sol_end: Optional[int],
    rules_cfg: dict[str, Any],
) -> str:
    return json.dumps(
        {
            "base_url": base_url,
            "cameras": sorted(cameras),
            "rules": rules_cfg,
            "sol_end": sol_end,
            "sol_start": sol_start,
        },
        sort_keys=True,
    )


def _resolve_requested_cameras(args: argparse.Namespace, cfg: dict[str, Any], rules_cfg: dict[str, Any]) -> list[str]:
    requested = args.cameras or cfg.get("default_cameras") or list(CAMERA_CONFIG_DEFAULT.keys())
    available_rule_cameras = {_norm_ascii(name) for name, _ in _camera_rule_items(rules_cfg)}
    cameras: list[str] = []
    unknown: list[str] = []
    for cam in requested:
        if _norm_ascii(str(cam)) in available_rule_cameras:
            cameras.append(str(cam))
        else:
            unknown.append(str(cam))
    if unknown:
        raise ValueError(f"Unsupported cameras for pre3000 builder: {unknown}. Available rules: {sorted(available_rule_cameras)}")
    return cameras


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Build/update a pre-3000 MSL catalog using camera-specific keep rules.")
    ap.add_argument("--config", default=str(DEFAULT_PRE3000_CONFIG_PATH), help="Config JSON path")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--cameras", nargs="+", default=None)
    ap.add_argument("--output", default=None)
    ap.add_argument("--parquet-output", default=None)
    ap.add_argument(
        "--output-tag",
        default=None,
        help="Append a tag to output filenames to avoid overwriting (e.g. navcam_20260421).",
    )
    ap.add_argument("--coord-url", default=None)
    ap.add_argument("--coord-local-path", default=None)
    ap.add_argument("--coord-parquet-path", default=None)
    ap.add_argument("--timeout", type=int, default=None)
    ap.add_argument("--retries", type=int, default=None)
    ap.add_argument("--sol-start", type=int, default=None)
    ap.add_argument("--sol-end", type=int, default=None)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--min-img-size-bytes-for-lbl", type=int, default=None)
    ap.add_argument("--checkpoint-every-products", type=int, default=None)
    ap.add_argument("--checkpoint-write-parquet", action="store_true")
    ap.add_argument("--refresh-sol-index", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    return ap.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    _install_controls()

    cfg_path = Path(args.config).expanduser().resolve()
    cfg: dict[str, Any] = _load_json(cfg_path, {}) if cfg_path.exists() else {}
    rules_cfg = _load_rules(cfg)

    project_root = Path(__file__).resolve().parent.parent

    base_url = args.base_url or cfg.get("base_url") or PDS_MSL_BASE_URL
    timeout = int(args.timeout if args.timeout is not None else cfg.get("timeout", DEFAULT_TIMEOUT))
    retries = int(args.retries if args.retries is not None else cfg.get("retries", DEFAULT_RETRIES))

    try:
        cameras = _resolve_requested_cameras(args, cfg, rules_cfg)
    except ValueError as exc:
        _emit("error", str(exc))
        return 1

    output_path = _resolve_path(project_root, args.output or cfg.get("output"), "data/catalog/catalog_pre3000.json")
    parquet_output_path = _resolve_path(
        project_root,
        args.parquet_output or cfg.get("parquet_output"),
        "data/catalog/catalog_pre3000.parquet",
    )
    if args.output_tag:
        tag = _sanitize_output_tag(str(args.output_tag))
        if not tag:
            _emit("error", f"Invalid --output-tag value: {args.output_tag!r}")
            return 1
        output_path = _with_output_tag(output_path, tag)
        parquet_output_path = _with_output_tag(parquet_output_path, tag)
        _emit(
            "output_tag",
            f"Using tagged outputs: json={output_path.name} parquet={parquet_output_path.name}",
        )

    coord_url = args.coord_url or cfg.get("coord_url")
    coord_local_path = _resolve_path(
        project_root,
        args.coord_local_path or cfg.get("coord_local_path"),
        "data/reference/geo/localized_interp_demv2.csv",
    )
    coord_parquet_path = _resolve_path(
        project_root,
        args.coord_parquet_path or cfg.get("coord_parquet_path"),
        "data/reference/geo/localized_interp_demv2.parquet",
    )

    sol_start = args.sol_start if args.sol_start is not None else cfg.get("sol_start")
    sol_end = args.sol_end if args.sol_end is not None else cfg.get("sol_end", 1500)
    min_img_size = int(
        args.min_img_size_bytes_for_lbl
        if args.min_img_size_bytes_for_lbl is not None
        else cfg.get("min_img_size_bytes_for_lbl", 51200)
    )
    checkpoint_every = int(
        args.checkpoint_every_products
        if args.checkpoint_every_products is not None
        else cfg.get("checkpoint_every_products", 1000)
    )
    checkpoint_write_parquet = bool(args.checkpoint_write_parquet or cfg.get("checkpoint_write_parquet", False))

    cam_cfg = cfg.get("camera_config") if isinstance(cfg.get("camera_config"), dict) else CAMERA_CONFIG_DEFAULT
    if not isinstance(cam_cfg, dict):
        cam_cfg = CAMERA_CONFIG_DEFAULT

    unknown = [c for c in cameras if c not in cam_cfg]
    if unknown:
        _emit("error", f"Unknown cameras requested: {unknown}. Allowed: {sorted(cam_cfg)}")
        return 1

    client = PDSClient(timeout=timeout, retries=retries)

    coord_downloaded_now = False
    coord_updated_now = False
    coord_sync_reason = "disabled"
    geo_table: dict[tuple[int, int], dict[str, Any]] = {}

    if coord_url:
        coord_downloaded_now, coord_updated_now, coord_sync_reason = _ensure_geo_csv_and_parquet(
            client=client,
            project_root=project_root,
            coord_url=coord_url,
            coord_local_path=coord_local_path,
            coord_parquet_path=coord_parquet_path,
        )
        geo_table = _load_geo_table(coord_local_path)

    existing_catalog = _load_json(output_path, {}) if output_path.exists() else {}

    catalog: dict[str, Any] = {
        "catalog_version": 2,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mission": "MSL",
        "base_url": base_url,
        "coord_url": coord_url,
        "coord_local_path": str(coord_local_path.relative_to(project_root))
        if coord_local_path.is_relative_to(project_root)
        else str(coord_local_path),
        "coord_downloaded_now": coord_downloaded_now,
        "coord_updated_now": coord_updated_now,
        "coord_sync_reason": coord_sync_reason,
        "cameras": {},
    }

    if isinstance(existing_catalog, dict) and isinstance(existing_catalog.get("cameras"), dict):
        for cam, payload in existing_catalog["cameras"].items():
            if cam in cameras and isinstance(payload, dict):
                products = payload.get("products", [])
                if isinstance(products, list):
                    catalog["cameras"][cam] = {
                        "product_count": len(products),
                        "products": products,
                    }

    for cam in cameras:
        if cam not in catalog["cameras"]:
            catalog["cameras"][cam] = {"product_count": 0, "products": []}

    existing_img_urls: set[str] = set()
    for cam in cameras:
        for p in catalog["cameras"][cam]["products"]:
            img_url = p.get("img_url")
            if img_url:
                existing_img_urls.add(str(img_url))

    state_path = output_path.with_suffix(output_path.suffix + ".state.json")
    fp = _build_fingerprint(base_url, list(cameras), sol_start, sol_end, rules_cfg)
    state = _load_json(state_path, {}) if state_path.exists() else {}
    if not isinstance(state, dict) or state.get("fingerprint") != fp or args.refresh_sol_index:
        state = {"fingerprint": fp, "scanned_sol_urls": []}
    scanned_sol_urls: set[str] = set(state.get("scanned_sol_urls") or [])

    def checkpoint(reason: str, write_parquet: bool) -> None:
        for cam in cameras:
            catalog["cameras"][cam]["product_count"] = len(catalog["cameras"][cam]["products"])
        catalog["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
        _write_json(output_path, catalog)
        state_payload = {
            "fingerprint": fp,
            "scanned_sol_urls": sorted(scanned_sol_urls),
            "saved_at_utc": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
        }
        _write_json(state_path, state_payload)
        if write_parquet:
            rows = _write_parquet(catalog, parquet_output_path)
            _emit("checkpoint", f"reason={reason} | parquet_rows={rows}")
        else:
            _emit("checkpoint", f"reason={reason} | json_saved")

    new_items_total = 0

    for camera in cameras:
        if STOP_EVENT.is_set():
            _emit("stop", "Interruzione richiesta: stop build catalog")
            break

        cconf = cam_cfg[camera]
        token = cconf.get("collection_token")
        data_roots = cconf.get("data_roots", [])

        _emit("camera_discover_start", f"{camera}: discovering collections matching {token}")
        collections = discover_collections_for_camera(client, base_url, str(token))
        _emit("camera_discover_done", f"{camera}: found {len(collections)} collections")

        all_sols: list[Any] = []
        for idx, coll in enumerate(collections, start=1):
            if STOP_EVENT.is_set():
                break
            _emit("camera_sol_scan", f"{camera}: [{idx}/{len(collections)}] scanning SOL directories in {coll}")
            all_sols.extend(discover_sol_locations(client, base_url, coll, data_roots))

        unique_sols = sorted(
            {
                (s.collection, s.data_root, s.sol, s.sol_dir_name, s.sol_url): s
                for s in all_sols
            }.values(),
            key=lambda s: (s.sol, s.collection, s.data_root, s.sol_url),
        )

        if sol_start is not None:
            unique_sols = [s for s in unique_sols if s.sol >= int(sol_start)]
        if sol_end is not None:
            unique_sols = [s for s in unique_sols if s.sol <= int(sol_end)]

        products_new_camera: list[dict[str, Any]] = []

        total_sols = len(unique_sols)
        for i, loc in enumerate(unique_sols, start=1):
            if STOP_EVENT.is_set():
                _emit("stop", f"{camera}: stop richiesto durante scan prodotti")
                break

            if loc.sol_url in scanned_sol_urls:
                continue

            _emit(
                "camera_product_scan",
                f"{camera}: [{i}/{total_sols}] indexing SOL {loc.sol} ({loc.collection})",
            )
            found = scan_products_in_sol(client, loc, base_url)
            kept, drop_reasons = _filter_products_for_pre3000(camera, found, rules_cfg)
            if drop_reasons:
                drop_desc = ", ".join(f"{k}={v}" for k, v in sorted(drop_reasons.items()))
                _emit(
                    "camera_filter",
                    f"{camera}: SOL {loc.sol} ({loc.collection}) kept {len(kept)}/{len(found)} | dropped: {drop_desc}",
                )
            else:
                _emit(
                    "camera_filter",
                    f"{camera}: SOL {loc.sol} ({loc.collection}) kept {len(kept)}/{len(found)}",
                )

            added_now = 0
            for rec in kept:
                img_url = str(rec.get("img_url", ""))
                if not img_url or img_url in existing_img_urls:
                    continue
                existing_img_urls.add(img_url)
                catalog["cameras"][camera]["products"].append(rec)
                products_new_camera.append(rec)
                new_items_total += 1
                added_now += 1

                if checkpoint_every > 0 and (new_items_total % checkpoint_every == 0):
                    checkpoint(reason=f"every_{checkpoint_every}", write_parquet=checkpoint_write_parquet)
                    _emit("catalog_live", f"items={new_items_total} -> {output_path}")

            scanned_sol_urls.add(loc.sol_url)
            if added_now:
                _emit("catalog_live", f"items={new_items_total} -> {output_path}")

        if STOP_EVENT.is_set():
            _emit("stop", "Interruzione richiesta: stop arricchimento geografico")
            continue

        _emit("camera_geo_enrich", f"{camera}: enriching products with geography")
        candidates = _select_lbl_candidates(products_new_camera, min_img_size)
        _enrich_with_lbl_and_geo(client, products_new_camera, candidates, geo_table)

    checkpoint(reason="final", write_parquet=True)

    if STOP_EVENT.is_set():
        _emit("stop", "Interruzione richiesta: stop build catalog")

    final_rows = _write_parquet(catalog, parquet_output_path)

    _emit("done", f"catalog written to: {output_path}")
    _emit("done", f"new items added: {new_items_total}")
    _emit("done", f"parquet written to: {parquet_output_path}")
    _emit("done", f"dataframe rows: {final_rows}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
