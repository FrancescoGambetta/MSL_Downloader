from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any, Callable, Optional


class ImageProcessingService:
    def __init__(
        self,
        *,
        project_root: Path,
        translator: Callable[..., str],
        normalize_text: Callable[[Any], str],
        norm_ascii: Callable[[str], str],
        load_json: Callable[..., Any],
        track_saved_output_file: Callable[[str], Any],
    ) -> None:
        self._project_root = project_root
        self._t = translator
        self._normalize_text = normalize_text
        self._norm_ascii = norm_ascii
        self._load_json = load_json
        self._track_saved_output_file = track_saved_output_file

        self._mastcam_bayer_pipeline_cache: Any = None
        self._mastcam_bayer_pipeline_error: str | None = None

    def mardi_geometric_correction_enabled(self, default_value: bool) -> bool:
        return bool(default_value)

    def mardi_side_by_side_enabled(self, default_value: bool) -> bool:
        return bool(default_value)

    def mardi_legacy_mode_enabled(self, default_value: bool) -> bool:
        return bool(default_value)

    def apply_mardi_geometric_correction(
        self,
        image_path: Path,
        *,
        side_by_side: bool,
    ) -> tuple[bool, Optional[Path], Optional[Path], dict[str, Any]]:
        try:
            import numpy as np  # type: ignore
        except Exception:
            return False, None, None, {}
        try:
            from PIL import Image  # type: ignore
        except Exception:
            return False, None, None, {}

        try:
            im = Image.open(image_path).convert("RGB")
            arr = np.asarray(im, dtype=np.float32)
            h, w = arr.shape[:2]
            if h < 80 or w < 80:
                return False, None, None, {}

            yy, xx = np.indices((h, w), dtype=np.float32)
            cx = (w - 1) * 0.5
            cy = (h - 1) * 0.5
            x = (xx - cx) / max(cx, 1.0)
            y = (yy - cy) / max(cy, 1.0)
            r2 = x * x + y * y

            scale_x = 1.0 + 0.26 * (y * y) + 0.05 * r2
            scale_y = 1.0 + 0.03 * r2
            xs = cx + (xx - cx) / scale_x
            ys = cy + (yy - cy) / scale_y

            xs = np.clip(xs, 0, w - 1.001)
            ys = np.clip(ys, 0, h - 1.001)
            x0 = np.floor(xs).astype(np.int32)
            y0 = np.floor(ys).astype(np.int32)
            x1 = np.clip(x0 + 1, 0, w - 1)
            y1 = np.clip(y0 + 1, 0, h - 1)
            dx = (xs - x0)[..., None]
            dy = (ys - y0)[..., None]

            Ia = arr[y0, x0]
            Ib = arr[y0, x1]
            Ic = arr[y1, x0]
            Id = arr[y1, x1]
            top = Ia * (1.0 - dx) + Ib * dx
            bottom = Ic * (1.0 - dx) + Id * dx
            corrected = top * (1.0 - dy) + bottom * dy

            out = np.clip(corrected, 0, 255).astype(np.uint8)

            top_crop = int(h * 0.09)
            bottom_crop = int(h * 0.09)
            left_crop = int(w * 0.03)
            right_crop = int(w * 0.03)
            if (h - top_crop - bottom_crop) > 40 and (w - left_crop - right_crop) > 40:
                out = out[top_crop : h - bottom_crop, left_crop : w - right_crop]

            saved_orig: Optional[Path] = None
            saved_corr: Optional[Path] = None
            if side_by_side:
                orig_path = image_path.with_name(f"{image_path.stem}_orig{image_path.suffix}")
                corr_path = image_path.with_name(f"{image_path.stem}_corr{image_path.suffix}")
                if not orig_path.exists():
                    orig_path.write_bytes(image_path.read_bytes())
                Image.fromarray(out).save(corr_path, format="JPEG", quality=95, subsampling=0)
                saved_orig = orig_path
                saved_corr = corr_path
            else:
                Image.fromarray(out).save(image_path, format="JPEG", quality=95, subsampling=0)
                saved_corr = image_path

            crop_applied = (h - top_crop - bottom_crop) > 40 and (w - left_crop - right_crop) > 40
            details = {
                "version": "mardi-crop-v1",
                "dewarp_enabled": True,
                "dewarp_formula": {"scale_x": "1 + 0.26*y^2 + 0.05*r2", "scale_y": "1 + 0.03*r2"},
                "crop": {
                    "applied": bool(crop_applied),
                    "percent_top": 0.09,
                    "percent_bottom": 0.09,
                    "percent_left": 0.03,
                    "percent_right": 0.03,
                    "pixels_top": int(top_crop),
                    "pixels_bottom": int(bottom_crop),
                    "pixels_left": int(left_crop),
                    "pixels_right": int(right_crop),
                },
                "input_size": {"width": int(w), "height": int(h)},
                "output_size": {"width": int(out.shape[1]), "height": int(out.shape[0])},
                "side_by_side_saved": bool(side_by_side),
                "notes": "Empirical 2D dewarp + border crop applied to reduce visible MARDI curvature. This is a visual correction, not a photogrammetric camera recalibration.",
            }
            return True, saved_orig, saved_corr, details
        except Exception:
            return False, None, None, {}

    def write_mardi_processing_metadata(self, meta_path: Path, details: dict[str, Any]) -> None:
        if not meta_path.exists() or not meta_path.is_file() or not details:
            return
        try:
            obj = json.loads(meta_path.read_text(encoding="utf-8"))
            if not isinstance(obj, dict):
                return
            obj["mardi_processing"] = {
                "cropped_default_mode": True,
                "description": "MARDI images are saved in cropped-corrected mode by default.",
                "applied": details,
            }
            meta_path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception:
            return

    def maybe_correct_mardi_products(
        self,
        records: list[dict[str, Any]],
        *,
        output_dir: str | Path,
        enabled: bool,
        side_by_side: bool,
    ) -> tuple[int, int]:
        if not enabled:
            return 0, 0
        out_dir = Path(output_dir).expanduser()
        corrected = 0
        saved_extras = 0
        for rec in records:
            cam = self._norm_ascii(self._normalize_text(rec.get("camera")))
            if cam != "mardi":
                continue
            product_id = self._normalize_text(rec.get("product_id")) or Path(self._normalize_text(rec.get("img_url"))).stem
            if not product_id:
                continue
            jpg = out_dir / f"{product_id}.jpg"
            if jpg.exists() and jpg.is_file():
                ok, saved_orig, saved_corr, details = self.apply_mardi_geometric_correction(jpg, side_by_side=side_by_side)
                if ok:
                    corrected += 1
                    if saved_orig is not None:
                        self._track_saved_output_file(saved_orig.name)
                        saved_extras += 1
                    if saved_corr is not None and saved_corr != jpg:
                        self._track_saved_output_file(saved_corr.name)
                        saved_extras += 1
                    meta_path = out_dir / f"{product_id}.meta.json"
                    self.write_mardi_processing_metadata(meta_path, details)
        return corrected, saved_extras

    def is_raw_archive_mastcam_record(self, rec: dict[str, Any], *, normalize_source: Callable[[Any], str]) -> bool:
        src_ok = normalize_source(rec.get("source")) == "raw"
        cam_ok = self._norm_ascii(self._normalize_text(rec.get("camera"))).lower() == "mastcam"
        url = self._normalize_text(rec.get("img_url")).lower()
        raw_url_ok = "mars.nasa.gov" in url and ("raw-images" in url or "raw_image_items" in url)
        return bool(src_ok and cam_ok and raw_url_ok)

    def load_mastcam_bayer_pipeline(self) -> tuple[Any, Path] | tuple[None, None]:
        if self._mastcam_bayer_pipeline_cache is not None:
            return self._mastcam_bayer_pipeline_cache, self._project_root / "config" / "mastcam_bayer_config.json"

        try:
            if str(self._project_root) not in sys.path:
                sys.path.insert(0, str(self._project_root))
            mod = importlib.import_module("core.mastcam_bayer_cli")
            cfg_path = self._project_root / "config" / "mastcam_bayer_config.json"
            raw_cfg = self._load_json(cfg_path)
            if not isinstance(raw_cfg, dict):
                raw_cfg = {}
            base = mod.MastcamConfig()

            grid = raw_cfg.get("clahe_grid", list(base.clahe_grid))
            if not isinstance(grid, (list, tuple)) or len(grid) != 2:
                grid = list(base.clahe_grid)
            try:
                clahe_grid = (int(grid[0]), int(grid[1]))
            except Exception:
                clahe_grid = base.clahe_grid

            cfg = mod.MastcamConfig(
                best_pattern=str(raw_cfg.get("best_pattern", base.best_pattern)).upper(),
                final_sigma=float(raw_cfg.get("final_sigma", base.final_sigma)),
                wb_strength=float(raw_cfg.get("wb_strength", base.wb_strength)),
                flat_threshold=float(raw_cfg.get("flat_threshold", base.flat_threshold)),
                chroma_sigma=float(raw_cfg.get("chroma_sigma", base.chroma_sigma)),
                chroma_blend=float(raw_cfg.get("chroma_blend", base.chroma_blend)),
                color_replace_sigma=float(raw_cfg.get("color_replace_sigma", base.color_replace_sigma)),
                green_neutralize=float(raw_cfg.get("green_neutralize", base.green_neutralize)),
                clahe_clip=float(raw_cfg.get("clahe_clip", base.clahe_clip)),
                clahe_grid=clahe_grid,
                gamma=float(raw_cfg.get("gamma", base.gamma)),
                debayer_profile=str(raw_cfg.get("debayer_profile", base.debayer_profile)).lower(),
                superpixel_upscale=bool(raw_cfg.get("superpixel_upscale", base.superpixel_upscale)),
            )
            pipe = mod.MastcamBayerPipeline(cfg)
            self._mastcam_bayer_pipeline_cache = pipe
            self._mastcam_bayer_pipeline_error = None
            return pipe, cfg_path
        except Exception as exc:
            self._mastcam_bayer_pipeline_error = f"{type(exc).__name__}: {exc}"
            return None, None

    def apply_mastcam_bayer_raw_processing(
        self,
        rec: dict[str, Any],
        *,
        output_dir: str | Path,
        normalize_source: Callable[[Any], str],
    ) -> tuple[bool, str]:
        try:
            from PIL import Image  # type: ignore
        except Exception:
            return False, "PIL_missing"

        if not self.is_raw_archive_mastcam_record(rec, normalize_source=normalize_source):
            return False, "not_raw_archive_mastcam"

        img_url = self._normalize_text(rec.get("img_url"))
        if not img_url:
            return False, "img_url_missing"

        image_path = Path(output_dir).expanduser() / Path(img_url).name
        if not image_path.exists() or not image_path.is_file():
            return False, "downloaded_image_missing"

        pipe, cfg_path = self.load_mastcam_bayer_pipeline()
        if pipe is None:
            err = self._normalize_text(self._mastcam_bayer_pipeline_error)
            if err:
                return False, f"pipeline_unavailable:{err}"
            return False, "pipeline_unavailable"

        try:
            raw_gray = pipe.load_raw_as_gray(image_path)
            rgb = pipe.process(raw_gray)
            Image.fromarray(rgb).save(image_path, format="JPEG", quality=95, subsampling=0)
            return True, f"ok:{cfg_path}"
        except Exception as exc:
            return False, f"processing_error:{exc}"

    def convert_jpg_to_png_keep_exif(self, jpg_path: Path) -> Optional[Path]:
        try:
            from PIL import Image  # type: ignore
        except Exception:
            return None
        if not jpg_path.exists() or not jpg_path.is_file():
            return None
        if jpg_path.suffix.lower() not in {".jpg", ".jpeg"}:
            return None
        png_path = jpg_path.with_suffix(".png")
        if png_path.exists() and png_path.is_file():
            try:
                if png_path.stat().st_size > 0:
                    return png_path
            except Exception:
                pass
        try:
            img = Image.open(jpg_path)
            exif_bytes = img.info.get("exif")
            if exif_bytes:
                img.save(png_path, format="PNG", exif=exif_bytes)
            else:
                img.save(png_path, format="PNG")
            self._track_saved_output_file(png_path.name)
            return png_path
        except Exception:
            return None

    def finalize_product_jpg_only(self, out_dir: Path, product_id: str) -> None:
        pid = self._normalize_text(product_id)
        if not pid:
            return
        png_path = out_dir / f"{pid}.png"
        if png_path.exists() and png_path.is_file():
            try:
                png_path.unlink(missing_ok=True)
            except Exception:
                return

    def decode_pds_array(self, img_bytes: bytes, lbl_text: str) -> Optional[Any]:
        try:
            module = importlib.import_module("core.engine_pipeline")
            decoder = getattr(module, "_decode_pds_image_array", None)
            if decoder is None:
                return None
            return decoder(img_bytes, lbl_text)
        except Exception:
            return None

    def augment_meta_with_alpha_pair(
        self,
        *,
        meta_path: Path,
        pair_product_id: str,
        pair_img_url: str,
        pair_lbl_url: str,
        rgba_path: Optional[Path] = None,
        mask_path: Optional[Path] = None,
        coverage: float,
        alpha_nonzero: int,
        alpha_zero: int,
    ) -> None:
        if not meta_path.exists() or not meta_path.is_file():
            return
        try:
            obj = json.loads(meta_path.read_text(encoding="utf-8"))
            if not isinstance(obj, dict):
                return
            obj["alpha_pair"] = {
                "kind": "mxylf",
                "pair_product_id": pair_product_id,
                "pair_img_url": pair_img_url,
                "pair_lbl_url": pair_lbl_url,
                "rgba_path": str(rgba_path) if rgba_path is not None else "",
                "mask_path": str(mask_path) if mask_path is not None else "",
                "mask_coverage": float(coverage),
                "alpha_nonzero": int(alpha_nonzero),
                "alpha_zero": int(alpha_zero),
            }
            post = obj.get("post_processing")
            if not isinstance(post, dict):
                post = {}
            post["mxylf_alpha_applied"] = True
            post["mxylf_alpha_pair_product_id"] = pair_product_id
            post["mxylf_alpha_rgba_path"] = str(rgba_path) if rgba_path is not None else ""
            if mask_path is not None:
                post["mxylf_alpha_mask_path"] = str(mask_path)
            obj["post_processing"] = post
            meta_path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception:
            return

    def apply_alpha_pair_rgba_for_record(
        self,
        rec: dict[str, Any],
        *,
        output_dir: Path,
        session: Any,
        record_product_id: Callable[[dict[str, Any]], str],
    ) -> tuple[bool, str]:
        try:
            import numpy as np  # type: ignore
        except Exception:
            return False, "pil_or_numpy_unavailable"
        try:
            from PIL import Image  # type: ignore
        except Exception:
            return False, "pil_or_numpy_unavailable"

        pair_img_url = self._normalize_text(rec.get("pair_img_url"))
        if not pair_img_url:
            return False, "pair_missing"
        pair_lbl_url = self._normalize_text(rec.get("pair_lbl_url"))
        pair_pid = self._normalize_text(rec.get("pair_product_id")) or Path(pair_img_url).stem
        product_id = record_product_id(rec) or Path(self._normalize_text(rec.get("img_url"))).stem
        if not product_id:
            return False, "product_id_missing"
        base_jpg = output_dir / f"{product_id}.jpg"
        if not base_jpg.exists():
            return False, "base_jpg_missing"

        pair_img_path = output_dir / Path(pair_img_url).name
        pair_lbl_path = output_dir / Path(pair_lbl_url).name if pair_lbl_url else None

        try:
            if not pair_img_path.exists() or pair_img_path.stat().st_size <= 0:
                r = session.get(pair_img_url, timeout=120)
                r.raise_for_status()
                pair_img_path.write_bytes(r.content)
            if pair_lbl_url and pair_lbl_path is not None and (not pair_lbl_path.exists() or pair_lbl_path.stat().st_size <= 0):
                r = session.get(pair_lbl_url, timeout=120)
                r.raise_for_status()
                pair_lbl_path.write_bytes(r.content)
            lbl_text = ""
            if pair_lbl_path is not None and pair_lbl_path.exists():
                lbl_text = pair_lbl_path.read_text(encoding="utf-8", errors="ignore")
            if not lbl_text:
                return False, "pair_lbl_missing"

            img_bytes = pair_img_path.read_bytes()
            arr = self.decode_pds_array(img_bytes, lbl_text)
            if arr is None:
                return False, "mask_decode_unavailable"
            arr_np = np.asarray(arr)
            if arr_np.ndim != 2:
                return False, f"mask_bad_ndim:{arr_np.ndim}"
            min_val = float(np.nanmin(arr_np))
            mask_bin = arr_np > min_val
            coverage = float(mask_bin.mean())

            keep_u8 = np.where(mask_bin, 0, 255).astype(np.uint8)

            base_img = Image.open(base_jpg)
            w, h = base_img.size
            base_img.close()

            if keep_u8.shape[:2] != (h, w):
                resized = Image.fromarray(keep_u8, mode="L").resize((w, h), Image.NEAREST)
                keep_u8 = np.asarray(resized).astype(np.uint8)
                mask_bin = np.asarray(resized) > 0

            mask_path = output_dir / f"{product_id}_mask.png"
            Image.fromarray(keep_u8, mode="L").save(mask_path)
            self._track_saved_output_file(mask_path.name)

            meta_path = output_dir / f"{product_id}.meta.json"
            self.augment_meta_with_alpha_pair(
                meta_path=meta_path,
                pair_product_id=pair_pid,
                pair_img_url=pair_img_url,
                pair_lbl_url=pair_lbl_url,
                mask_path=mask_path,
                coverage=coverage,
                alpha_nonzero=int((keep_u8 > 0).sum()),
                alpha_zero=int((keep_u8 == 0).sum()),
            )
            return True, "ok"
        except Exception as exc:
            return False, f"mask_error:{exc}"
        finally:
            try:
                if pair_img_path.exists():
                    pair_img_path.unlink(missing_ok=True)
            except Exception:
                pass
            try:
                if pair_lbl_path is not None and pair_lbl_path.exists():
                    pair_lbl_path.unlink(missing_ok=True)
            except Exception:
                pass

    def apply_optional_alpha_pair_processing(
        self,
        records: list[dict[str, Any]],
        *,
        output_dir: Path,
        record_product_id: Callable[[dict[str, Any]], str],
        progress_emit: Optional[Callable[[str], None]] = None,
    ) -> tuple[int, int]:
        candidates = [r for r in records if self._normalize_text(r.get("pair_img_url"))]
        if not candidates:
            return 0, 0

        try:
            import requests  # type: ignore
        except Exception:
            return 0, len(candidates)

        ok_count = 0
        skip_count = 0
        with requests.Session() as session:
            session.headers.update({"User-Agent": "dwnapp-alpha-pair/1.0"})
            for idx, rec in enumerate(candidates, start=1):
                product_id = record_product_id(rec) or Path(self._normalize_text(rec.get("img_url"))).stem
                if progress_emit:
                    progress_emit(f"[alpha_pair] {idx}/{len(candidates)} building MASK for {product_id}")
                ok, _reason = self.apply_alpha_pair_rgba_for_record(rec, output_dir=output_dir, session=session, record_product_id=record_product_id)
                if ok:
                    ok_count += 1
                else:
                    skip_count += 1
        return ok_count, skip_count

    def apply_raw_archive_hardcoded_exif(
        self,
        records: list[dict[str, Any]],
        *,
        output_dir: Path,
        progress_emit: Optional[Callable[[str], None]] = None,
    ) -> tuple[int, int]:
        if not records:
            return 0, 0
        try:
            import piexif  # type: ignore
        except Exception:
            return 0, 0
        try:
            from core.default_camera_meta import defaults_for_record  # type: ignore
            from core.engine_pipeline import _build_piexif_bytes_for_metashape  # type: ignore
        except Exception:
            return 0, 0

        applied = 0
        skipped = 0
        for rec in records:
            img_url = self._normalize_text(rec.get("img_url"))
            if not img_url:
                continue
            p = output_dir / Path(img_url).name
            if p.suffix.lower() not in {".jpg", ".jpeg"} or not p.exists():
                continue

            try:
                ex = piexif.load(str(p))
                focal_existing = (ex.get("Exif") or {}).get(piexif.ExifIFD.FocalLength)
                if focal_existing:
                    skipped += 1
                    continue
            except Exception:
                pass

            pid = self._normalize_text(rec.get("product_id")) or Path(img_url).stem
            defaults = defaults_for_record(
                camera=self._normalize_text(rec.get("camera")),
                instrument_id=self._normalize_text(rec.get("instrument_id")),
                product_id=pid,
            )
            try:
                focal_mm = float(defaults.get("focal_length_mm")) if defaults.get("focal_length_mm") is not None else None
            except Exception:
                focal_mm = None
            try:
                px_um = float(defaults.get("pixel_size_um")) if defaults.get("pixel_size_um") is not None else None
            except Exception:
                px_um = None

            if focal_mm is None:
                skipped += 1
                continue

            fp_res = None
            if px_um and px_um > 0:
                fp_res = 10000.0 / px_um

            try:
                exif_bytes = _build_piexif_bytes_for_metashape(
                    focal_length_mm=focal_mm,
                    focal_plane_x_resolution=fp_res,
                    focal_plane_y_resolution=fp_res,
                    focal_plane_resolution_unit=3,
                    latitude=None,
                    longitude=None,
                    altitude=None,
                )
                piexif.insert(exif_bytes, str(p))
                applied += 1
                if progress_emit:
                    progress_emit(f"[raw_exif] applied: {p.name}")
            except Exception:
                skipped += 1
        return applied, skipped

    def write_raw_archive_meta(
        self,
        records: list[dict[str, Any]],
        *,
        output_dir: Path,
        rover_csv_url: str,
        rover_csv_local_path: str,
        engine_version: str,
        normalize_source: Callable[[Any], str],
        progress_emit: Optional[Callable[[str], None]] = None,
    ) -> tuple[int, int]:
        if not records:
            return 0, 0
        try:
            from core.default_camera_meta import defaults_for_record  # type: ignore
            from core.metashape_engine import MatchInfo, PdsProduct, build_meta_payload, write_meta_json  # type: ignore
        except Exception:
            return 0, 0

        _SCLK_SOL_SCALE = 88775.244
        _SCLK_SOL_OFFSET = 4477.74496

        def _extract_sclk(rec: dict[str, Any], product_id: str, img_url: str) -> Optional[int]:
            raw = rec.get("sclk")
            if raw is None:
                raw = rec.get("clock")
            try:
                if raw is not None and str(raw).strip():
                    return int(raw)
            except Exception:
                pass
            import re

            for text in (product_id, Path(img_url).stem):
                m = re.search(r"_(\d{6,12})EDR_", str(text))
                if m:
                    try:
                        return int(m.group(1))
                    except Exception:
                        pass
            return None

        def _sol_from_sclk(sclk: Optional[int]) -> Optional[int]:
            if not sclk or sclk <= 0:
                return None
            sol_est = (float(sclk) / float(_SCLK_SOL_SCALE)) - float(_SCLK_SOL_OFFSET)
            if not (sol_est > -1000 and sol_est < 200000):
                return None
            try:
                return int(round(sol_est))
            except Exception:
                return None

        def _write_one(rec: dict[str, Any]) -> bool:
            img_url = self._normalize_text(rec.get("img_url"))
            if not img_url:
                return False
            jpg_path = output_dir / Path(img_url).name
            if not jpg_path.exists():
                return False

            product_id = self._normalize_text(rec.get("product_id")) or Path(img_url).stem
            if not product_id:
                return False

            meta_path = output_dir / f"{product_id}.meta.json"
            if meta_path.exists() and meta_path.stat().st_size > 0:
                return False

            defaults = defaults_for_record(
                camera=self._normalize_text(rec.get("camera")),
                instrument_id=self._normalize_text(rec.get("instrument_id")),
                product_id=product_id,
            )
            focal_mm = None
            px_um = None
            try:
                focal_mm = float(defaults.get("focal_length_mm")) if defaults.get("focal_length_mm") is not None else None
            except Exception:
                focal_mm = None
            try:
                px_um = float(defaults.get("pixel_size_um")) if defaults.get("pixel_size_um") is not None else None
            except Exception:
                px_um = None
            fp_res = (10000.0 / px_um) if (px_um and px_um > 0) else None

            exif_written: dict[str, Any] = {}
            if focal_mm is not None:
                exif_written["FocalLength"] = focal_mm
            if fp_res is not None:
                exif_written["FocalPlaneXResolution"] = fp_res
                exif_written["FocalPlaneYResolution"] = fp_res
                exif_written["FocalPlaneResolutionUnit"] = 3

            raw_sol = rec.get("sol")
            sol_val: Optional[int] = None
            try:
                sol_val = int(raw_sol) if str(raw_sol).strip().isdigit() else None
            except Exception:
                sol_val = None

            sclk_val = _extract_sclk(rec, product_id, img_url)
            if sol_val is None:
                sol_val = _sol_from_sclk(sclk_val)

            warnings = ["raw_archive:no_lbl"]
            if sol_val is not None and str(raw_sol).strip() == "":
                warnings.append("raw_archive:sol_from_sclk")

            product = PdsProduct(
                product_id=product_id,
                image_id=self._normalize_text(rec.get("image_id")) or None,
                instrument_id=self._normalize_text(rec.get("instrument_id")) or None,
                instrument_name=self._normalize_text(rec.get("instrument_name")) or None,
                sol=sol_val,
                site=None,
                drive=None,
                pose=None,
                sclk=sclk_val,
                start_time=self._normalize_text(rec.get("start_time")) or None,
                image_time=self._normalize_text(rec.get("image_time")) or None,
                img_url=img_url,
                lbl_url="",
                base_url=self._normalize_text(rec.get("data_root")) or None,
            )
            match_info = MatchInfo(
                strategy="raw_archive_no_lbl",
                gps_found=False,
                csv_refreshed=False,
                csv_match_count=0,
                frame=None,
            )
            payload = build_meta_payload(
                product=product,
                lbl_text="",
                csv_row=None,
                match_info=match_info,
                img_url=img_url,
                lbl_url="",
                rover_csv_url=rover_csv_url,
                rover_csv_local_path=str(rover_csv_local_path),
                output_jpg=str(jpg_path),
                output_meta_json=str(meta_path),
                exif_written=exif_written,
                warnings=warnings,
                errors=[],
                engine_version=engine_version,
            )
            if self.is_raw_archive_mastcam_record(rec, normalize_source=normalize_source):
                payload["processing"] = {
                    "mastcam_bayer_applied": bool(rec.get("_mastcam_bayer_applied", False)),
                    "mastcam_bayer_reason": self._normalize_text(rec.get("_mastcam_bayer_reason")) or "not_run",
                }
            write_meta_json(payload, meta_path)
            self._track_saved_output_file(meta_path.name)
            if progress_emit:
                progress_emit(f"[raw meta] written: {meta_path.name}")
            return True

        written = 0
        skipped = 0
        for rec in records:
            try:
                if _write_one(rec):
                    written += 1
                else:
                    skipped += 1
            except Exception:
                skipped += 1
        return written, skipped
