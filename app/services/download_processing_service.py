from __future__ import annotations

import inspect
import time
from pathlib import Path
from typing import Any, Callable, Optional


class DownloadProcessingService:
    def __init__(
        self,
        *,
        translator: Callable[..., str],
        normalize_text: Callable[[str], str],
        ensure_writable_download_path: Callable[[str], tuple[bool, str]],
        set_download_path: Callable[[str, bool], str],
        prepare_action_df_with_min_size: Callable[..., tuple[Any, dict[str, int], int]],
        records_from_dataframe: Callable[..., list[dict[str, Any]]],
        attach_optional_alpha_pairs: Callable[..., tuple[list[dict[str, Any]], int]],
        strip_lbl_for_raw_records: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
        output_dir_for_source: Callable[[str | Path, str], Path],
        split_records_by_source: Callable[[list[dict[str, Any]]], tuple[list[dict[str, Any]], list[dict[str, Any]]]],
        split_records_by_lbl: Callable[[list[dict[str, Any]]], tuple[list[dict[str, Any]], list[dict[str, Any]]]],
        display_image_name_from_output_file: Callable[[str], str],
        track_saved_output_file: Callable[[str], None],
        load_json: Callable[[Path], dict[str, Any]],
        resolve_msl_config: Callable[[], Path],
        project_root: Path,
        download_records: Callable[..., dict[str, Any]],
        process_records_with_engine: Callable[..., dict[str, Any]],
        enforce_global_min_output_size: Callable[[str | Path, int], int],
        enforce_mastcam_min_output_size: Callable[[str | Path], int],
        mastcam_min_output_size_bytes: Callable[[], int],
        format_size_short: Callable[[int], str],
        maybe_correct_mardi_products: Callable[[list[dict[str, Any]], str | Path], tuple[int, int]],
        mardi_geometric_correction_enabled: Callable[[], bool],
        mardi_side_by_side_enabled: Callable[[], bool],
        apply_optional_alpha_pair_processing: Callable[..., tuple[int, int]],
        apply_mastcam_bayer_raw_processing: Callable[[dict[str, Any], str | Path], tuple[bool, str]],
        is_raw_archive_mastcam_record: Callable[[dict[str, Any]], bool],
        finalize_product_jpg_only: Callable[[Path, str], None],
        apply_raw_archive_hardcoded_exif: Callable[..., tuple[int, int]],
        write_raw_archive_meta: Callable[..., tuple[int, int]],
    ) -> None:
        self._t = translator
        self._normalize_text = normalize_text
        self._ensure_writable_download_path = ensure_writable_download_path
        self._set_download_path = set_download_path
        self._prepare_action_df_with_min_size = prepare_action_df_with_min_size
        self._records_from_dataframe = records_from_dataframe
        self._attach_optional_alpha_pairs = attach_optional_alpha_pairs
        self._strip_lbl_for_raw_records = strip_lbl_for_raw_records
        self._output_dir_for_source = output_dir_for_source
        self._split_records_by_source = split_records_by_source
        self._split_records_by_lbl = split_records_by_lbl
        self._display_image_name_from_output_file = display_image_name_from_output_file
        self._track_saved_output_file = track_saved_output_file
        self._load_json = load_json
        self._resolve_msl_config = resolve_msl_config
        self._project_root = project_root
        self._download_records = download_records
        self._process_records_with_engine = process_records_with_engine
        self._enforce_global_min_output_size = enforce_global_min_output_size
        self._enforce_mastcam_min_output_size = enforce_mastcam_min_output_size
        self._mastcam_min_output_size_bytes = mastcam_min_output_size_bytes
        self._format_size_short = format_size_short
        self._maybe_correct_mardi_products = maybe_correct_mardi_products
        self._mardi_geometric_correction_enabled = mardi_geometric_correction_enabled
        self._mardi_side_by_side_enabled = mardi_side_by_side_enabled
        self._apply_optional_alpha_pair_processing = apply_optional_alpha_pair_processing
        self._apply_mastcam_bayer_raw_processing = apply_mastcam_bayer_raw_processing
        self._is_raw_archive_mastcam_record = is_raw_archive_mastcam_record
        self._finalize_product_jpg_only = finalize_product_jpg_only
        self._apply_raw_archive_hardcoded_exif = apply_raw_archive_hardcoded_exif
        self._write_raw_archive_meta = write_raw_archive_meta

    def run_download(
        self,
        *,
        requested_path: str,
        all_variants: bool = False,
        progress_emit: Optional[Callable[[str], None]] = None,
        max_images: Optional[int] = None,
        random_sample: bool = False,
        per_camera_limits: Optional[dict[str, int]] = None,
        selection_df: Any = None,
        reference_df: Any = None,
    ) -> str:
        ok_path, path = self._ensure_writable_download_path(requested_path)
        if not ok_path:
            return self._t("output_path_required")
        if path != requested_path:
            self._set_download_path(path, True)
        df, pre_size_stats, min_size_threshold = self._prepare_action_df_with_min_size(
            all_variants=all_variants,
            max_images=max_images,
            random_sample=random_sample,
            per_camera_limits=per_camera_limits,
            require_lbl=False,
            selection_df=selection_df,
        )
        records = self._records_from_dataframe(df, limit=None, require_lbl=False)
        records, paired_candidates = self._attach_optional_alpha_pairs(records, reference_df=reference_df)
        records = self._strip_lbl_for_raw_records(records)
        if not records:
            return self._t("nothing_to_download")

        if progress_emit:
            progress_emit(self._t("progress_images", current=0, total=len(records)))
            progress_emit(self._t("progress_download_running"))

        running_names_emitted: set[str] = set()
        saved_names_emitted: set[str] = set()
        last_images_emit_t = 0.0
        last_images_emit_cur: Optional[int] = None

        def emit_images_progress(cur: Any, total: Any, *, force: bool = False) -> None:
            nonlocal last_images_emit_t, last_images_emit_cur
            if not progress_emit:
                return
            try:
                cur_i = int(cur) if cur is not None else None
                total_i = int(total) if total is not None else None
            except Exception:
                return
            if cur_i is None or total_i is None or total_i <= 0:
                return
            now = time.monotonic()
            # Streamlit UI can slow down a lot if we emit too many progress updates.
            # Throttle to a few updates per second while still forcing the final update.
            if force or cur_i == 0 or cur_i == total_i or last_images_emit_cur != cur_i and (now - last_images_emit_t) >= 0.15:
                last_images_emit_t = now
                last_images_emit_cur = cur_i
                progress_emit(self._t("progress_images", current=cur_i, total=total_i))

        def event_image_name(ev: dict[str, Any]) -> str:
            file_name = self._normalize_text(ev.get("filename"))
            if file_name:
                return file_name
            img_url = self._normalize_text(ev.get("img_url"))
            if img_url:
                return Path(img_url).name
            lbl_url = self._normalize_text(ev.get("lbl_url"))
            if lbl_url:
                return Path(lbl_url).name
            return ""

        def event_image_key(ev: dict[str, Any]) -> str:
            img_name = Path(self._normalize_text(ev.get("img_url"))).name
            if img_name:
                return self._normalize_text(self._display_image_name_from_output_file(img_name) or img_name)
            file_name = event_image_name(ev)
            return self._normalize_text(self._display_image_name_from_output_file(file_name) or file_name)

        def on_download_event(ev: dict[str, Any]) -> None:
            stage = self._normalize_text(ev.get("stage"))
            if stage == "download_file_saved":
                file_name = event_image_name(ev)
                self._track_saved_output_file(file_name)
                if progress_emit and file_name:
                    key = self._normalize_text(file_name)
                    if key and key not in saved_names_emitted:
                        saved_names_emitted.add(key)
                        progress_emit(self._t("progress_download_file_saved", name=file_name))
            if not progress_emit:
                return
            cur = ev.get("current")
            total = ev.get("total")
            if stage == "download_progress":
                item_key = event_image_key(ev)
                item_name = event_image_name(ev)
                if item_key and item_name and item_key not in running_names_emitted:
                    running_names_emitted.add(item_key)
                    progress_emit(self._t("progress_download_item_running", name=item_name))
                emit_images_progress(cur, total)
            elif stage == "download_done":
                progress_emit(self._t("progress_download_done"))
                emit_images_progress(total, total, force=True)

        dl_params = inspect.signature(self._download_records).parameters
        pds_records, raw_records = self._split_records_by_source(records)
        total_images = 0
        downloaded_files = 0
        skipped_files = 0
        errors = 0
        images_already_present = 0
        images_with_new_downloads = 0
        for source_name, source_records in (("pds", pds_records), ("raw", raw_records)):
            if not source_records:
                continue
            out_dir = self._output_dir_for_source(path, source_name)
            dl_kwargs: dict[str, Any] = {
                "output_dir": str(out_dir),
                "timeout": 120,
                "skip_existing": True,
                "workers": 16,
            }
            if "progress_callback" in dl_params:
                dl_kwargs["progress_callback"] = on_download_event
            stats = self._download_records(source_records, **dl_kwargs)
            total_images += int(stats.get("total", len(source_records)))
            downloaded_files += int(stats.get("downloaded", 0))
            skipped_files += int(stats.get("skipped", 0))
            errors += int(stats.get("errors", 0))
            images_already_present += int(stats.get("images_already_present", 0))
            images_with_new_downloads += int(stats.get("images_with_new_downloads", 0))

        removed_small_by_min = 0
        if min_size_threshold > 0:
            removed_small_by_min += int(self._enforce_global_min_output_size(self._output_dir_for_source(path, "pds"), min_size_threshold))
            removed_small_by_min += int(self._enforce_global_min_output_size(self._output_dir_for_source(path, "raw"), min_size_threshold))

        lines = [
            self._t("download_summary_title"),
            self._t("download_summary_selected", value=total_images),
            f"- Alpha-pair candidates (navcam/hazcam): {paired_candidates}",
            self._t("download_summary_already_complete", value=images_already_present),
            self._t("download_summary_with_new", value=images_with_new_downloads),
            self._t("download_summary_downloaded_files", value=downloaded_files),
            self._t("download_summary_skipped_files", value=skipped_files),
            self._t("download_summary_errors", value=errors),
        ]
        if min_size_threshold > 0 and (
            int(pre_size_stats.get("checked", 0)) > 0
            or int(pre_size_stats.get("dropped_known_small", 0)) > 0
            or int(pre_size_stats.get("dropped_unknown_or_small", 0)) > 0
        ):
            lines.append(
                f"- Min-size preselect ({self._format_size_short(min_size_threshold)}): "
                f"checked={int(pre_size_stats.get('checked', 0))}, "
                f"dropped_known_small={int(pre_size_stats.get('dropped_known_small', 0))}, "
                f"dropped_unknown_or_small={int(pre_size_stats.get('dropped_unknown_or_small', 0))}"
            )
        if removed_small_by_min > 0:
            lines.append(f"- Min-size post-download ({self._format_size_short(min_size_threshold)}): removed {removed_small_by_min}")
        if downloaded_files == 0 and images_already_present > 0 and errors == 0:
            lines.append(self._t("download_summary_note_no_new"))
        return "\n".join(lines)

    def run_process(
        self,
        *,
        requested_path: str,
        all_variants: bool = False,
        progress_emit: Optional[Callable[[str], None]] = None,
        max_images: Optional[int] = None,
        random_sample: bool = False,
        per_camera_limits: Optional[dict[str, int]] = None,
        selection_df: Any = None,
        reference_df: Any = None,
    ) -> str:
        ok_path, path = self._ensure_writable_download_path(requested_path)
        if not ok_path:
            return self._t("output_path_required")
        if path != requested_path:
            self._set_download_path(path, True)
        df, pre_size_stats, min_size_threshold = self._prepare_action_df_with_min_size(
            all_variants=all_variants,
            max_images=max_images,
            random_sample=random_sample,
            per_camera_limits=per_camera_limits,
            require_lbl=False,
            selection_df=selection_df,
        )
        records = self._records_from_dataframe(df, limit=None, require_lbl=False)
        records, paired_candidates = self._attach_optional_alpha_pairs(records, reference_df=reference_df)
        records = self._strip_lbl_for_raw_records(records)
        if not records:
            return self._t("nothing_to_process")
        if progress_emit:
            progress_emit(self._t("progress_conversion_start", current=0, total=len(records)))
        cfg = self._load_json(self._resolve_msl_config())
        rover_csv_url = self._normalize_text(cfg.get("coord_url"))
        rover_csv_local = (self._project_root / self._normalize_text(cfg.get("coord_local_path", "data/reference/geo/localized_interp_demv2.csv"))).resolve()
        def on_process_event(ev: dict[str, Any]) -> None:
            stage = self._normalize_text(ev.get("stage"))
            product_id = self._normalize_text(ev.get("product_id"))
            if stage == "write_jpg" and product_id:
                self._track_saved_output_file(f"{product_id}.jpg")
            elif stage == "write_meta" and product_id:
                self._track_saved_output_file(f"{product_id}.meta.json")
            if not progress_emit:
                return
            cur = ev.get("current")
            total = ev.get("total")
            if stage in {"batch_progress", "write_jpg", "write_meta"} and cur and total:
                progress_emit(self._t("progress_conversion_running", current=cur, total=total))
            elif stage == "batch_done":
                progress_emit(self._t("progress_conversion_done"))

        proc_params = inspect.signature(self._process_records_with_engine).parameters
        pds_records, raw_records = self._split_records_by_source(records)
        total_processed = 0
        total_ok = 0
        total_errors = 0
        alpha_pair_rgba_ok = 0
        alpha_pair_rgba_skipped = 0
        removed_small_mastcam = 0
        removed_small_by_min = 0
        threshold = self._mastcam_min_output_size_bytes()
        for source_name, source_records in (("pds", pds_records), ("raw", raw_records)):
            if not source_records:
                continue
            out_dir = self._output_dir_for_source(path, source_name)
            recs_with_lbl, recs_without_lbl = self._split_records_by_lbl(source_records)
            proc_kwargs: dict[str, Any] = {
                "output_dir": str(out_dir),
                "rover_csv_url": rover_csv_url,
                "rover_csv_local_path": rover_csv_local,
                "dwn_dir": self._project_root.parent / "DWN",
                "engine_version": "app-0.1.0",
            }
            if "progress_callback" in proc_params:
                proc_kwargs["progress_callback"] = on_process_event
            if recs_with_lbl:
                stats = self._process_records_with_engine(recs_with_lbl, **proc_kwargs)
                total_processed += int(stats.get("total", 0))
                total_ok += int(stats.get("ok", 0))
                total_errors += int(stats.get("errors", 0))
                self._maybe_correct_mardi_products(recs_with_lbl, out_dir)
                a_ok, a_skip = self._apply_optional_alpha_pair_processing(recs_with_lbl, output_dir=out_dir, progress_emit=progress_emit)
                alpha_pair_rgba_ok += int(a_ok)
                alpha_pair_rgba_skipped += int(a_skip)
            if recs_without_lbl:
                dl_stats = self._download_records(recs_without_lbl, output_dir=str(out_dir), timeout=120, skip_existing=True)
                no_lbl_total = int(dl_stats.get("total", len(recs_without_lbl)))
                no_lbl_errors = int(dl_stats.get("errors", 0))
                total_processed += no_lbl_total
                total_ok += max(0, no_lbl_total - no_lbl_errors)
                total_errors += no_lbl_errors
                if source_name == "raw":
                    for rec in recs_without_lbl:
                        img_url = self._normalize_text(rec.get("img_url"))
                        if not img_url:
                            continue
                        img_path = out_dir / Path(img_url).name
                        if img_path.exists() and img_path.is_file():
                            self._apply_mastcam_bayer_raw_processing(rec, out_dir)
            if min_size_threshold > 0:
                removed_small_by_min += int(self._enforce_global_min_output_size(out_dir, min_size_threshold))
            removed_small_mastcam += int(self._enforce_mastcam_min_output_size(out_dir))

        lines = [self._t("process_summary", total=total_processed, ok=total_ok, errors=total_errors)]
        if min_size_threshold > 0 and (
            int(pre_size_stats.get("checked", 0)) > 0
            or int(pre_size_stats.get("dropped_known_small", 0)) > 0
            or int(pre_size_stats.get("dropped_unknown_or_small", 0)) > 0
        ):
            lines.append(
                f"Min-size preselect ({self._format_size_short(min_size_threshold)}): "
                f"checked={int(pre_size_stats.get('checked', 0))}, "
                f"dropped_known_small={int(pre_size_stats.get('dropped_known_small', 0))}, "
                f"dropped_unknown_or_small={int(pre_size_stats.get('dropped_unknown_or_small', 0))}"
            )
        if removed_small_by_min > 0:
            lines.append(f"Min-size post-download ({self._format_size_short(min_size_threshold)}): removed {removed_small_by_min}")
        if removed_small_mastcam > 0:
            lines.append(self._t("mastcam_min_size_removed", count=removed_small_mastcam, size=self._format_size_short(threshold)))
        lines.append(f"Alpha pair candidates (navcam/hazcam): {paired_candidates}")
        lines.append(f"Alpha RGBA generated: {alpha_pair_rgba_ok}")
        lines.append(f"Alpha RGBA skipped/errors: {alpha_pair_rgba_skipped}")
        return "\n".join(lines)

    def run_download_and_process_interleaved(
        self,
        *,
        requested_path: str,
        stop_requested_getter: Callable[[], bool],
        all_variants: bool = False,
        progress_emit: Optional[Callable[[str], None]] = None,
        max_images: Optional[int] = None,
        random_sample: bool = False,
        per_camera_limits: Optional[dict[str, int]] = None,
        selection_df: Any = None,
        reference_df: Any = None,
    ) -> str:
        ok_path, path = self._ensure_writable_download_path(requested_path)
        if not ok_path:
            return self._t("output_path_required")
        if path != requested_path:
            self._set_download_path(path, True)
        df, pre_size_stats, min_size_threshold = self._prepare_action_df_with_min_size(
            all_variants=all_variants,
            max_images=max_images,
            random_sample=random_sample,
            per_camera_limits=per_camera_limits,
            require_lbl=False,
            selection_df=selection_df,
        )
        records = self._records_from_dataframe(df, limit=None, require_lbl=False)
        records, paired_candidates = self._attach_optional_alpha_pairs(records, reference_df=reference_df)
        records = self._strip_lbl_for_raw_records(records)
        total = len(records)
        if total == 0:
            return self._t("nothing_to_download_process")
        cfg = self._load_json(self._resolve_msl_config())
        rover_csv_url = self._normalize_text(cfg.get("coord_url"))
        rover_csv_local = (self._project_root / self._normalize_text(cfg.get("coord_local_path", "data/reference/geo/localized_interp_demv2.csv"))).resolve()
        total_converted_ok = 0
        total_convert_errors = 0
        mastcam_bayer_applied = 0
        mastcam_bayer_skipped = 0
        alpha_pair_rgba_ok = 0
        alpha_pair_rgba_skipped = 0
        processed_images = 0

        for idx, rec in enumerate(records, start=1):
            if stop_requested_getter():
                if progress_emit:
                    progress_emit(self._t("stop_requested_pipeline"))
                break
            img_url = self._normalize_text(rec.get("img_url"))
            lbl_url = self._normalize_text(rec.get("lbl_url"))
            img_name = Path(img_url).name if img_url else f"image_{idx}"
            if progress_emit:
                progress_emit(self._t("progress_images", current=idx, total=total))
                progress_emit(self._t("progress_download_convert_running", name=img_name))

            def on_process_event(ev: dict[str, Any]) -> None:
                stage = self._normalize_text(ev.get("stage"))
                product_id = self._normalize_text(ev.get("product_id")) or Path(img_name).stem
                if stage == "write_jpg" and product_id:
                    self._track_saved_output_file(f"{product_id}.jpg")
                elif stage == "write_meta" and product_id:
                    self._track_saved_output_file(f"{product_id}.meta.json")
                if not progress_emit:
                    return
                if stage == "download_lbl":
                    progress_emit(self._t("progress_lbl_downloaded", name=img_name))
                elif stage == "download_img":
                    progress_emit(self._t("progress_img_downloaded", name=img_name))
                elif stage == "write_jpg":
                    progress_emit(self._t("progress_jpg_saved", name=img_name))
                elif stage == "write_meta":
                    progress_emit(self._t("progress_meta_saved", name=img_name))

            out_dir = self._output_dir_for_source(path, rec.get("source"))
            item_ok = False
            if self._normalize_text(rec.get("lbl_url")):
                p_stats = self._process_records_with_engine(
                    [rec],
                    output_dir=str(out_dir),
                    rover_csv_url=rover_csv_url,
                    rover_csv_local_path=rover_csv_local,
                    dwn_dir=self._project_root.parent / "DWN",
                    engine_version="app-0.1.0",
                    progress_callback=on_process_event,
                )
                total_converted_ok += int(p_stats.get("ok", 0))
                total_convert_errors += int(p_stats.get("errors", 0))
                item_ok = int(p_stats.get("ok", 0)) > 0
                if item_ok:
                    a_ok, a_skip = self._apply_optional_alpha_pair_processing([rec], output_dir=out_dir, progress_emit=progress_emit)
                    alpha_pair_rgba_ok += int(a_ok)
                    alpha_pair_rgba_skipped += int(a_skip)
            else:
                dl_stats = self._download_records([rec], output_dir=str(out_dir), timeout=120, skip_existing=True)
                total_converted_ok += max(0, int(dl_stats.get("total", 1)) - int(dl_stats.get("errors", 0)))
                total_convert_errors += int(dl_stats.get("errors", 0))
                item_ok = int(dl_stats.get("errors", 0)) == 0 and int(dl_stats.get("total", 0)) > 0
                if item_ok:
                    applied, reason = self._apply_mastcam_bayer_raw_processing(rec, out_dir)
                    rec["_mastcam_bayer_applied"] = bool(applied)
                    rec["_mastcam_bayer_reason"] = self._normalize_text(reason)
                    if applied:
                        mastcam_bayer_applied += 1
                        if progress_emit:
                            progress_emit(f"Mastcam RAW Bayer processing applied: {img_name}")
                    else:
                        if self._is_raw_archive_mastcam_record(rec):
                            mastcam_bayer_skipped += 1
                            if progress_emit:
                                progress_emit(f"Mastcam RAW Bayer processing skipped: {img_name} ({reason})")
                    # RAW archive: images only (no metadata files).

            # No final conversion: canonical outputs are JPG (masks/RGBA remain PNG).
            if img_url:
                raw_img = out_dir / Path(img_url).name
                if raw_img.exists() and raw_img.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                    raw_img.unlink(missing_ok=True)
            if lbl_url:
                raw_lbl = out_dir / Path(lbl_url).name
                if raw_lbl.exists():
                    raw_lbl.unlink(missing_ok=True)
            if progress_emit:
                progress_emit(self._t("progress_converted_ok", name=img_name) if item_ok else self._t("progress_converted_error", name=img_name))
            processed_images = idx

            # RAW archive: write meta.json per-file as soon as the JPG is available,
            # so downstream organization can rely on SOL (including fallback from SCLK).
            if item_ok and self._normalize_text(rec.get("source")).lower() == "raw":
                try:
                    self._write_raw_archive_meta(
                        [rec],
                        output_dir=self._output_dir_for_source(path, "raw"),
                        rover_csv_url=rover_csv_url,
                        rover_csv_local_path=str(rover_csv_local),
                        engine_version="app-0.1.0",
                        progress_emit=progress_emit,
                    )
                except Exception:
                    pass

            # Finalize: enforce JPG-only outputs for the current product (masks/RGBA remain PNG).
            if item_ok and img_url:
                try:
                    product_id = self._normalize_text(rec.get("product_id")) or Path(img_url).stem
                    if product_id:
                        self._finalize_product_jpg_only(out_dir, product_id)
                except Exception:
                    pass

        interrupted = stop_requested_getter() and processed_images < total
        corrected_total = 0
        extras_total = 0
        pds_done, raw_done = self._split_records_by_source(records[:processed_images])
        if pds_done:
            c, e = self._maybe_correct_mardi_products(pds_done, self._output_dir_for_source(path, "pds"))
            corrected_total += int(c)
            extras_total += int(e)
        if raw_done:
            c, e = self._maybe_correct_mardi_products(raw_done, self._output_dir_for_source(path, "raw"))
            corrected_total += int(c)
            extras_total += int(e)
        threshold = self._mastcam_min_output_size_bytes()
        removed_small_by_min = 0
        if min_size_threshold > 0:
            removed_small_by_min += int(self._enforce_global_min_output_size(self._output_dir_for_source(path, "pds"), min_size_threshold))
        removed_small_mastcam = int(self._enforce_mastcam_min_output_size(self._output_dir_for_source(path, "pds")))
        removed_small_mastcam += int(self._enforce_mastcam_min_output_size(self._output_dir_for_source(path, "raw")))
        lines = [
            self._t("download_convert_summary_title"),
            self._t("download_convert_selected", value=total),
            f"- Alpha-pair candidates (navcam/hazcam): {paired_candidates}",
            self._t("download_convert_processed", value=processed_images),
            self._t("download_convert_interrupted", value=self._t("yes_label") if interrupted else self._t("no_label")),
            self._t("download_convert_ok", value=total_converted_ok),
            self._t("download_convert_errors", value=total_convert_errors),
            self._t("download_convert_no_raw"),
        ]
        if min_size_threshold > 0 and (
            int(pre_size_stats.get("checked", 0)) > 0
            or int(pre_size_stats.get("dropped_known_small", 0)) > 0
            or int(pre_size_stats.get("dropped_unknown_or_small", 0)) > 0
        ):
            lines.append(
                f"- Min-size preselect ({self._format_size_short(min_size_threshold)}): "
                f"checked={int(pre_size_stats.get('checked', 0))}, "
                f"dropped_known_small={int(pre_size_stats.get('dropped_known_small', 0))}, "
                f"dropped_unknown_or_small={int(pre_size_stats.get('dropped_unknown_or_small', 0))}"
            )
        if removed_small_by_min > 0:
            lines.append(f"- Min-size post-download ({self._format_size_short(min_size_threshold)}): removed {removed_small_by_min}")
        if self._mardi_geometric_correction_enabled():
            lines.append(self._t("mardi_geom_applied", value=corrected_total))
            if self._mardi_side_by_side_enabled():
                lines.append(self._t("mardi_geom_side_saved", value=extras_total))
        if removed_small_mastcam > 0:
            lines.append(self._t("mastcam_min_size_removed", count=removed_small_mastcam, size=self._format_size_short(threshold)))
        lines.append(f"Alpha RGBA generated: {alpha_pair_rgba_ok}")
        lines.append(f"Alpha RGBA skipped/errors: {alpha_pair_rgba_skipped}")
        lines.append(f"- Mastcam RAW Bayer processing: applied={mastcam_bayer_applied}, skipped={mastcam_bayer_skipped}")
        if raw_done:
            exif_applied, exif_skipped = self._apply_raw_archive_hardcoded_exif(
                raw_done,
                output_dir=self._output_dir_for_source(path, "raw"),
                progress_emit=progress_emit,
            )
            meta_written, meta_skipped = self._write_raw_archive_meta(
                raw_done,
                output_dir=self._output_dir_for_source(path, "raw"),
                rover_csv_url=rover_csv_url,
                rover_csv_local_path=str(rover_csv_local),
                engine_version="app-0.1.0",
                progress_emit=progress_emit,
            )
            lines.append(f"- RAW hardcoded EXIF: applied={exif_applied}, skipped={exif_skipped}")
            lines.append(f"- RAW meta.json: written={meta_written}, skipped={meta_skipped}")
        return "\n".join(lines)
