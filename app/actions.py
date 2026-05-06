from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd
import requests
import streamlit as st

from utils.folder_dialog import choose_folder_dialog
from catalog import (
    apply_filters,
    analytics_use_filtered_scope,
    camera_types_report,
    catalog_content_report,
    database_count_report,
    database_max_sol_report,
    is_analytics_query,
    filter_dataframe,
    selection_report,
)
from parser import (
    _humanize_parser_response,
    _intent_match,
    _is_camera_list_request,
    _is_unsupported_image_url_request,
    _normalize_camera_key,
    _normalize_command_for_parser,
    _no_pending_bulk_text,
    _parse_cameras,
    _parse_int,
    _parse_sol_range,
    _split_multi_range_blocks,
    _parser_validation_note,
    _wants_all_cameras,
    _wants_organize_step,
    _wants_random_sample,
    set_translator as set_parser_translator,
)
from runtime import (
    DEFAULT_BULK_CONFIRM_THRESHOLD,
    MARDI_GEOMETRIC_CORRECTION_DEFAULT,
    MARDI_GEOMETRIC_SIDE_BY_SIDE_DEFAULT,
    MARDI_LEGACY_MODE_DEFAULT,
    _default_download_path,
    _display_image_name_from_output_file,
    _ensure_writable_download_path,
    _refresh_saved_output_files,
    _resolve_download_path,
    _resolve_msl_config,
    _resolve_pds_missing_sols,
    _resolve_output_files_for_product,
    _track_saved_output_file,
    load_app_ui_config,
    load_json,
    normalize_text,
    save_app_ui_config,
    save_json,
)
from session import _append_user_action

from portable_engine_adapter import download_records, process_records_with_engine, records_from_dataframe  # type: ignore
from catalog_runner import CatalogUpdateOptions, run_catalog_update  # type: ignore

from services.app_config_service import AppConfigService
from services.catalog_update_service import CatalogUpdateService
from services.download_processing_service import DownloadProcessingService
from services.output_organizer import OutputOrganizer
from services.action_dispatcher_service import ActionDispatcherService
from services.command_submission_service import CommandSubmissionService
from services.selection_service import SelectionService
from services.local_command_handler_service import LocalCommandHandlerService
from services.image_processing_service import ImageProcessingService
from services.action_dataframe_service import ActionDataframeService
from services.catalog_selection_service import CatalogSelectionService
from services.output_size_enforcement_service import OutputSizeEnforcementService
from services.record_output_utils_service import RecordOutputUtilsService
from services.text_utils_service import TextUtilsService
from services.camera_naming_service import CameraNamingService
from services.alpha_pair_service import AlphaPairService


PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = Path(__file__).resolve().parent

_T: Callable[..., str] = lambda key, **kwargs: key.format(**kwargs) if kwargs else key
_APP_CONFIG_SERVICE: AppConfigService | None = None
_CATALOG_UPDATE_SERVICE: CatalogUpdateService | None = None
_DOWNLOAD_PROCESSING_SERVICE: DownloadProcessingService | None = None
_OUTPUT_ORGANIZER: OutputOrganizer | None = None
_ACTION_DISPATCHER_SERVICE: ActionDispatcherService | None = None
_COMMAND_SUBMISSION_SERVICE: CommandSubmissionService | None = None
_SELECTION_SERVICE: SelectionService | None = None
_LOCAL_COMMAND_HANDLER_SERVICE: LocalCommandHandlerService | None = None
_IMAGE_PROCESSING_SERVICE: ImageProcessingService | None = None
_ACTION_DF_SERVICE: ActionDataframeService | None = None
_CATALOG_SELECTION_SERVICE: CatalogSelectionService | None = None
_OUTPUT_SIZE_SERVICE: OutputSizeEnforcementService | None = None
_RECORD_OUTPUT_UTILS_SERVICE: RecordOutputUtilsService | None = None
_TEXT_UTILS_SERVICE: TextUtilsService | None = None
_CAMERA_NAMING_SERVICE: CameraNamingService | None = None
_ALPHA_PAIR_SERVICE: AlphaPairService | None = None


def _get_app_config_service() -> AppConfigService:
    global _APP_CONFIG_SERVICE
    if _APP_CONFIG_SERVICE is None:
        _APP_CONFIG_SERVICE = AppConfigService(
            project_root=PROJECT_ROOT,
            translator=t,
            normalize_text=normalize_text,
            resolve_download_path=_resolve_download_path,
            refresh_saved_output_files=_refresh_saved_output_files,
            load_app_ui_config=load_app_ui_config,
            save_app_ui_config=save_app_ui_config,
            load_json=load_json,
            resolve_msl_config=_resolve_msl_config,
            ensure_writable_download_path=_ensure_writable_download_path,
            default_download_path=_default_download_path,
        )
    return _APP_CONFIG_SERVICE


def _get_catalog_update_service() -> CatalogUpdateService:
    global _CATALOG_UPDATE_SERVICE
    if _CATALOG_UPDATE_SERVICE is None:
        _CATALOG_UPDATE_SERVICE = CatalogUpdateService(
            project_root=PROJECT_ROOT,
            translator=t,
            normalize_text=normalize_text,
            normalize_command_for_parser=_normalize_command_for_parser,
            parse_sol_range=_parse_sol_range,
            parse_int=_parse_int,
            parse_cameras=_parse_cameras,
            resolve_msl_config=_resolve_msl_config,
            catalog_update_options_cls=CatalogUpdateOptions,
            run_catalog_update=run_catalog_update,
        )
    return _CATALOG_UPDATE_SERVICE


def _get_download_processing_service() -> DownloadProcessingService:
    global _DOWNLOAD_PROCESSING_SERVICE
    if _DOWNLOAD_PROCESSING_SERVICE is None:
        _DOWNLOAD_PROCESSING_SERVICE = DownloadProcessingService(
            translator=t,
            normalize_text=normalize_text,
            ensure_writable_download_path=_ensure_writable_download_path,
            set_download_path=set_download_path,
            prepare_action_df_with_min_size=_prepare_action_df_with_min_size,
            records_from_dataframe=records_from_dataframe,
            attach_optional_alpha_pairs=_attach_optional_alpha_pairs,
            strip_lbl_for_raw_records=_strip_lbl_for_raw_records,
            output_dir_for_source=_output_dir_for_source,
            split_records_by_source=_split_records_by_source,
            split_records_by_lbl=_split_records_by_lbl,
            display_image_name_from_output_file=_display_image_name_from_output_file,
            track_saved_output_file=_track_saved_output_file,
            load_json=load_json,
            resolve_msl_config=_resolve_msl_config,
            project_root=PROJECT_ROOT,
            download_records=download_records,
            process_records_with_engine=process_records_with_engine,
            enforce_global_min_output_size=_enforce_global_min_output_size,
            enforce_mastcam_min_output_size=_enforce_mastcam_min_output_size,
            mastcam_min_output_size_bytes=_mastcam_min_output_size_bytes,
            format_size_short=_format_size_short,
            maybe_correct_mardi_products=_maybe_correct_mardi_products,
            mardi_geometric_correction_enabled=_mardi_geometric_correction_enabled,
            mardi_side_by_side_enabled=_mardi_side_by_side_enabled,
            apply_optional_alpha_pair_processing=_apply_optional_alpha_pair_processing,
            apply_mastcam_bayer_raw_processing=_apply_mastcam_bayer_raw_processing,
            is_raw_archive_mastcam_record=_is_raw_archive_mastcam_record,
            finalize_product_jpg_only=_finalize_product_jpg_only,
            apply_raw_archive_hardcoded_exif=_apply_raw_archive_hardcoded_exif,
            write_raw_archive_meta=_write_raw_archive_meta,
        )
    return _DOWNLOAD_PROCESSING_SERVICE


def _get_output_organizer() -> OutputOrganizer:
    global _OUTPUT_ORGANIZER
    if _OUTPUT_ORGANIZER is None:
        _OUTPUT_ORGANIZER = OutputOrganizer(
            translator=t,
            refresh_saved_output_files=_refresh_saved_output_files,
            camera_folder_for_filename=_camera_folder_for_filename,
            normalize_text=normalize_text,
        )
    return _OUTPUT_ORGANIZER


def _get_action_dispatcher_service() -> ActionDispatcherService:
    global _ACTION_DISPATCHER_SERVICE
    if _ACTION_DISPATCHER_SERVICE is None:
        _ACTION_DISPATCHER_SERVICE = ActionDispatcherService(
            translator=t,
            normalize_text=normalize_text,
            run_sql_query=run_sql_query,
            run_download=run_download,
            run_download_and_process_interleaved=run_download_and_process_interleaved,
        )
    return _ACTION_DISPATCHER_SERVICE


def _get_command_submission_service() -> CommandSubmissionService:
    global _COMMAND_SUBMISSION_SERVICE
    if _COMMAND_SUBMISSION_SERVICE is None:
        _COMMAND_SUBMISSION_SERVICE = CommandSubmissionService(
            translator=t,
            normalize_text=normalize_text,
            append_user_action=_append_user_action,
            handle_local=handle_local,
            parser_validation_note=_parser_validation_note,
            humanize_parser_response=_humanize_parser_response,
            norm_ascii=_norm_ascii,
            show_combined_config_text=show_combined_config_text,
            geo_status_text=geo_status_text,
            show_download_path_text=show_download_path_text,
        )
    return _COMMAND_SUBMISSION_SERVICE


def _get_selection_service() -> SelectionService:
    global _SELECTION_SERVICE
    if _SELECTION_SERVICE is None:
        _SELECTION_SERVICE = SelectionService()
    return _SELECTION_SERVICE


def _get_local_command_handler_service() -> LocalCommandHandlerService:
    global _LOCAL_COMMAND_HANDLER_SERVICE
    if _LOCAL_COMMAND_HANDLER_SERVICE is None:
        _LOCAL_COMMAND_HANDLER_SERVICE = LocalCommandHandlerService(
            translator=t,
            normalize_text=normalize_text,
            norm_ascii=_norm_ascii,
            mardi_legacy_mode_enabled=_mardi_legacy_mode_enabled,
            analytics_use_filtered_scope=analytics_use_filtered_scope,
            apply_filters=apply_filters,
            camera_types_report=camera_types_report,
            catalog_content_report=catalog_content_report,
            database_count_report=database_count_report,
            database_max_sol_report=database_max_sol_report,
            is_analytics_query=is_analytics_query,
            filter_dataframe=filter_dataframe,
            selection_report=selection_report,
            reset_filters_state=_reset_filters_state_for,
            prepare_action_df=_prepare_action_df,
            run_download=run_download,
            run_process=run_process,
            run_download_and_process_interleaved=run_download_and_process_interleaved,
            organize_photos_simple_layout=organize_photos_simple_layout,
            choose_download_path_dialog=choose_download_path_dialog,
            set_download_path=set_download_path,
            show_combined_config_text=show_combined_config_text,
            show_download_path_text=show_download_path_text,
            geo_status_text=geo_status_text,
            download_geo_csv=download_geo_csv,
            parse_set_config=_parse_set_config,
            parse_cfg_value=_parse_cfg_value,
            set_nested=_set_nested,
            load_json=load_json,
            save_json=save_json,
            resolve_msl_config=_resolve_msl_config,
            run_catalog_update_from_text=run_catalog_update_from_text,
            get_selection_df=_get_selection_df_for,
        )
    return _LOCAL_COMMAND_HANDLER_SERVICE


def _get_image_processing_service() -> ImageProcessingService:
    global _IMAGE_PROCESSING_SERVICE
    if _IMAGE_PROCESSING_SERVICE is None:
        _IMAGE_PROCESSING_SERVICE = ImageProcessingService(
            project_root=PROJECT_ROOT,
            translator=t,
            normalize_text=normalize_text,
            norm_ascii=_norm_ascii,
            load_json=load_json,
            track_saved_output_file=_track_saved_output_file,
        )
    return _IMAGE_PROCESSING_SERVICE


def _get_action_df_service() -> ActionDataframeService:
    global _ACTION_DF_SERVICE
    if _ACTION_DF_SERVICE is None:
        _ACTION_DF_SERVICE = ActionDataframeService(
            normalize_text=normalize_text,
        )
    return _ACTION_DF_SERVICE


def _get_catalog_selection_service() -> CatalogSelectionService:
    global _CATALOG_SELECTION_SERVICE
    if _CATALOG_SELECTION_SERVICE is None:
        _CATALOG_SELECTION_SERVICE = CatalogSelectionService(
            normalize_text=normalize_text,
            load_json=load_json,
            resolve_pds_missing_sols=_resolve_pds_missing_sols,
        )
    return _CATALOG_SELECTION_SERVICE


def _get_output_size_service() -> OutputSizeEnforcementService:
    global _OUTPUT_SIZE_SERVICE
    if _OUTPUT_SIZE_SERVICE is None:
        _OUTPUT_SIZE_SERVICE = OutputSizeEnforcementService(
            project_root=PROJECT_ROOT,
            load_json=load_json,
            camera_folder_for_filename=_camera_folder_for_filename,
            refresh_saved_output_files=_refresh_saved_output_files,
        )
    return _OUTPUT_SIZE_SERVICE


def _get_record_output_utils_service() -> RecordOutputUtilsService:
    global _RECORD_OUTPUT_UTILS_SERVICE
    if _RECORD_OUTPUT_UTILS_SERVICE is None:
        _RECORD_OUTPUT_UTILS_SERVICE = RecordOutputUtilsService(
            normalize_text=normalize_text,
            norm_ascii=_norm_ascii,
            load_json=load_json,
            save_json=save_json,
        )
    return _RECORD_OUTPUT_UTILS_SERVICE


def _get_text_utils_service() -> TextUtilsService:
    global _TEXT_UTILS_SERVICE
    if _TEXT_UTILS_SERVICE is None:
        _TEXT_UTILS_SERVICE = TextUtilsService(normalize_text=normalize_text)
    return _TEXT_UTILS_SERVICE


def _get_camera_naming_service() -> CameraNamingService:
    global _CAMERA_NAMING_SERVICE
    if _CAMERA_NAMING_SERVICE is None:
        _CAMERA_NAMING_SERVICE = CameraNamingService(normalize_text=normalize_text)
    return _CAMERA_NAMING_SERVICE


def _get_alpha_pair_service() -> AlphaPairService:
    global _ALPHA_PAIR_SERVICE
    if _ALPHA_PAIR_SERVICE is None:
        _ALPHA_PAIR_SERVICE = AlphaPairService(
            normalize_text=normalize_text,
            norm_ascii=_norm_ascii,
            normalize_source=_normalize_source,
            record_product_id=_record_product_id,
        )
    return _ALPHA_PAIR_SERVICE


def _norm_ascii(text: str) -> str:
    return _get_text_utils_service().norm_ascii(text)


def _strip_lbl_for_raw_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _get_record_output_utils_service().strip_lbl_for_raw_records(records)


def set_translator(fn: Callable[..., str]) -> None:
    global _T
    _T = fn
    set_parser_translator(fn)


def t(key: str, **kwargs: Any) -> str:
    try:
        return _T(key, **kwargs)
    except Exception:
        return key.format(**kwargs) if kwargs else key


def _mardi_geometric_correction_enabled() -> bool:
    return _get_image_processing_service().mardi_geometric_correction_enabled(MARDI_GEOMETRIC_CORRECTION_DEFAULT)


def _mardi_side_by_side_enabled() -> bool:
    return _get_image_processing_service().mardi_side_by_side_enabled(MARDI_GEOMETRIC_SIDE_BY_SIDE_DEFAULT)


def _mardi_legacy_mode_enabled() -> bool:
    return _get_image_processing_service().mardi_legacy_mode_enabled(MARDI_LEGACY_MODE_DEFAULT)


def _apply_mardi_geometric_correction(image_path: Path) -> tuple[bool, Optional[Path], Optional[Path], dict[str, Any]]:
    return _get_image_processing_service().apply_mardi_geometric_correction(
        image_path,
        side_by_side=_mardi_side_by_side_enabled(),
    )


def _write_mardi_processing_metadata(meta_path: Path, details: dict[str, Any]) -> None:
    _get_image_processing_service().write_mardi_processing_metadata(meta_path, details)


def _maybe_correct_mardi_products(records: list[dict[str, Any]], output_dir: str | Path) -> tuple[int, int]:
    return _get_image_processing_service().maybe_correct_mardi_products(
        records,
        output_dir=output_dir,
        enabled=_mardi_geometric_correction_enabled(),
        side_by_side=_mardi_side_by_side_enabled(),
    )


def _is_raw_archive_mastcam_record(rec: dict[str, Any]) -> bool:
    return _get_image_processing_service().is_raw_archive_mastcam_record(rec, normalize_source=_normalize_source)


def _load_mastcam_bayer_pipeline() -> tuple[Any, Path] | tuple[None, None]:
    return _get_image_processing_service().load_mastcam_bayer_pipeline()


def _apply_mastcam_bayer_raw_processing(rec: dict[str, Any], output_dir: str | Path) -> tuple[bool, str]:
    return _get_image_processing_service().apply_mastcam_bayer_raw_processing(
        rec,
        output_dir=output_dir,
        normalize_source=_normalize_source,
    )


def _camera_folder_for_filename(filename: str) -> str:
    return _get_camera_naming_service().camera_folder_for_filename(filename)


def _convert_jpg_to_png_keep_exif(jpg_path: Path) -> Optional[Path]:
    return _get_image_processing_service().convert_jpg_to_png_keep_exif(jpg_path)


def _update_meta_outputs_meta_path(meta_path: Path) -> None:
    _get_record_output_utils_service().update_meta_outputs_meta_path(meta_path)


def _finalize_product_jpg_only(out_dir: Path, product_id: str) -> None:
    """
    Enforce JPG-only outputs for a product:
    - if `<product_id>.png` exists (non-mask), remove it
    - keep `<product_id>.jpg` as the canonical output

    Masks (`*_mask.png`) and RGBA outputs are intentionally left untouched.
    """
    _get_image_processing_service().finalize_product_jpg_only(out_dir, product_id)

def _mastcam_min_output_size_bytes() -> int:
    return _get_output_size_service().mastcam_min_output_size_bytes()


def _configured_min_img_size_bytes() -> int:
    return _get_action_df_service().configured_min_img_size_bytes(st.session_state)


def _remote_size_cache() -> dict[str, int]:
    return _get_action_df_service().remote_size_cache(st.session_state)


def _probe_remote_img_size_bytes(img_url: str, timeout_sec: int = 20) -> Optional[int]:
    return _get_action_df_service().probe_remote_img_size_bytes(
        st.session_state,
        img_url,
        timeout_sec=timeout_sec,
    )


def _prefilter_df_by_min_size(
    df: pd.DataFrame,
    *,
    min_size_bytes: int,
    desired_count: Optional[int] = None,
    max_remote_checks: int = 60,
) -> tuple[pd.DataFrame, dict[str, int]]:
    return _get_action_df_service().prefilter_df_by_min_size(
        st.session_state,
        df,
        min_size_bytes=min_size_bytes,
        desired_count=desired_count,
        max_remote_checks=max_remote_checks,
    )


def _prepare_action_df_with_min_size(
    *,
    all_variants: bool = False,
    max_images: Optional[int] = None,
    random_sample: bool = False,
    per_camera_limits: Optional[dict[str, int]] = None,
    require_lbl: bool = False,
    selection_df: Optional[pd.DataFrame] = None,
) -> tuple[pd.DataFrame, dict[str, int], int]:
    return _get_action_df_service().prepare_action_df_with_min_size(
        st.session_state,
        all_variants=all_variants,
        max_images=max_images,
        random_sample=random_sample,
        per_camera_limits=per_camera_limits,
        require_lbl=require_lbl,
        selection_df=selection_df,
        get_selection_df=get_selection_df,
        route_selection_by_catalog_boundary=_route_selection_by_catalog_boundary,
        norm_ascii=_norm_ascii,
    )


def _format_size_short(size_bytes: int) -> str:
    return _get_record_output_utils_service().format_size_short(size_bytes)


def _normalize_source(value: Any) -> str:
    return _get_record_output_utils_service().normalize_source(value)


def _output_dir_for_source(base_output_path: str | Path, source: str) -> Path:
    return _get_record_output_utils_service().output_dir_for_source(base_output_path, source)


def _split_records_by_source(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return _get_record_output_utils_service().split_records_by_source(records)


def _split_records_by_lbl(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return _get_record_output_utils_service().split_records_by_lbl(records)


def _record_product_id(rec: dict[str, Any]) -> str:
    return _get_record_output_utils_service().record_product_id(rec)


def _attach_optional_alpha_pairs(
    records: list[dict[str, Any]],
    *,
    reference_df: Optional[pd.DataFrame] = None,
) -> tuple[list[dict[str, Any]], int]:
    return _get_alpha_pair_service().attach_optional_alpha_pairs(
        records,
        state=st.session_state,
        reference_df=reference_df,
    )


def _decode_pds_array(img_bytes: bytes, lbl_text: str) -> Optional[Any]:
    return _get_image_processing_service().decode_pds_array(img_bytes, lbl_text)


def _augment_meta_with_alpha_pair(
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
    _get_image_processing_service().augment_meta_with_alpha_pair(
        meta_path=meta_path,
        pair_product_id=pair_product_id,
        pair_img_url=pair_img_url,
        pair_lbl_url=pair_lbl_url,
        rgba_path=rgba_path,
        mask_path=mask_path,
        coverage=coverage,
        alpha_nonzero=alpha_nonzero,
        alpha_zero=alpha_zero,
    )


def _apply_alpha_pair_rgba_for_record(
    rec: dict[str, Any],
    *,
    output_dir: Path,
    session: requests.Session,
) -> tuple[bool, str]:
    return _get_image_processing_service().apply_alpha_pair_rgba_for_record(
        rec,
        output_dir=output_dir,
        session=session,
        record_product_id=_record_product_id,
    )


def _apply_optional_alpha_pair_processing(
    records: list[dict[str, Any]],
    *,
    output_dir: Path,
    progress_emit: Optional[Callable[[str], None]] = None,
) -> tuple[int, int]:
    return _get_image_processing_service().apply_optional_alpha_pair_processing(
        records,
        output_dir=output_dir,
        record_product_id=_record_product_id,
        progress_emit=progress_emit,
    )


def _apply_raw_archive_hardcoded_exif(
    records: list[dict[str, Any]],
    *,
    output_dir: Path,
    progress_emit: Optional[Callable[[str], None]] = None,
) -> tuple[int, int]:
    return _get_image_processing_service().apply_raw_archive_hardcoded_exif(
        records,
        output_dir=output_dir,
        progress_emit=progress_emit,
    )


def _write_raw_archive_meta(
    records: list[dict[str, Any]],
    *,
    output_dir: Path,
    rover_csv_url: str,
    rover_csv_local_path: str,
    engine_version: str,
    progress_emit: Optional[Callable[[str], None]] = None,
) -> tuple[int, int]:
    return _get_image_processing_service().write_raw_archive_meta(
        records,
        output_dir=output_dir,
        rover_csv_url=rover_csv_url,
        rover_csv_local_path=rover_csv_local_path,
        engine_version=engine_version,
        normalize_source=_normalize_source,
        progress_emit=progress_emit,
    )


def _enforce_mastcam_min_output_size(output_dir: str | Path) -> int:
    return _get_output_size_service().enforce_mastcam_min_output_size(output_dir)


def _enforce_global_min_output_size(output_dir: str | Path, threshold: int) -> int:
    return _get_output_size_service().enforce_global_min_output_size(output_dir, threshold)


def _organize_source_buckets(out: Path) -> list[Path]:
    return _get_record_output_utils_service().organize_source_buckets(out)


def organize_photos_in_output() -> tuple[bool, str]:
    path = normalize_text(st.session_state.get("download_path", ""))
    if not path:
        return False, t("output_path_required")
    res = _get_output_organizer().organize_by_camera(path)
    return bool(res.ok), res.message


def organize_photos_simple_layout() -> tuple[bool, str]:
    path = normalize_text(st.session_state.get("download_path", ""))
    if not path:
        return False, t("output_path_required")
    divide_by_sol = bool(st.session_state.get("organize_divide_by_sol", False))
    divide_by_camera = bool(st.session_state.get("organize_divide_by_camera_type", True))
    res = _get_output_organizer().organize_simple_layout(
        path,
        divide_by_sol=divide_by_sol,
        divide_by_camera=divide_by_camera,
    )
    return bool(res.ok), res.message
def _find_output_meta_for_image(src: Path, out_dir: Path) -> Optional[Path]:
    return _get_record_output_utils_service().find_output_meta_for_image(src, out_dir)


def _extract_sol_for_output_file(src: Path, out_dir: Path) -> Optional[int]:
    return _get_record_output_utils_service().extract_sol_for_output_file(src, out_dir)


def organize_photos_by_sol_in_output() -> tuple[bool, str]:
    path = normalize_text(st.session_state.get("download_path", ""))
    if not path:
        return False, t("output_path_required")
    res = _get_output_organizer().organize_by_sol(path)
    return bool(res.ok), res.message


def _load_selected_image_outputs(product_name: str) -> None:
    name = normalize_text(product_name)
    if not name:
        return
    image_path, meta_path = _resolve_output_files_for_product(name)
    st.session_state.selected_image = name
    st.session_state.selected_image_path = str(image_path) if image_path else ""
    st.session_state.selected_meta_path = str(meta_path) if meta_path else ""
    if meta_path:
        try:
            meta_obj = json.loads(meta_path.read_text(encoding="utf-8"))
            st.session_state.selected_meta_obj = meta_obj if isinstance(meta_obj, dict) else {}
        except Exception:
            st.session_state.selected_meta_obj = {}
    else:
        st.session_state.selected_meta_obj = {}


def set_download_path(path: str, persist: bool = True) -> str:
    return _get_app_config_service().set_download_path(st.session_state, path, persist)


def show_download_path_text() -> str:
    return _get_app_config_service().show_download_path_text(st.session_state)


def show_combined_config_text() -> str:
    return _get_app_config_service().show_combined_config_text()


def geo_status_text() -> str:
    return _get_app_config_service().geo_status_text()


def download_geo_csv() -> str:
    return _get_app_config_service().download_geo_csv()


def _parse_set_config(text: str) -> tuple[Optional[str], Optional[str]]:
    return _get_app_config_service().parse_set_config(text)


def _parse_cfg_value(raw: str) -> Any:
    return _get_app_config_service().parse_cfg_value(raw)


def _set_nested(cfg: dict[str, Any], dotted_key: str, value: Any) -> None:
    _get_app_config_service().set_nested(cfg, dotted_key, value)


def run_sql_query(df: pd.DataFrame, sql: str) -> tuple[bool, str, pd.DataFrame]:
    sql_clean = (sql or "").strip().rstrip(";")
    if not sql_clean:
        return False, t("sql_missing"), pd.DataFrame()
    if not re.match(r"(?is)^\s*select\b", sql_clean):
        return False, t("sql_select_only"), pd.DataFrame()
    # Guardrails: avoid freezing Streamlit by loading huge DataFrames into SQLite in-memory.
    # If the query doesn't include a LIMIT, we enforce one; and we also cap the DF rows we load.
    max_rows = 200_000
    limit_match = re.search(r"(?is)\blimit\s+(\d+)\b", sql_clean)
    if limit_match is None:
        sql_clean = f"{sql_clean} LIMIT 2000"
    if len(df) > max_rows:
        df = df.head(max_rows).copy()
    try:
        with sqlite3.connect(":memory:") as conn:
            df.to_sql("catalog", conn, index=False, if_exists="replace")
            out = pd.read_sql_query(sql_clean, conn)
    except Exception as exc:
        return False, t("sql_query_error", error=str(exc)), pd.DataFrame()
    if len(out) == 0:
        return True, t("sql_query_zero_rows"), out
    return True, t("sql_query_ok_rows", rows=len(out)), out


def choose_download_path_dialog() -> tuple[bool, str]:
    folder = choose_folder_dialog(t("select_download_folder_prompt"))
    if folder:
        set_download_path(folder, persist=True)
        return True, folder
    return False, ""


def get_selection_df(all_variants: bool = False) -> pd.DataFrame:
    return _get_selection_service().get_selection_df(st.session_state, all_variants=all_variants)


def _get_selection_df_for(state: dict[str, Any], all_variants: bool = False) -> pd.DataFrame:
    return _get_selection_service().get_selection_df(state, all_variants=all_variants)


def _selection_list_text() -> str:
    return _get_local_command_handler_service().selection_list_text(st.session_state)


def _block_filters_from_text(block_text: str, available_cams: list[str], *, mardi_legacy_mode: bool, require_lbl: bool) -> dict[str, Any]:
    return _get_local_command_handler_service().block_filters_from_text(
        st.session_state,
        block_text,
        available_cams,
        mardi_legacy_mode=mardi_legacy_mode,
        require_lbl=require_lbl,
    )


def _execute_multi_block_workflow(
    command: str,
    *,
    progress_emit: Optional[Callable[[str], None]] = None,
    action_kind: str,
    all_variants: bool,
    random_sample: bool,
    global_max_images: Optional[int],
    global_per_camera_limits: Optional[dict[str, int]],
    wants_organize: bool,
) -> str:
    return _get_local_command_handler_service().execute_multi_block_workflow(
        st.session_state,
        command,
        progress_emit=progress_emit,
        action_kind=action_kind,
        all_variants=all_variants,
        random_sample=random_sample,
        global_max_images=global_max_images,
        global_per_camera_limits=global_per_camera_limits,
        wants_organize=wants_organize,
    )


def _prepare_action_df(
    *,
    all_variants: bool = False,
    max_images: Optional[int] = None,
    random_sample: bool = False,
    per_camera_limits: Optional[dict[str, int]] = None,
    require_lbl: bool = False,
    selection_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    return _get_action_df_service().prepare_action_df(
        all_variants=all_variants,
        max_images=max_images,
        random_sample=random_sample,
        per_camera_limits=per_camera_limits,
        require_lbl=require_lbl,
        selection_df=selection_df,
        get_selection_df=get_selection_df,
        route_selection_by_catalog_boundary=_route_selection_by_catalog_boundary,
        norm_ascii=_norm_ascii,
    )


def _get_pds_max_sol() -> Optional[int]:
    return _get_catalog_selection_service().get_pds_max_sol(st.session_state)


def _get_pds_missing_sols() -> set[int]:
    return _get_catalog_selection_service().get_pds_missing_sols(st.session_state)


def _route_selection_by_catalog_boundary(df: pd.DataFrame) -> pd.DataFrame:
    return _get_catalog_selection_service().route_selection_by_catalog_boundary(st.session_state, df)


def _count_records_for_action(
    action_type: str,
    all_variants: bool,
    max_images: Optional[int] = None,
    random_sample: bool = False,
    per_camera_limits: Optional[dict[str, int]] = None,
    selection_df: Optional[pd.DataFrame] = None,
) -> int:
    return _get_local_command_handler_service().count_records_for_action(
        action_type,
        all_variants=all_variants,
        max_images=max_images,
        random_sample=random_sample,
        per_camera_limits=per_camera_limits,
        selection_df=selection_df,
    )


def run_download(
    all_variants: bool = False,
    progress_emit: Optional[callable] = None,
    max_images: Optional[int] = None,
    random_sample: bool = False,
    per_camera_limits: Optional[dict[str, int]] = None,
    selection_df: Optional[pd.DataFrame] = None,
) -> str:
    return _get_download_processing_service().run_download(
        requested_path=normalize_text(st.session_state.get("download_path", "")),
        all_variants=all_variants,
        progress_emit=progress_emit,
        max_images=max_images,
        random_sample=random_sample,
        per_camera_limits=per_camera_limits,
        selection_df=selection_df,
        reference_df=st.session_state.get("df"),
    )


def run_process(
    all_variants: bool = False,
    progress_emit: Optional[callable] = None,
    max_images: Optional[int] = None,
    random_sample: bool = False,
    per_camera_limits: Optional[dict[str, int]] = None,
    selection_df: Optional[pd.DataFrame] = None,
) -> str:
    return _get_download_processing_service().run_process(
        requested_path=normalize_text(st.session_state.get("download_path", "")),
        all_variants=all_variants,
        progress_emit=progress_emit,
        max_images=max_images,
        random_sample=random_sample,
        per_camera_limits=per_camera_limits,
        selection_df=selection_df,
        reference_df=st.session_state.get("df"),
    )


def run_download_and_process_interleaved(
    all_variants: bool = False,
    progress_emit: Optional[callable] = None,
    max_images: Optional[int] = None,
    random_sample: bool = False,
    per_camera_limits: Optional[dict[str, int]] = None,
    selection_df: Optional[pd.DataFrame] = None,
) -> str:
    return _get_download_processing_service().run_download_and_process_interleaved(
        requested_path=normalize_text(st.session_state.get("download_path", "")),
        stop_requested_getter=lambda: bool(st.session_state.get("stop_requested", False)),
        all_variants=all_variants,
        progress_emit=progress_emit,
        max_images=max_images,
        random_sample=random_sample,
        per_camera_limits=per_camera_limits,
        selection_df=selection_df,
        reference_df=st.session_state.get("df"),
    )
def run_catalog_update_from_text(command: str) -> str:
    return _get_catalog_update_service().run_catalog_update_from_text(st.session_state, command)


def execute_action(payload: dict[str, Any]) -> str:
    return _get_action_dispatcher_service().execute_action(st.session_state, payload)


def _default_filters_state() -> dict[str, Any]:
    return _get_selection_service().default_filters_state()


def _reset_filters_state(*, preserve_selection: bool = False) -> int:
    return _reset_filters_state_for(st.session_state, preserve_selection=preserve_selection)


def _reset_filters_state_for(state: dict[str, Any], *, preserve_selection: bool = False) -> int:
    return _get_selection_service().reset_filters_state(
        state,
        apply_filters=apply_filters,
        preserve_selection=preserve_selection,
    )


def _filters_are_default() -> bool:
    return _get_selection_service().filters_are_default(st.session_state)


def handle_local(
    command: str,
    progress_emit: Optional[callable] = None,
) -> tuple[bool, str]:
    return _get_local_command_handler_service().handle_local(st.session_state, command, progress_emit=progress_emit)


def submit_command(command: str, progress_slot: Any = None, progress_bar: Any = None) -> None:
    _get_command_submission_service().submit_command(
        st.session_state,
        command,
        progress_slot=progress_slot,
        progress_bar=progress_bar,
    )


def run_builder_download_process_organize(
    *,
    state: Optional[dict[str, Any]] = None,
    filters: Optional[dict[str, Any]] = None,
    progress_emit: Optional[Callable[[str], None]] = None,
    apply_filters_progress: Optional[Callable[[float, str], None]] = None,
    max_images: Optional[int] = None,
    wants_organize: bool = True,
) -> tuple[bool, str]:
    """
    Builder-only execution path: run download+process(+organize) without creating an internal command string.

    Keeps bulk-confirmation behavior identical:
    - if `max_images` is None and the actionable total exceeds DEFAULT_BULK_CONFIRM_THRESHOLD,
      sets `pending_bulk_action` and returns (False, "bulk_required"). The existing bulk modal will handle it.
    """
    if state is None:
        state = st.session_state
    if filters is not None:
        state["filters"] = filters
    if apply_filters_progress is not None:
        try:
            rows = apply_filters(progress=apply_filters_progress)
            state["filtered_rows_count"] = int(rows) if rows is not None else 0
        except Exception:
            state["filtered_rows_count"] = int(state.get("filtered_rows_count", 0) or 0)

    # Count actionable records exactly like the command workflow does (no limit for bulk decision).
    state["stop_requested"] = False
    total = _count_records_for_action("download_process", all_variants=False, max_images=None, random_sample=False)
    state["last_actionable_total"] = int(total)
    if (max_images is None) and total > int(DEFAULT_BULK_CONFIRM_THRESHOLD):
        state["pending_bulk_action"] = {
            "type": "download_process",
            "all_variants": False,
            "total": int(total),
            "per_camera_limits": None,
        }
        return False, "bulk_required"

    # Keep the live log in sync with progress callbacks.
    progress_lines: list[str] = []
    state["is_processing"] = True

    def _emit(line: str) -> None:
        msg = normalize_text(line)
        if not msg:
            return
        progress_lines.append(msg)
        state["operation_live_text"] = "\n".join(progress_lines[-14:])
        if progress_emit is not None:
            try:
                progress_emit(msg)
            except Exception:
                pass

    try:
        action_msg = run_download_and_process_interleaved(
            all_variants=False,
            progress_emit=_emit,
            max_images=max_images,
            random_sample=False,
            per_camera_limits=None,
            selection_df=None,
        )
        org_msg = ""
        if wants_organize:
            _, org_msg = organize_photos_simple_layout()
        out = f"{action_msg}\n\n{org_msg}".strip() if org_msg else action_msg
        return True, out
    finally:
        state["is_processing"] = False
