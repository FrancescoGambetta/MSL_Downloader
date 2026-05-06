#!/usr/bin/env python3
"""
DecodeIMGFromUrl.py

Standalone utility (kept out of the app runtime) to convert PDS3 MSL images:
  - input: .IMG + optional .LBL (local path or URL)
  - output: PNG

Local file usage:
    python devtools/tools/DecodeIMGFromUrl.py file.IMG [file.LBL] -o output.png

URL usage:
    python devtools/tools/DecodeIMGFromUrl.py https://.../image.IMG
    python devtools/tools/DecodeIMGFromUrl.py https://.../image.IMG https://.../image.LBL
    python devtools/tools/DecodeIMGFromUrl.py https://.../image.IMG -o marte.png

If .LBL is not specified, the script tries to fetch it automatically
by swapping the extension in the URL/path.

Dependencies:
  - Pillow is recommended for PNG writing: `pip install Pillow`
"""

from __future__ import annotations

import argparse
import json
import os
import re
import struct
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _resolve_repo_root() -> Path:
    """
    Best-effort repo root resolver so this script can live under `devtools/tools/`.
    Looks for a `config/` folder as an anchor.
    """
    here = Path(__file__).resolve()
    for p in [here.parent, *here.parents]:
        if (p / "config").exists():
            return p
    return here.parent


PROJECT_ROOT = _resolve_repo_root()
PIPELINE_SOURCES_CONFIG_PATH = PROJECT_ROOT / "config" / "pipeline" / "sources.json"


def _load_pipeline_sources() -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "coord_url": "https://planetarydata.jpl.nasa.gov/w10n/msl/msl_places/data_localizations/localized_interp_demv2.csv",
    }
    if not PIPELINE_SOURCES_CONFIG_PATH.exists():
        return defaults
    try:
        data = json.loads(PIPELINE_SOURCES_CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            v = data.get("coord_url")
            if isinstance(v, str) and v.strip():
                defaults["coord_url"] = v.strip()
    except Exception:
        pass
    return defaults


PIPELINE_SOURCES = _load_pipeline_sources()
DEFAULT_COORD_URL = str(PIPELINE_SOURCES.get("coord_url") or "").strip()


def is_url(s: str) -> bool:
    return s.startswith(("http://", "https://", "ftp://"))


def download(url: str, dest: str) -> str:
    """Download URL -> dest. Returns dest."""
    print(f"[DOWN] {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "DecodeIMGFromUrl/1.0 (Python urllib)"})
        with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as out:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            block = 1024 * 256
            while True:
                chunk = resp.read(block)
                if not chunk:
                    break
                out.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded * 100 // total
                    print(f"\r       {downloaded // 1024} / {total // 1024} KB  ({pct}%)", end="", flush=True)
            if total:
                print()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"[ERR]  HTTP {e.code} – {url}")
    except urllib.error.URLError as e:
        raise SystemExit(f"[ERR]  Cannot reach {url}: {e.reason}")
    return dest


def _swap_extension(url_or_path: str, new_ext: str) -> str:
    base = url_or_path.rsplit(".", 1)[0]
    return base + new_ext


def _resolve_file(source: str, tmpdir: str, label: str) -> str:
    if is_url(source):
        filename = os.path.basename(source.split("?")[0]) or label
        dest = os.path.join(tmpdir, filename)
        return download(source, dest)
    if not os.path.isfile(source):
        raise SystemExit(f"[ERR]  File not found: {source}")
    return source


def _auto_lbl(img_source: str, tmpdir: str) -> str | None:
    for ext in (".LBL", ".lbl"):
        candidate = _swap_extension(img_source, ext)
        if is_url(candidate):
            dest = os.path.join(tmpdir, os.path.basename(candidate))
            try:
                return download(candidate, dest)
            except SystemExit:
                continue
        elif os.path.isfile(candidate):
            return candidate
    if not is_url(img_source):
        folder = os.path.dirname(img_source) or "."
        lbls = [f for f in os.listdir(folder) if f.upper().endswith(".LBL")]
        if lbls:
            return os.path.join(folder, lbls[0])
    return None


def parse_lbl(lbl_path: str) -> dict[str, Any]:
    """
    Minimal PDS3 label parser for IMAGE object fields.
    """
    params: dict[str, str] = {}
    in_image_object = False
    with open(lbl_path, "r", errors="replace") as f:
        for line in f:
            stripped = line.strip()
            if re.match(r"^OBJECT\s*=\s*IMAGE\b", stripped, re.IGNORECASE):
                in_image_object = True
                continue
            if re.match(r"^END_OBJECT\s*=\s*IMAGE\b", stripped, re.IGNORECASE):
                in_image_object = False
                continue
            if in_image_object:
                m = re.match(r"^(\w+)\s*=\s*(.+)", stripped)
                if m:
                    params[m.group(1).upper()] = m.group(2).strip().strip('"')

    def _int(name: str, default: int) -> int:
        try:
            return int(str(params.get(name, default)).strip())
        except Exception:
            return default

    bits = _int("SAMPLE_BITS", 16)
    storage = str(params.get("BAND_STORAGE_TYPE", "BAND_SEQUENTIAL")).upper()
    sample_type = str(params.get("SAMPLE_TYPE", "MSB_UNSIGNED_INTEGER")).upper()

    byte_order = "MSB" if "MSB" in sample_type else ("LSB" if "LSB" in sample_type else "MSB")
    signed = "SIGNED" in sample_type

    bit_mask: int | None = None
    raw_mask = str(params.get("SAMPLE_BIT_MASK", "")).strip()
    m2 = re.search(r"2#([01]+)#", raw_mask)
    if m2:
        bit_mask = int(m2.group(1), 2)
    else:
        m3 = re.search(r"0x([0-9A-Fa-f]+)", raw_mask)
        if m3:
            bit_mask = int(m3.group(1), 16)

    return {
        "lines": _int("LINES", 144),
        "samples": _int("LINE_SAMPLES", 160),
        "bands": _int("BANDS", 1),
        "bits": bits,
        "storage": storage,
        "byte_order": byte_order,
        "signed": signed,
        "bit_mask": bit_mask,
        "raw_params": params,
    }


def _dtype_unpacker(bits: int, byte_order: str, signed: bool) -> tuple[str, int]:
    if bits == 8:
        fmt = "b" if signed else "B"
        return fmt, 1
    if bits == 16:
        endian = ">" if byte_order == "MSB" else "<"
        fmt = endian + ("h" if signed else "H")
        return fmt, 2
    raise ValueError(f"Unsupported SAMPLE_BITS={bits} (supported: 8,16)")


def _read_band_sequential(img_path: str, meta: dict[str, Any]) -> list[list[int]]:
    lines = int(meta["lines"])
    samples = int(meta["samples"])
    bands = int(meta["bands"])
    bits = int(meta["bits"])
    byte_order = str(meta["byte_order"])
    signed = bool(meta["signed"])
    bit_mask = meta.get("bit_mask")

    fmt, bpp = _dtype_unpacker(bits, byte_order, signed)
    count = lines * samples
    band_bytes = count * bpp

    out: list[list[int]] = []
    with open(img_path, "rb") as f:
        for _b in range(bands):
            raw = f.read(band_bytes)
            if len(raw) < band_bytes:
                raise ValueError("Unexpected EOF while reading IMG")
            vals = list(struct.unpack(fmt * count if bpp == 1 else fmt[0] + fmt[1:] * count, raw))  # type: ignore[index]
            if bit_mask is not None:
                vals = [int(v) & int(bit_mask) for v in vals]
            out.append([int(v) for v in vals])
    return out


def _to_png(out_path: Path, lines: int, samples: int, bands: int, band_data: list[list[int]]) -> None:
    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover
        raise SystemExit("Pillow is required to write PNG. Install with: pip install Pillow") from exc

    if bands <= 1:
        flat = band_data[0]
        # Normalize to 0..255
        mn = min(flat) if flat else 0
        mx = max(flat) if flat else 1
        scale = 255.0 / float(mx - mn) if mx != mn else 1.0
        pixels = [max(0, min(255, int((v - mn) * scale))) for v in flat]
        im = Image.frombytes("L", (samples, lines), bytes(pixels))
        im.save(out_path)
        return

    # For RGB-like 3 bands, normalize each band independently to 0..255.
    if bands >= 3:
        r, g, b = band_data[0], band_data[1], band_data[2]
        def norm(ch: list[int]) -> list[int]:
            mn = min(ch) if ch else 0
            mx = max(ch) if ch else 1
            scale = 255.0 / float(mx - mn) if mx != mn else 1.0
            return [max(0, min(255, int((v - mn) * scale))) for v in ch]

        rn, gn, bn = norm(r), norm(g), norm(b)
        rgb = bytearray()
        for i in range(lines * samples):
            rgb.extend([rn[i], gn[i], bn[i]])
        im = Image.frombytes("RGB", (samples, lines), bytes(rgb))
        im.save(out_path)
        return

    raise ValueError(f"Unsupported BANDS={bands}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Convert PDS3 .IMG/.LBL to PNG (standalone tool).")
    ap.add_argument("img", help="Path or URL to .IMG file")
    ap.add_argument("lbl", nargs="?", default="", help="Optional path/URL to .LBL file")
    ap.add_argument("-o", "--output", default="", help="Output PNG path")
    args = ap.parse_args()

    img_src = str(args.img)
    lbl_src = str(args.lbl or "")

    with tempfile.TemporaryDirectory(prefix="dwnapp_pds3_") as tmpdir:
        img_path = _resolve_file(img_src, tmpdir, "image.IMG")
        lbl_path = ""
        if lbl_src:
            lbl_path = _resolve_file(lbl_src, tmpdir, "image.LBL")
        else:
            auto = _auto_lbl(img_src, tmpdir)
            if auto:
                lbl_path = auto

        if not lbl_path or not os.path.isfile(lbl_path):
            raise SystemExit("[ERR] .LBL is required (pass it explicitly or make sure auto-detection works).")

        meta = parse_lbl(lbl_path)
        storage = str(meta.get("storage") or "").upper()
        if storage not in {"BAND_SEQUENTIAL", "BAND_SEQUENTIAL "}:
            raise SystemExit(f"[ERR] Unsupported BAND_STORAGE_TYPE={storage} (supported: BAND_SEQUENTIAL)")

        lines = int(meta["lines"])
        samples = int(meta["samples"])
        bands = int(meta["bands"])

        band_data = _read_band_sequential(img_path, meta)

        out_path = Path(args.output).expanduser() if args.output else Path(img_path).with_suffix(".png")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _to_png(out_path, lines, samples, bands, band_data)

        print(f"[OK] IMG : {img_src}")
        print(f"[OK] LBL : {lbl_src or '(auto)'}")
        print(f"[OK] OUT : {out_path}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
