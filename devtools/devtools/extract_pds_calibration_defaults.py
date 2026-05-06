import argparse
import json
from pathlib import Path
from typing import Any, Optional


def _norm(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _get_float(fields: dict[str, Any], key: str) -> Optional[float]:
    raw = fields.get(key)
    if raw is None:
        return None
    s = _norm(raw)
    if not s:
        return None
    # values can look like: "14.67 <MM>" or "0.012 <MM>"
    s = s.replace("<MM>", "").replace("<mm>", "").replace("<UM>", "").replace("<um>", "")
    s = s.replace(",", ".").strip()
    for tok in (" ", "\t"):
        if tok in s:
            s = s.split(tok, 1)[0].strip()
    try:
        return float(s)
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--root",
        default="test_output_cfg/pds_one_per_camera",
        help="Folder containing one-per-camera PDS outputs (jpg + meta.json).",
    )
    args = ap.parse_args()

    root = Path(args.root)
    if not root.exists():
        raise SystemExit(f"not found: {root}")

    meta_files = sorted(root.rglob("*.meta.json"))
    if not meta_files:
        raise SystemExit(f"no meta.json found under: {root}")

    rows = []
    for p in meta_files:
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        product = obj.get("product", {}) if isinstance(obj.get("product"), dict) else {}
        fields = obj.get("lbl_fields", {}) if isinstance(obj.get("lbl_fields"), dict) else {}
        camera = _norm(product.get("instrument_id")) or _norm(product.get("instrument_name"))
        focal = _get_float(fields, "FOCAL_LENGTH")
        pixel_pitch = _get_float(fields, "PIXEL_PITCH") or _get_float(fields, "PIXEL_SIZE")
        rows.append(
            {
                "path": str(p),
                "product_id": _norm(product.get("product_id")),
                "instrument_id": _norm(product.get("instrument_id")),
                "camera": _norm(product.get("instrument_name")),
                "focal_length_mm": focal,
                "pixel_pitch_mm": pixel_pitch,
            }
        )

    # Print concise summary, one per instrument_id (first seen).
    seen: set[str] = set()
    for r in rows:
        inst = r.get("instrument_id") or ""
        if inst in seen:
            continue
        seen.add(inst)
        print(
            f"{inst:16} focal_mm={r.get('focal_length_mm')} pixel_pitch_mm={r.get('pixel_pitch_mm')} product_id={r.get('product_id')}"
        )


if __name__ == "__main__":
    main()
