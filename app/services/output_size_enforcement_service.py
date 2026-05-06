from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


class OutputSizeEnforcementService:
    def __init__(
        self,
        *,
        project_root: Path,
        load_json: Callable[..., Any],
        camera_folder_for_filename: Callable[[str], str],
        refresh_saved_output_files: Callable[[], Any],
    ) -> None:
        self._project_root = project_root
        self._load_json = load_json
        self._camera_folder_for_filename = camera_folder_for_filename
        self._refresh_saved_output_files = refresh_saved_output_files

    def mastcam_min_output_size_bytes(self) -> int:
        try:
            cfg = self._load_json(self._project_root / "config" / "camera_rules.json")
            if isinstance(cfg, dict):
                mastcam = cfg.get("mastcam", {})
                if isinstance(mastcam, dict):
                    val = mastcam.get("min_img_size_bytes")
                    if val is None:
                        rules = mastcam.get("rules", {})
                        if isinstance(rules, dict):
                            pds = rules.get("pds", {})
                            if isinstance(pds, dict):
                                val = pds.get("min_img_size_bytes")
                    if val is not None:
                        return max(0, int(float(val)))
        except Exception:
            pass
        return 102400

    def enforce_mastcam_min_output_size(self, output_dir: str | Path) -> int:
        threshold = self.mastcam_min_output_size_bytes()
        if threshold <= 0:
            return 0
        out_dir = Path(output_dir).expanduser()
        if not out_dir.exists() or not out_dir.is_dir():
            return 0
        removed = 0
        for p in out_dir.glob("*.jpg"):
            if not p.is_file():
                continue
            if self._camera_folder_for_filename(p.name) != "MASTCAM":
                continue
            try:
                size = p.stat().st_size
            except Exception:
                continue
            if size >= threshold:
                continue
            meta = p.with_name(f"{p.stem}.meta.json")
            try:
                p.unlink(missing_ok=True)
                if meta.exists() and meta.is_file():
                    meta.unlink(missing_ok=True)
                removed += 1
            except Exception:
                continue
        if removed > 0:
            self._refresh_saved_output_files()
        return removed

    def enforce_global_min_output_size(self, output_dir: str | Path, threshold: int) -> int:
        if threshold <= 0:
            return 0
        out_dir = Path(output_dir).expanduser()
        if not out_dir.exists() or not out_dir.is_dir():
            return 0
        removed = 0
        image_exts = {".jpg", ".jpeg", ".png", ".img", ".tif", ".tiff"}
        for p in out_dir.iterdir():
            if not p.is_file():
                continue
            if p.suffix.lower() == ".png" and p.name.lower().endswith("_mask.png"):
                continue
            if p.suffix.lower() not in image_exts:
                continue
            try:
                size = int(p.stat().st_size)
            except Exception:
                continue
            if size >= threshold:
                continue
            meta = p.with_name(f"{p.stem}.meta.json")
            try:
                p.unlink(missing_ok=True)
                if meta.exists() and meta.is_file():
                    meta.unlink(missing_ok=True)
                removed += 1
            except Exception:
                continue
        if removed > 0:
            self._refresh_saved_output_files()
        return removed

