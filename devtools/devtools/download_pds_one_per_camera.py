import argparse
from pathlib import Path
from typing import Any

import sys
import pandas as pd


def _norm(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _pick_one(
    df: pd.DataFrame,
    *,
    camera: str,
    prefer_sol_min: int | None,
    prefer_sol_max: int | None,
) -> dict[str, Any] | None:
    cam_mask = df["camera"].astype(str).str.strip().str.lower().eq(str(camera).lower())
    sub = df[cam_mask].copy()
    if len(sub) == 0:
        return None
    sub = sub[sub["img_url"].astype(str).str.len() > 0].copy()
    sub = sub[sub["lbl_url"].astype(str).str.len() > 0].copy()
    if len(sub) == 0:
        return None

    # Prefer a sol window if provided.
    if prefer_sol_min is not None and "sol" in sub.columns:
        sub_sol = pd.to_numeric(sub["sol"], errors="coerce")
        lo = float(prefer_sol_min)
        hi = float(prefer_sol_max) if prefer_sol_max is not None else lo
        in_win = sub[(sub_sol >= min(lo, hi)) & (sub_sol <= max(lo, hi))].copy()
        if len(in_win):
            sub = in_win

    # Deterministic: pick smallest sol, then lexicographically smallest product_id/img_url.
    if "sol" in sub.columns:
        sub["__sol"] = pd.to_numeric(sub["sol"], errors="coerce").fillna(1e18)
    else:
        sub["__sol"] = 1e18
    if "product_id" not in sub.columns:
        sub["product_id"] = sub["img_url"].astype(str).str.rsplit("/", n=1).str[-1].str.replace(r"\.(?:IMG|img)$", "", regex=True)
    sub = sub.sort_values(["__sol", "product_id", "img_url"], kind="mergesort")
    row = sub.iloc[0].to_dict()
    row.pop("__sol", None)
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="data/catalog/Catalog_PDS.parquet", help="PDS parquet catalog path.")
    ap.add_argument("--out-dir", default="test_output_cfg/pds_one_per_camera", help="Output folder.")
    ap.add_argument("--prefer-sol-min", type=int, default=720, help="Preferred sol window start.")
    ap.add_argument("--prefer-sol-max", type=int, default=750, help="Preferred sol window end.")
    ap.add_argument(
        "--cameras",
        default="mastcam,navcam,hazcam,mahli,mardi",
        help="Comma-separated camera keys.",
    )
    args = ap.parse_args()

    catalog_path = Path(args.catalog)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(str(catalog_path), columns=["product_id", "camera", "sol", "sol_url", "img_url", "lbl_url"])
    # Ensure expected columns exist.
    for c in ("product_id", "camera", "sol", "sol_url", "img_url", "lbl_url"):
        if c not in df.columns:
            df[c] = ""

    cameras = [c.strip() for c in _norm(args.cameras).split(",") if c.strip()]
    picks: list[dict[str, Any]] = []
    for cam in cameras:
        row = _pick_one(
            df,
            camera=cam,
            prefer_sol_min=int(args.prefer_sol_min) if args.prefer_sol_min is not None else None,
            prefer_sol_max=int(args.prefer_sol_max) if args.prefer_sol_max is not None else None,
        )
        if row is None:
            print(f"[skip] {cam}: no suitable PDS records found")
            continue
        picks.append(row)
        pid = _norm(row.get("product_id")) or Path(_norm(row.get("img_url"))).stem
        sol = row.get("sol")
        print(f"[pick] {cam}: sol={sol} product_id={pid}")

    if not picks:
        raise SystemExit("No cameras selected or no records found.")

    # Process with the same core engine used by the app.
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from core.engine_pipeline import process_products_from_catalog  # type: ignore

    # Geo CSV settings match the app defaults.
    rover_csv_url = "https://planetarydata.jpl.nasa.gov/w10n/msl/msl_places/data_localizations/localized_interp_demv2.csv"
    rover_csv_local_path = Path("data/reference/geo/localized_interp_demv2.csv").resolve()

    for row in picks:
        cam = _norm(row.get("camera")).lower() or "camera"
        pid = _norm(row.get("product_id")) or Path(_norm(row.get("img_url"))).stem
        cam_dir = out_dir / cam
        cam_dir.mkdir(parents=True, exist_ok=True)
        rec = {
            "img_url": _norm(row.get("img_url")),
            "lbl_url": _norm(row.get("lbl_url")),
            "base_url": _norm(row.get("sol_url")) or None,
        }
        results = process_products_from_catalog(
            catalog=[rec],
            output_dir=cam_dir,
            rover_csv_url=rover_csv_url,
            rover_csv_local_path=rover_csv_local_path,
            engine_version="sample-one-per-camera",
            progress_callback=None,
        )
        ok = len(results) == 1 and getattr(results[0], "status", "") in {"ok", "ok_with_missing_gps"}
        print(f"[done] {cam}: {pid} ok={ok}")


if __name__ == "__main__":
    main()
