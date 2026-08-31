"""Per-record output-path helpers: source bucket resolution, PDS/RAW/lbl splitting, and skip-if-already-downloaded detection."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable


class RecordOutputUtilsService:
    """Small stateless helpers used while preparing/running a download+process batch (source routing, dedupe-by-completion, size formatting)."""

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
        """Format a byte count as a short human string (e.g. "1.23MB", "512KB", "42B")."""
        val = float(size_bytes)
        if val >= 1024 * 1024 * 1024:
            return f"{val / (1024 * 1024 * 1024):.2f}GB"
        if val >= 1024 * 1024:
            return f"{val / (1024 * 1024):.2f}MB"
        if val >= 1024:
            return f"{val / 1024:.0f}KB"
        return f"{int(val)}B"

    def normalize_source(self, value: Any) -> str:
        """Normalize a record's "source" field to exactly "pds" or "raw" (anything else/unrecognized defaults to "pds")."""
        src = self._norm_ascii(self._normalize_text(value)).lower()
        return "raw" if src == "raw" else "pds"

    def output_dir_for_source(self, base_output_path: str | Path, source: str) -> Path:
        """Return (and create) the `PDS/` or `RAW_PHOTOS/` subfolder of `base_output_path` for `source`, or `base_output_path` itself if it's already named that bucket."""
        base = Path(base_output_path).expanduser()
        bucket = "RAW_PHOTOS" if self.normalize_source(source) == "raw" else "PDS"
        if base.name.upper() == bucket:
            out = base
        else:
            out = base / bucket
        out.mkdir(parents=True, exist_ok=True)
        return out

    def split_records_by_source(self, records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Split `records` into `(pds_records, raw_records)` by their normalized source."""
        pds_records: list[dict[str, Any]] = []
        raw_records: list[dict[str, Any]] = []
        for rec in records:
            if self.normalize_source(rec.get("source")) == "raw":
                raw_records.append(rec)
            else:
                pds_records.append(rec)
        return pds_records, raw_records

    def split_records_by_lbl(self, records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Split `records` into `(with_lbl, without_lbl)` by whether they have a non-empty `lbl_url`."""
        with_lbl: list[dict[str, Any]] = []
        without_lbl: list[dict[str, Any]] = []
        for rec in records:
            if self._normalize_text(rec.get("lbl_url")):
                with_lbl.append(rec)
            else:
                without_lbl.append(rec)
        return with_lbl, without_lbl

    def record_product_id(self, rec: dict[str, Any]) -> str:
        """Return `rec`'s product_id, or the stem of its img_url if product_id is missing."""
        pid = self._normalize_text(rec.get("product_id"))
        if pid:
            return pid
        img_url = self._normalize_text(rec.get("img_url"))
        return Path(img_url).stem if img_url else ""

    def filter_completed_records(
        self,
        records: list[dict[str, Any]],
        base_output_path: str | Path,
    ) -> tuple[list[dict[str, Any]], int]:
        """Exclude records whose final image already exists in the chosen output.

        Build one recursive, source-aware index of final image stems. PDS and RAW
        are indexed separately so an equally named product in one source cannot
        suppress a product from the other source.
        """
        base = Path(base_output_path).expanduser()
        final_exts = {".jpg", ".jpeg", ".png"}
        completed: dict[str, set[str]] = {"pds": set(), "raw": set()}

        for source, bucket_name in (("pds", "PDS"), ("raw", "RAW_PHOTOS")):
            root = base if base.name.upper() == bucket_name else base / bucket_name
            if not root.exists() or not root.is_dir():
                continue
            stack = [str(root)]
            while stack:
                current = stack.pop()
                try:
                    with os.scandir(current) as entries:
                        for entry in entries:
                            try:
                                if entry.is_dir(follow_symlinks=False):
                                    stack.append(entry.path)
                                elif entry.is_file(follow_symlinks=False):
                                    suffix = Path(entry.name).suffix.lower()
                                    if suffix in final_exts and entry.stat().st_size > 0:
                                        completed[source].add(Path(entry.name).stem.casefold())
                            except OSError:
                                continue
                except OSError:
                    continue

        pending: list[dict[str, Any]] = []
        skipped = 0
        for rec in records:
            source = self.normalize_source(rec.get("source"))
            product_id = self.record_product_id(rec).casefold()
            if product_id and product_id in completed[source]:
                skipped += 1
            else:
                pending.append(rec)
        return pending, skipped

    def strip_lbl_for_raw_records(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return a copy of `records` with `lbl_url`/`pair_lbl_url` cleared on RAW Archive rows (RAW has no .LBL files to fetch)."""
        out: list[dict[str, Any]] = []
        for r in records:
            rr = dict(r)
            if self.normalize_source(rr.get("source")) == "raw":
                rr["lbl_url"] = ""
                rr["pair_lbl_url"] = ""
            out.append(rr)
        return out

    def update_meta_outputs_meta_path(self, meta_path: Path) -> None:
        """Rewrite a saved `.meta.json`'s own `outputs.meta_json_path` field to match `meta_path` (used after the organizer moves it)."""
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
