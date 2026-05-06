import argparse
from pathlib import Path
from typing import Any, Optional

import sys
import pandas as pd
import requests
from PIL import Image
import numpy as np


def _norm(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _find_record(product_id: str, catalog_path: Path) -> dict[str, str]:
    df = pd.read_parquet(str(catalog_path), columns=["product_id", "img_url", "lbl_url"])
    pid_u = _norm(product_id).upper()
    sub = df[df["product_id"].astype(str).str.upper() == pid_u]
    if len(sub) == 0:
        raise SystemExit(f"product_id not found in catalog: {product_id}")
    row = sub.iloc[0]
    img_url = _norm(row.get("img_url"))
    lbl_url = _norm(row.get("lbl_url"))
    if not img_url or not lbl_url:
        raise SystemExit("record is missing img_url or lbl_url")
    return {"img_url": img_url, "lbl_url": lbl_url}


def _download(url: str, *, session: requests.Session, timeout: int = 120) -> bytes:
    r = session.get(url, timeout=timeout)
    r.raise_for_status()
    return r.content


def _decode_pds(img_bytes: bytes, lbl_text: str) -> np.ndarray:
    # Reuse the engine's decoder to ensure parity with the app.
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from core.engine_pipeline import _decode_pds_image_array  # type: ignore

    arr = _decode_pds_image_array(img_bytes, lbl_text)
    if arr is None:
        raise RuntimeError("decoder returned None")
    out = np.asarray(arr)
    if out.ndim != 2:
        raise RuntimeError(f"expected 2D mask, got shape={out.shape}")
    return out


def _write_png_u8(path: Path, arr_u8: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr_u8.astype(np.uint8), mode="L").save(path)


def _scale_minmax_to_u8(arr: np.ndarray) -> np.ndarray:
    a = np.asarray(arr)
    if a.size == 0:
        return np.zeros((1, 1), dtype=np.uint8)
    amin = float(np.nanmin(a))
    amax = float(np.nanmax(a))
    if not np.isfinite(amin) or not np.isfinite(amax) or amax <= amin:
        return np.zeros(a.shape, dtype=np.uint8)
    scaled = (a.astype(np.float64) - amin) / (amax - amin)
    return np.clip(np.round(scaled * 255.0), 0, 255).astype(np.uint8)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--product-id", help="Exact MXYLF product_id (preferred).")
    ap.add_argument("--img-url", help="Direct IMG url (if you don't want to query the catalog).")
    ap.add_argument("--lbl-url", help="Direct LBL url (required with --img-url).")
    ap.add_argument("--catalog", default="data/catalog/Catalog_PDS.parquet", help="Parquet catalog path for lookup.")
    ap.add_argument("--out-dir", default="test_output_cfg/mxylf_debug", help="Output folder for PNGs.")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    catalog_path = Path(args.catalog)

    img_url = _norm(args.img_url)
    lbl_url = _norm(args.lbl_url)
    product_id = _norm(args.product_id)

    if product_id:
        rec = _find_record(product_id, catalog_path)
        img_url = rec["img_url"]
        lbl_url = rec["lbl_url"]
    if not img_url or not lbl_url:
        raise SystemExit("provide --product-id or both --img-url and --lbl-url")

    name = Path(img_url).stem
    with requests.Session() as s:
        s.headers.update({"User-Agent": "dwnapp-mxylf-dump/1.0"})
        lbl_text = _download(lbl_url, session=s).decode("utf-8", errors="ignore")
        img_bytes = _download(img_url, session=s)

    arr = _decode_pds(img_bytes, lbl_text)
    amin = float(np.nanmin(arr))
    amax = float(np.nanmax(arr))

    # 1) Raw min-max scaled preview (useful to compare with third-party PNGs).
    scaled_u8 = _scale_minmax_to_u8(arr)
    scaled_path = out_dir / f"{name}.scaled.png"
    _write_png_u8(scaled_path, scaled_u8)

    # 2) Binary mask derived with the same logic used by the app (min value means "masked out").
    bin_u8 = np.where(arr > amin, 255, 0).astype(np.uint8)
    bin_path = out_dir / f"{name}.binary.png"
    _write_png_u8(bin_path, bin_u8)

    print("product:", name)
    print("img_url:", img_url)
    print("lbl_url:", lbl_url)
    print("shape:", arr.shape, "dtype:", arr.dtype)
    print("min/max:", amin, amax)
    print("written:", str(scaled_path))
    print("written:", str(bin_path))


if __name__ == "__main__":
    main()
