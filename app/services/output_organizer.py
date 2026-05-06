from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


@dataclass
class OrganizeResult:
    ok: bool
    message: str
    moved: int = 0
    already: int = 0
    unknown: int = 0
    conflicts: int = 0
    folders: dict[str, int] = field(default_factory=dict)


class OutputOrganizer:
    def __init__(
        self,
        *,
        translator: Callable[..., str],
        refresh_saved_output_files: Callable[[], None],
        camera_folder_for_filename: Callable[[str], str],
        normalize_text: Callable[[str], str],
    ) -> None:
        self._t = translator
        self._refresh_saved_output_files = refresh_saved_output_files
        self._camera_folder_for_filename = camera_folder_for_filename
        self._normalize_text = normalize_text

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
        for bucket in buckets:
            key = self._normalize_text(str(bucket.resolve()))
            if key and key not in seen:
                seen.add(key)
                uniq.append(bucket)
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
            return next((p for p in out_dir.rglob(f"{src.stem}.meta.json") if p.is_file()), None)
        except Exception:
            return None

    def _update_meta_outputs_meta_path(self, meta_path: Path) -> None:
        if not meta_path.exists() or not meta_path.is_file():
            return
        try:
            obj = json.loads(meta_path.read_text(encoding="utf-8", errors="ignore"))
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
            meta_path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            return

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
            for part in (src.parent.name, src.parent.parent.name if src.parent.parent else ""):
                match = re.search(r"\bsol[_\s-]*(\d{1,5})\b", self._normalize_text(part), re.IGNORECASE)
                if match:
                    return int(match.group(1))
        except Exception:
            pass
        match = re.match(r"^(\d{4,5})", src.stem)
        if match:
            try:
                return int(match.group(1))
            except Exception:
                return None
        return None

    def organize_by_camera(self, output_path: str | Path) -> OrganizeResult:
        out = Path(output_path).expanduser()
        if not out.exists() or not out.is_dir():
            return OrganizeResult(False, self._t("output_path_required"))
        image_exts = {".jpg", ".jpeg", ".png"}
        buckets = self.organize_source_buckets(out)
        files: list[tuple[Path, Path]] = []
        for bucket in buckets:
            for path in bucket.rglob("*"):
                if path.is_file() and path.suffix.lower() in image_exts:
                    files.append((bucket, path))
        if not files:
            return OrganizeResult(False, self._t("organize_photos_no_images"))
        moved = 0
        already = 0
        unknown = 0
        conflicts = 0
        by_folder: Counter[str] = Counter()
        for bucket, src in files:
            folder = self._camera_folder_for_filename(src.name)
            if not folder:
                unknown += 1
                continue
            dst_dir = bucket / folder
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / src.name
            if src.parent.resolve() == dst_dir.resolve() or dst_dir in src.parents:
                already += 1
                continue
            if dst.exists():
                conflicts += 1
                continue
            src.replace(dst)
            moved += 1
            meta_src = self.find_output_meta_for_image(src, bucket)
            if meta_src is not None and meta_src.exists() and meta_src.is_file():
                meta_dst = dst_dir / meta_src.name
                try:
                    if meta_src.resolve() != meta_dst.resolve() and not meta_dst.exists():
                        meta_src.replace(meta_dst)
                except Exception:
                    pass
            bucket_label = self._normalize_text(bucket.name) if bucket.resolve() != out.resolve() else "ROOT"
            by_folder[f"{bucket_label}/{folder}"] += 1
        self._refresh_saved_output_files()
        parts = [
            self._t("organize_photos_done"),
            self._t("organize_photos_mode_camera"),
            self._t("organize_photos_moved", value=moved),
            self._t("organize_photos_already", value=already),
            self._t("organize_photos_unknown", value=unknown),
            self._t("organize_photos_conflicts", value=conflicts),
        ]
        if by_folder:
            details = ", ".join(f"{k}:{v}" for k, v in sorted(by_folder.items()))
            parts.append(self._t("organize_photos_folders", value=details))
        return OrganizeResult(True, "\n".join(parts), moved, already, unknown, conflicts, dict(by_folder))

    def organize_simple_layout(
        self,
        output_path: str | Path,
        *,
        divide_by_sol: bool = False,
        divide_by_camera: bool = True,
    ) -> OrganizeResult:
        out = Path(output_path).expanduser()
        if not out.exists() or not out.is_dir():
            return OrganizeResult(False, self._t("output_path_required"))

        if not divide_by_sol and not divide_by_camera:
            return OrganizeResult(True, "Organize: no options enabled (nothing to move). Enable 'Divide by camera type' and/or 'Divide by SOL'.")

        image_exts = {".jpg", ".jpeg", ".png"}
        pds_exts = {".img", ".lbl"}  # only for MXYLF mask products (PDS)

        def is_meta_json_name(name: str) -> bool:
            return self._normalize_text(name).lower().endswith(".meta.json")

        def extract_sol_from_meta_path(meta_path: Path) -> Optional[int]:
            if not meta_path.exists() or not meta_path.is_file():
                return None
            try:
                obj = json.loads(meta_path.read_text(encoding="utf-8", errors="ignore"))
                if not isinstance(obj, dict):
                    return None
                if obj.get("sol") is not None:
                    return int(float(obj.get("sol")))
                prod = obj.get("product")
                if isinstance(prod, dict) and prod.get("sol") is not None:
                    return int(float(prod.get("sol")))
            except Exception:
                return None
            return None

        def nearby_meta_for_image(src: Path, root: Path) -> Optional[Path]:
            cand = src.with_name(f"{src.stem}.meta.json")
            if cand.exists() and cand.is_file():
                return cand
            cand2 = root / f"{src.stem}.meta.json"
            if cand2.exists() and cand2.is_file():
                return cand2
            cand3 = root / "metadata" / f"{src.stem}.meta.json"
            if cand3.exists() and cand3.is_file():
                return cand3
            return None

        def extract_sol_fast(src: Path) -> Optional[int]:
            meta = nearby_meta_for_image(src, src.parent)
            if meta is not None:
                sol = extract_sol_from_meta_path(meta)
                if sol is not None:
                    return sol
            try:
                for part in (src.parent.name, src.parent.parent.name if src.parent.parent else ""):
                    match = re.search(r"\bsol[_\s-]*(\d{1,5})\b", self._normalize_text(part), re.IGNORECASE)
                    if match:
                        return int(match.group(1))
            except Exception:
                pass
            match = re.match(r"^(\d{4,5})", src.stem)
            if match:
                try:
                    return int(match.group(1))
                except Exception:
                    return None
            return None

        moved = 0
        already = 0
        unknown = 0
        conflicts = 0
        masks = 0
        meta_moved = 0
        by_folder: Counter[str] = Counter()

        def relocate_meta_files_one_level(folder: Path) -> int:
            if not folder.exists() or not folder.is_dir():
                return 0
            meta_dir = folder / "metadata"
            moved_here = 0
            try:
                for meta in folder.glob("*.meta.json"):
                    if not meta.is_file():
                        continue
                    meta_dir.mkdir(parents=True, exist_ok=True)
                    dst = meta_dir / meta.name
                    if dst.exists():
                        continue
                    try:
                        meta.replace(dst)
                        self._update_meta_outputs_meta_path(dst)
                        moved_here += 1
                    except Exception:
                        continue
            except Exception:
                return moved_here
            return moved_here

        scan_roots = [out, out / "PDS", out / "RAW_PHOTOS"]
        any_found = False
        for root in scan_roots:
            if not root.exists() or not root.is_dir():
                continue
            meta_moved += int(relocate_meta_files_one_level(root))
            try:
                for p in root.iterdir():
                    if not p.is_file():
                        continue
                    suf = p.suffix.lower()
                    if suf not in image_exts and suf not in pds_exts and not is_meta_json_name(p.name):
                        continue
                    any_found = True
                    if is_meta_json_name(p.name):
                        continue

                    name_up = self._normalize_text(p.name).upper()
                    cam_folder = self._camera_folder_for_filename(p.name)
                    if not cam_folder:
                        unknown += 1
                        continue

                    if suf in pds_exts:
                        if "MXYLF" in name_up:
                            dst_dir = (root / cam_folder / "Masks") if divide_by_camera else (root / "Masks")
                            dst_dir.mkdir(parents=True, exist_ok=True)
                            dst = dst_dir / p.name
                            if dst.exists():
                                conflicts += 1
                                continue
                            try:
                                p.replace(dst)
                                moved += 1
                                masks += 1
                                by_folder[f"{cam_folder}/Masks" if divide_by_camera else "Masks"] += 1
                            except Exception:
                                conflicts += 1
                            continue
                        already += 1
                        continue

                    sol = extract_sol_fast(p) if divide_by_sol else None
                    if divide_by_sol and sol is None:
                        unknown += 1
                        continue

                    dst_dir = root
                    label_parts: list[str] = []
                    if divide_by_camera and cam_folder:
                        dst_dir = dst_dir / cam_folder
                        label_parts.append(cam_folder)
                    if divide_by_sol and sol is not None:
                        dst_dir = dst_dir / f"sol_{sol}"
                        label_parts.append(f"sol_{sol}")
                    dst_dir.mkdir(parents=True, exist_ok=True)
                    dst = dst_dir / p.name
                    try:
                        if dst.resolve() == p.resolve():
                            already += 1
                            continue
                    except Exception:
                        pass
                    if dst.exists():
                        conflicts += 1
                        continue
                    try:
                        p.replace(dst)
                        moved += 1
                        by_folder["/".join(label_parts) if label_parts else "ROOT"] += 1
                    except Exception:
                        conflicts += 1
                        continue

                    meta_src = nearby_meta_for_image(p, root)
                    if meta_src is not None and meta_src.exists() and meta_src.is_file():
                        meta_dst_dir = dst_dir / "metadata"
                        meta_dst_dir.mkdir(parents=True, exist_ok=True)
                        meta_dst = meta_dst_dir / meta_src.name
                        if not meta_dst.exists():
                            try:
                                meta_src.replace(meta_dst)
                                self._update_meta_outputs_meta_path(meta_dst)
                                meta_moved += 1
                            except Exception:
                                pass

                    mask_src = p.with_name(f"{p.stem}_mask.png")
                    if mask_src.exists() and mask_src.is_file():
                        mask_dst = dst_dir / mask_src.name
                        if not mask_dst.exists():
                            try:
                                mask_src.replace(mask_dst)
                                masks += 1
                            except Exception:
                                pass
            except Exception:
                continue

        if not any_found:
            return OrganizeResult(False, self._t("organize_photos_no_images"))

        self._refresh_saved_output_files()
        parts = [
            self._t("organize_photos_done"),
            f"Mode: divide_by_camera={'yes' if divide_by_camera else 'no'}, divide_by_sol={'yes' if divide_by_sol else 'no'}",
            self._t("organize_photos_moved", value=moved),
            self._t("organize_photos_already", value=already),
            self._t("organize_photos_unknown", value=unknown),
            self._t("organize_photos_conflicts", value=conflicts),
            f"- meta moved into metadata/: {meta_moved}",
            f"- masks moved: {masks}",
        ]
        if by_folder:
            details = ", ".join(f"{k}:{v}" for k, v in sorted(by_folder.items()))
            parts.append(self._t("organize_photos_folders", value=details))
        return OrganizeResult(True, "\n".join(parts), moved, already, unknown, conflicts, dict(by_folder))

    def organize_by_sol(self, output_path: str | Path) -> OrganizeResult:
        out = Path(output_path).expanduser()
        if not out.exists() or not out.is_dir():
            return OrganizeResult(False, self._t("output_path_required"))
        image_exts = {".jpg", ".jpeg", ".png"}
        buckets = self.organize_source_buckets(out)
        files: list[tuple[Path, Path, bool]] = []
        allowed_camera_dirs = {"MASTCAM", "MAHLI", "MARDI", "FHAZ", "RHAZ", "NAV", "CHEMCAM"}
        for bucket in buckets:
            camera_dirs = [
                path for path in bucket.iterdir()
                if path.is_dir() and self._normalize_text(path.name).upper() in allowed_camera_dirs
            ]
            has_camera_dirs = bool(camera_dirs)
            if has_camera_dirs:
                for directory in camera_dirs:
                    for path in directory.rglob("*"):
                        if path.is_file() and path.suffix.lower() in image_exts:
                            files.append((bucket, path, True))
                for path in bucket.iterdir():
                    if path.is_file() and path.suffix.lower() in image_exts:
                        files.append((bucket, path, True))
            else:
                for path in bucket.iterdir():
                    if path.is_file() and path.suffix.lower() in image_exts:
                        files.append((bucket, path, False))
        if not files:
            return OrganizeResult(False, self._t("organize_photos_no_images"))

        def camera_container_for_path(src: Path, bucket: Path) -> str:
            try:
                for parent in src.parents:
                    if parent.parent == bucket and self._normalize_text(parent.name).upper() in allowed_camera_dirs:
                        return self._normalize_text(parent.name).upper()
            except Exception:
                pass
            inferred = self._camera_folder_for_filename(src.name)
            return inferred if inferred in allowed_camera_dirs else ""

        moved = 0
        already = 0
        unknown = 0
        conflicts = 0
        by_folder: Counter[str] = Counter()
        for bucket, src, has_camera_dirs in files:
            sol = self.extract_sol_for_output_file(src, bucket)
            if sol is None:
                unknown += 1
                continue
            sol_folder = f"sol_{sol}"
            if has_camera_dirs:
                cam_folder = camera_container_for_path(src, bucket)
                dst_dir = (bucket / cam_folder / sol_folder) if cam_folder else (bucket / sol_folder)
            else:
                dst_dir = bucket / sol_folder
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / src.name
            if src.resolve() == dst.resolve():
                already += 1
                continue
            if dst.exists():
                conflicts += 1
                continue
            src.replace(dst)
            moved += 1
            by_folder[dst_dir.name] += 1
            meta_src = self.find_output_meta_for_image(src, bucket)
            if meta_src is not None and meta_src.exists() and meta_src.is_file():
                meta_dst = dst_dir / meta_src.name
                try:
                    if meta_src.resolve() != meta_dst.resolve() and not meta_dst.exists():
                        meta_src.replace(meta_dst)
                except Exception:
                    pass
        self._refresh_saved_output_files()
        parts = [
            self._t("organize_photos_done"),
            self._t("organize_photos_mode_sol"),
            self._t("organize_photos_moved", value=moved),
            self._t("organize_photos_already", value=already),
            self._t("organize_photos_unknown", value=unknown),
            self._t("organize_photos_conflicts", value=conflicts),
        ]
        if by_folder:
            details = ", ".join(f"{k}:{v}" for k, v in sorted(by_folder.items()))
            parts.append(self._t("organize_photos_folders", value=details))
        return OrganizeResult(True, "\n".join(parts), moved, already, unknown, conflicts, dict(by_folder))
