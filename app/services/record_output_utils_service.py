from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional


class RecordOutputUtilsService:
    def __init__(
        self,
        *,
        normalize_text: Callable[[Any], str],
        norm_ascii: Callable[[str], str],
        load_json: Callable[..., Any],
        save_json: Callable[..., Any],
    ) -> None:
        self._normalize_text = normalize_text
        self._norm_ascii = norm_ascii
        self._load_json = load_json
        self._save_json = save_json

    def format_size_short(self, size_bytes: int) -> str:
        val = float(size_bytes)
        if val >= 1024 * 1024 * 1024:
            return f"{val / (1024 * 1024 * 1024):.2f}GB"
        if val >= 1024 * 1024:
            return f"{val / (1024 * 1024):.2f}MB"
        if val >= 1024:
            return f"{val / 1024:.0f}KB"
        return f"{int(val)}B"

    def normalize_source(self, value: Any) -> str:
        src = self._norm_ascii(self._normalize_text(value)).lower()
        return "raw" if src == "raw" else "pds"

    def output_dir_for_source(self, base_output_path: str | Path, source: str) -> Path:
        base = Path(base_output_path).expanduser()
        bucket = "RAW_PHOTOS" if self.normalize_source(source) == "raw" else "PDS"
        if base.name.upper() == bucket:
            out = base
        else:
            out = base / bucket
        out.mkdir(parents=True, exist_ok=True)
        return out

    def split_records_by_source(self, records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        pds_records: list[dict[str, Any]] = []
        raw_records: list[dict[str, Any]] = []
        for rec in records:
            if self.normalize_source(rec.get("source")) == "raw":
                raw_records.append(rec)
            else:
                pds_records.append(rec)
        return pds_records, raw_records

    def split_records_by_lbl(self, records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        with_lbl: list[dict[str, Any]] = []
        without_lbl: list[dict[str, Any]] = []
        for rec in records:
            if self._normalize_text(rec.get("lbl_url")):
                with_lbl.append(rec)
            else:
                without_lbl.append(rec)
        return with_lbl, without_lbl

    def record_product_id(self, rec: dict[str, Any]) -> str:
        pid = self._normalize_text(rec.get("product_id"))
        if pid:
            return pid
        img_url = self._normalize_text(rec.get("img_url"))
        return Path(img_url).stem if img_url else ""

    def strip_lbl_for_raw_records(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for r in records:
            rr = dict(r)
            if self.normalize_source(rr.get("source")) == "raw":
                rr["lbl_url"] = ""
                rr["pair_lbl_url"] = ""
            out.append(rr)
        return out

    def update_meta_outputs_meta_path(self, meta_path: Path) -> None:
        if not meta_path.exists() or not meta_path.is_file():
            return
        try:
            obj = self._load_json(meta_path)
        except Exception:
            return
        if not isinstance(obj, dict):
            return
        outputs = obj.get("outputs")
        if not isinstance(outputs, dict):
            outputs = {}
            obj["outputs"] = outputs
        outputs["meta_json_path"] = str(meta_path)
        try:
            self._save_json(meta_path, obj)
        except Exception:
            return

    def organize_source_buckets(self, out: Path) -> list[Path]:
        buckets: list[Path] = []
        pds = out / "PDS"
        raw = out / "RAW_PHOTOS"
        if pds.exists() and pds.is_dir():
            buckets.append(pds)
        if raw.exists() and raw.is_dir():
            buckets.append(raw)
        image_exts = {".jpg", ".jpeg", ".png"}
        has_root_images = any(p.is_file() and p.suffix.lower() in image_exts for p in out.iterdir())
        if has_root_images or not buckets:
            buckets.insert(0, out)
        uniq: list[Path] = []
        seen: set[str] = set()
        for b in buckets:
            key = self._normalize_text(str(b.resolve()))
            if key and key not in seen:
                seen.add(key)
                uniq.append(b)
        return uniq

    def find_output_meta_for_image(self, src: Path, out_dir: Path) -> Optional[Path]:
        candidates = [
            src.with_name(f"{src.stem}.meta.json"),
            out_dir / f"{src.stem}.meta.json",
        ]
        seen: set[str] = set()
        for candidate in candidates:
            cand_s = self._normalize_text(str(candidate))
            if not cand_s or cand_s in seen:
                continue
            seen.add(cand_s)
            if candidate.exists() and candidate.is_file():
                return candidate
        try:
            found = next((p for p in out_dir.rglob(f"{src.stem}.meta.json") if p.is_file()), None)
            return found
        except Exception:
            return None

    def extract_sol_for_output_file(self, src: Path, out_dir: Path) -> Optional[int]:
        meta_path = self.find_output_meta_for_image(src, out_dir)
        if meta_path is not None:
            try:
                meta_obj = json.loads(meta_path.read_text(encoding="utf-8"))
                if isinstance(meta_obj, dict):
                    sol_val = meta_obj.get("sol")
                    if sol_val is not None:
                        return int(float(sol_val))
            except Exception:
                pass
        try:
            import re

            for part in (src.parent.name, src.parent.parent.name if src.parent.parent else ""):
                m = re.search(r"\bsol[_\s-]*(\d{1,5})\b", self._normalize_text(part), re.IGNORECASE)
                if m:
                    return int(m.group(1))
        except Exception:
            pass
        try:
            import re

            m = re.match(r"^(\d{4,5})", src.stem)
            if m:
                return int(m.group(1))
        except Exception:
            return None
        return None
