from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd

from parser import (
    _append_parser_debug,
    _bulk_cancel_words,
    _bulk_cancelled_text,
    _bulk_confirmation_text,
    _bulk_proceed_words,
    _cfg_keywords,
    _contains_word,
    _has_download_intent,
    _has_process_intent,
    _has_workflow_action_words,
    _intent_match,
    _is_camera_list_request,
    _is_unsupported_image_url_request,
    _normalize_camera_key,
    _normalize_command_for_parser,
    _no_pending_bulk_text,
    _parse_camera_quota_map,
    _parse_cameras,
    _parse_dr_variants,
    _parse_each_camera_count,
    _parse_int,
    _parse_requested_image_count,
    _parse_size_bytes_from_text,
    _parse_sol_range,
    _split_multi_range_blocks,
    _wants_all_cameras,
    _wants_organize_step,
    _wants_random_sample,
)
from portable_engine_adapter import records_from_dataframe  # type: ignore
from runtime import DEFAULT_BULK_CONFIRM_THRESHOLD, _ensure_writable_download_path


class LocalCommandHandlerService:
    def __init__(
        self,
        *,
        translator: Callable[..., str],
        normalize_text: Callable[[Any], str],
        norm_ascii: Callable[[str], str],
        mardi_legacy_mode_enabled: Callable[[], bool],
        analytics_use_filtered_scope: Callable[[str], bool],
        apply_filters: Callable[[], int],
        camera_types_report: Callable[[], str],
        catalog_content_report: Callable[..., str],
        database_count_report: Callable[..., str],
        database_max_sol_report: Callable[..., str],
        is_analytics_query: Callable[[str], bool],
        filter_dataframe: Callable[[pd.DataFrame, dict[str, Any]], pd.DataFrame],
        selection_report: Callable[[], str],
        reset_filters_state: Callable[[dict[str, Any]], int],
        prepare_action_df: Callable[..., pd.DataFrame],
        run_download: Callable[..., str],
        run_process: Callable[..., str],
        run_download_and_process_interleaved: Callable[..., str],
        organize_photos_simple_layout: Callable[[], tuple[bool, str]],
        choose_download_path_dialog: Callable[[], tuple[bool, str]],
        set_download_path: Callable[..., str],
        show_combined_config_text: Callable[[], str],
        show_download_path_text: Callable[[], str],
        geo_status_text: Callable[[], str],
        download_geo_csv: Callable[[], str],
        parse_set_config: Callable[[str], tuple[Optional[str], Optional[str]]],
        parse_cfg_value: Callable[[str], Any],
        set_nested: Callable[[dict[str, Any], str, Any], None],
        load_json: Callable[..., Any],
        save_json: Callable[..., Any],
        resolve_msl_config: Callable[[], str | Path],
        run_catalog_update_from_text: Callable[[str], str],
        get_selection_df: Callable[[dict[str, Any], bool], pd.DataFrame],
    ) -> None:
        self._t = translator
        self._normalize_text = normalize_text
        self._norm_ascii = norm_ascii
        self._mardi_legacy_mode_enabled = mardi_legacy_mode_enabled
        self._analytics_use_filtered_scope = analytics_use_filtered_scope
        self._apply_filters = apply_filters
        self._camera_types_report = camera_types_report
        self._catalog_content_report = catalog_content_report
        self._database_count_report = database_count_report
        self._database_max_sol_report = database_max_sol_report
        self._is_analytics_query = is_analytics_query
        self._filter_dataframe = filter_dataframe
        self._selection_report = selection_report
        self._reset_filters_state = reset_filters_state
        self._prepare_action_df = prepare_action_df
        self._run_download = run_download
        self._run_process = run_process
        self._run_download_and_process_interleaved = run_download_and_process_interleaved
        self._organize_photos_simple_layout = organize_photos_simple_layout
        self._choose_download_path_dialog = choose_download_path_dialog
        self._set_download_path = set_download_path
        self._show_combined_config_text = show_combined_config_text
        self._show_download_path_text = show_download_path_text
        self._geo_status_text = geo_status_text
        self._download_geo_csv = download_geo_csv
        self._parse_set_config = parse_set_config
        self._parse_cfg_value = parse_cfg_value
        self._set_nested = set_nested
        self._load_json = load_json
        self._save_json = save_json
        self._resolve_msl_config = resolve_msl_config
        self._run_catalog_update_from_text = run_catalog_update_from_text
        self._get_selection_df = get_selection_df

    def _selection_list_text(self, state: dict[str, Any]) -> str:
        df = self._get_selection_df(state, False)
        if len(df) == 0:
            return self._t("selection_empty")

        lines: list[str] = []
        for idx, (_, row) in enumerate(df.iterrows(), start=1):
            product = self._normalize_text(row.get("product_id"))
            img_url = self._normalize_text(row.get("img_url"))
            file_name = self._normalize_text(img_url).rsplit("/", 1)[-1] if img_url else ""
            name = product or file_name or f"row_{idx}"
            sol = self._normalize_text(row.get("sol"))
            camera = self._normalize_text(row.get("camera"))
            meta_parts: list[str] = []
            if sol:
                meta_parts.append(f"sol={sol}")
            if camera:
                meta_parts.append(f"camera={camera}")
            meta_txt = f" ({', '.join(meta_parts)})" if meta_parts else ""
            lines.append(f"{idx}. {name}{meta_txt}")

        return "\n".join(lines)

    def _block_filters_from_text(
        self,
        state: dict[str, Any],
        block_text: str,
        available_cams: list[str],
        *,
        mardi_legacy_mode: bool,
        require_lbl: bool,
    ) -> dict[str, Any]:
        cur_filters = state.get("filters", {}) or {}
        filters: dict[str, Any] = {
            "sol_start": None,
            "sol_end": None,
            "cameras": [],
            "source_pds": bool(cur_filters.get("source_pds", True)),
            "source_raw": bool(cur_filters.get("source_raw", True)),
            "min_img_size": None,
            "only_with_lbl": require_lbl,
            "dr_variants": [],
            "name_tokens": [],
            "file_prefixes": [],
            "file_name_contains": [],
            "mastcam_only_drcl": False,
            "mahli_only_drcl": False,
            "mardi_only_e01_drcx": False,
            "navcam_only_iltlf": False,
            "hazcam_only_lb_edr": False,
        }
        sol_start, sol_end = _parse_sol_range(block_text)
        if sol_start is not None:
            filters["sol_start"] = min(sol_start, sol_end or sol_start)
            filters["sol_end"] = max(sol_start, sol_end or sol_start)
        cams = _parse_cameras(block_text, available_cams)
        if cams:
            filters["cameras"] = cams
        size_bytes = _parse_size_bytes_from_text(block_text)
        if size_bytes is not None:
            filters["min_img_size"] = int(size_bytes)

        cams_norm = {_normalize_camera_key(str(c)) for c in (cams or [])}
        if "mastcam" in cams_norm:
            filters["mastcam_only_drcl"] = True
        if "mahli" in cams_norm:
            filters["mahli_only_drcl"] = True
        if "mardi" in cams_norm and mardi_legacy_mode:
            filters["mardi_only_e01_drcx"] = True
        if "navcam" in cams_norm:
            filters["navcam_only_iltlf"] = True
        if "hazcam" in cams_norm:
            filters["hazcam_only_lb_edr"] = True
        return filters

    def _execute_multi_block_workflow(
        self,
        state: dict[str, Any],
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
        blocks = _split_multi_range_blocks(command)
        if len(blocks) < 2:
            return ""

        df_all = state.get("df")
        if isinstance(df_all, pd.DataFrame) and "camera" in df_all.columns:
            available_cams = sorted(set(df_all["camera"].dropna().astype(str)))
        else:
            available_cams = []
        base_df = self._get_selection_df(state, all_variants=all_variants)
        mardi_legacy_mode = self._mardi_legacy_mode_enabled()
        report_lines: list[str] = []

        for idx, block in enumerate(blocks, start=1):
            block_filters = self._block_filters_from_text(
                state,
                block,
                available_cams,
                mardi_legacy_mode=mardi_legacy_mode,
                require_lbl=(action_kind == "process"),
            )
            block_df = self._filter_dataframe(base_df, block_filters)
            if len(block_df) == 0:
                report_lines.append(self._t("block_no_matching_records", index=idx, block=block))
                continue

            block_cams = block_filters.get("cameras") or []
            block_per_camera_limits = _parse_camera_quota_map(block, available_cams)
            requested_each_camera = _parse_each_camera_count(block)
            requested_max_images = _parse_requested_image_count(block)
            if requested_each_camera and requested_each_camera > 0:
                for cam_name in block_cams:
                    if str(cam_name) not in block_per_camera_limits:
                        block_per_camera_limits[str(cam_name)] = int(requested_each_camera)
                if requested_max_images is not None and int(requested_max_images) == int(requested_each_camera) and not re.search(
                    r"\b(?:totali|totale|total|overall|max(?:imum)?)\b",
                    block,
                    re.IGNORECASE,
                ):
                    requested_max_images = None
            if requested_max_images is None and block_per_camera_limits:
                try:
                    quota_sum = sum(int(v) for v in block_per_camera_limits.values() if int(v) > 0)
                    if quota_sum > 0:
                        requested_max_images = quota_sum
                except Exception:
                    pass
            if global_max_images is not None and requested_max_images is None:
                requested_max_images = global_max_images

            block_progress = progress_emit
            if block_progress:
                block_progress(f"[block {idx}/{len(blocks)}] {block}")

            if action_kind == "download_process":
                msg = self._run_download_and_process_interleaved(
                    all_variants=all_variants,
                    progress_emit=block_progress,
                    max_images=requested_max_images,
                    random_sample=random_sample,
                    per_camera_limits=block_per_camera_limits or global_per_camera_limits,
                    selection_df=block_df,
                )
            elif action_kind == "download":
                msg = self._run_download(
                    all_variants=all_variants,
                    progress_emit=block_progress,
                    max_images=requested_max_images,
                    random_sample=random_sample,
                    per_camera_limits=block_per_camera_limits or global_per_camera_limits,
                    selection_df=block_df,
                )
            elif action_kind == "process":
                msg = self._run_process(
                    all_variants=all_variants,
                    progress_emit=block_progress,
                    max_images=requested_max_images,
                    random_sample=random_sample,
                    per_camera_limits=block_per_camera_limits or global_per_camera_limits,
                    selection_df=block_df,
                )
            else:
                msg = ""

            report_lines.append(f"[block {idx}] {block}\n{msg}".strip())

        if wants_organize:
            ok, org_msg = self._organize_photos_simple_layout()
            if ok:
                report_lines.append(org_msg)
            else:
                report_lines.append(org_msg)

        return "\n\n".join([line for line in report_lines if line.strip()])

    def _count_records_for_action(
        self,
        action_type: str,
        *,
        all_variants: bool,
        max_images: Optional[int] = None,
        random_sample: bool = False,
        per_camera_limits: Optional[dict[str, int]] = None,
        selection_df: Optional[pd.DataFrame] = None,
    ) -> int:
        require_lbl = False
        df = self._prepare_action_df(
            all_variants=all_variants,
            max_images=max_images,
            random_sample=random_sample,
            per_camera_limits=per_camera_limits,
            require_lbl=require_lbl,
            selection_df=selection_df,
        )
        return len(records_from_dataframe(df, require_lbl=require_lbl))

    # Exposed for backwards-compat while refactoring `actions.py` helpers.
    def selection_list_text(self, state: dict[str, Any]) -> str:
        return self._selection_list_text(state)

    def block_filters_from_text(
        self,
        state: dict[str, Any],
        block_text: str,
        available_cams: list[str],
        *,
        mardi_legacy_mode: bool,
        require_lbl: bool,
    ) -> dict[str, Any]:
        return self._block_filters_from_text(
            state,
            block_text,
            available_cams,
            mardi_legacy_mode=mardi_legacy_mode,
            require_lbl=require_lbl,
        )

    def execute_multi_block_workflow(
        self,
        state: dict[str, Any],
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
        return self._execute_multi_block_workflow(
            state,
            command,
            progress_emit=progress_emit,
            action_kind=action_kind,
            all_variants=all_variants,
            random_sample=random_sample,
            global_max_images=global_max_images,
            global_per_camera_limits=global_per_camera_limits,
            wants_organize=wants_organize,
        )

    def count_records_for_action(
        self,
        action_type: str,
        *,
        all_variants: bool,
        max_images: Optional[int] = None,
        random_sample: bool = False,
        per_camera_limits: Optional[dict[str, int]] = None,
        selection_df: Optional[pd.DataFrame] = None,
    ) -> int:
        return self._count_records_for_action(
            action_type,
            all_variants=all_variants,
            max_images=max_images,
            random_sample=random_sample,
            per_camera_limits=per_camera_limits,
            selection_df=selection_df,
        )

    def handle_local(
        self,
        state: dict[str, Any],
        command: str,
        *,
        progress_emit: Optional[callable] = None,
    ) -> tuple[bool, str]:
        t = self._t
        normalize_text = self._normalize_text
        _norm_ascii = self._norm_ascii
        _mardi_legacy_mode_enabled = self._mardi_legacy_mode_enabled
        _reset_filters_state = self._reset_filters_state
        run_download = self._run_download
        run_process = self._run_process
        run_download_and_process_interleaved = self._run_download_and_process_interleaved
        organize_photos_simple_layout = self._organize_photos_simple_layout
        choose_download_path_dialog = self._choose_download_path_dialog
        set_download_path = self._set_download_path
        show_combined_config_text = self._show_combined_config_text
        show_download_path_text = self._show_download_path_text
        geo_status_text = self._geo_status_text
        download_geo_csv = self._download_geo_csv
        _parse_set_config = self._parse_set_config
        _parse_cfg_value = self._parse_cfg_value
        _set_nested = self._set_nested
        load_json = self._load_json
        save_json = self._save_json
        _resolve_msl_config = self._resolve_msl_config
        run_catalog_update_from_text = self._run_catalog_update_from_text
        get_selection_df = self._get_selection_df

        cmd = _normalize_command_for_parser(command)
        cmd_ascii = _norm_ascii(cmd)
        df = state.get("df_filtered")
        if not isinstance(df, pd.DataFrame):
            df = pd.DataFrame()
        has_download_word = _has_download_intent(cmd)
        has_convert_word = _has_process_intent(cmd) or _contains_word(cmd, ["conversione"])
        has_fetch_word = _contains_word(cmd, ["get", "fetch", "recupera", "prendi"])
        wants_organize = _wants_organize_step(cmd)
        requested_max_images = _parse_requested_image_count(cmd)
        wants_random = _wants_random_sample(cmd)
        requested_each_camera = _parse_each_camera_count(cmd)
        original_filters = copy.deepcopy(state.get("filters", {}))
        pending = state.get("pending_bulk_action")

        if isinstance(pending, dict):
            action_type = normalize_text(pending.get("type"))
            if _contains_word(cmd, _bulk_cancel_words()):
                state["pending_bulk_action"] = None
                return True, _bulk_cancelled_text()

            limit: Optional[int] = None
            n = _parse_int(cmd, r"\b(\d{1,6})\b")
            if n is not None and n > 0:
                limit = int(n)
            elif _contains_word(cmd, _bulk_proceed_words()):
                limit = None
            else:
                return True, _bulk_confirmation_text(int(pending.get("total", 0)), action_type=action_type or "download_process")

            all_variants = bool(pending.get("all_variants", False))
            per_camera_limits = pending.get("per_camera_limits")
            state["pending_bulk_action"] = None
            if action_type == "download_process":
                action_msg = run_download_and_process_interleaved(
                    all_variants=all_variants,
                    progress_emit=progress_emit,
                    max_images=limit,
                    random_sample=False,
                    per_camera_limits=per_camera_limits,
                )
                _, org_msg = organize_photos_simple_layout()
                return True, f"{action_msg}\n\n{org_msg}".strip()
            if action_type == "download":
                action_msg = run_download(
                    all_variants=all_variants,
                    progress_emit=progress_emit,
                    max_images=limit,
                    random_sample=False,
                    per_camera_limits=per_camera_limits,
                )
                _, org_msg = organize_photos_simple_layout()
                return True, f"{action_msg}\n\n{org_msg}".strip()
            return True, _no_pending_bulk_text()

        if _is_unsupported_image_url_request(cmd):
            return True, t("unsupported_image_url_request")
        # Robust natural-language fallbacks for common filter intents.
        if re.search(r"\b(?:mostra|mostrami|show|affiche|mostrar|zeige)\b", cmd_ascii) and re.search(r"\bfiltr\w*\b", cmd_ascii):
            return True, json.dumps(state.get("filters", {}), ensure_ascii=False)
        if re.search(r"\b(?:reset\w*|azzera\w*|cancell\w*)\b", cmd_ascii) and re.search(r"\bfiltr\w*\b", cmd_ascii):
            n = _reset_filters_state(state)
            return True, t("filters_reset_rows", rows=n)
        if _intent_match("size_counts", cmd):
            if "img_size_bytes" in df.columns:
                non_null = int(pd.to_numeric(df["img_size_bytes"], errors="coerce").notna().sum())
                return True, t("size_counts_with_col", rows=len(df), non_null=non_null)
            return True, t("size_counts_no_col", rows=len(df))
        if _intent_match("help", cmd):
            return True, t("help_commands")
        if _intent_match("filter_examples", cmd):
            return True, t("help_filter_examples")
        if _intent_match("schema", cmd):
            return True, "\n".join(f"- {c}: {df[c].dtype}" for c in df.columns)
        if _intent_match("report", cmd):
            return True, self._catalog_content_report(use_filtered=self._analytics_use_filtered_scope(command))
        if _intent_match("contains", cmd):
            return True, self._catalog_content_report(use_filtered=self._analytics_use_filtered_scope(command))
        if (_is_camera_list_request(cmd) or _intent_match("camera_types", cmd)) and not _has_workflow_action_words(cmd):
            return True, self._camera_types_report()
        if _intent_match("config_show", cmd):
            return True, show_combined_config_text()
        if _intent_match("show_download_path", cmd):
            return True, show_download_path_text()
        if _intent_match("config_dialog", cmd):
            return True, t("config_dialog_hint")
        if _intent_match("geo_status", cmd):
            return True, geo_status_text()
        if _intent_match("geo_download", cmd):
            try:
                return True, download_geo_csv()
            except Exception as exc:
                return True, t("geo_download_error", error=str(exc))
        if _intent_match("config_set", cmd):
            key, val = _parse_set_config(command)
            if not key:
                return True, t("config_set_usage")
            cfg = load_json(_resolve_msl_config())
            _set_nested(cfg, key, _parse_cfg_value(val or ""))
            save_json(_resolve_msl_config(), cfg)
            return True, t("config_updated", key=key)

        has_operational_words = has_download_word or has_convert_word or has_fetch_word or wants_organize
        multi_blocks = _split_multi_range_blocks(cmd)
        if len(multi_blocks) >= 2 and (has_operational_words or requested_max_images is not None or requested_each_camera is not None):
            block_kind = "download_process"
            if has_convert_word and not has_download_word and not has_fetch_word:
                block_kind = "process"
            elif has_download_word and not has_convert_word and not has_fetch_word and not wants_organize:
                block_kind = "download"
            return True, self._execute_multi_block_workflow(
                state,
                command,
                progress_emit=progress_emit,
                action_kind=block_kind,
                all_variants=any(t in cmd for t in _cfg_keywords("all_variants")),
                random_sample=wants_random,
                global_max_images=requested_max_images if requested_max_images and requested_max_images > 0 else None,
                global_per_camera_limits=None,
                wants_organize=wants_organize,
            )
        if self._is_analytics_query(cmd) and not has_operational_words:
            use_filtered = self._analytics_use_filtered_scope(command)
            if "sol" in _norm_ascii(cmd) and _contains_word(
                cmd,
                ["piu", "massimo", "max", "most", "highest", "plus", "mehr", "mayor", "mas"],
            ):
                return True, self._database_max_sol_report(command, use_filtered=use_filtered)
            return True, self._database_count_report(command, use_filtered=use_filtered)

        changed = False
        navcam_rule_active = False
        hazcam_rule_active = False
        mardi_rule_active = False
        mardi_legacy_mode = _mardi_legacy_mode_enabled()
        filters_state = state.setdefault("filters", {})
        if not isinstance(filters_state, dict):
            filters_state = {}
            state["filters"] = filters_state

        sol_start, sol_end = _parse_sol_range(cmd)
        if sol_start is not None:
            filters_state["sol_start"] = min(sol_start, sol_end or sol_start)
            filters_state["sol_end"] = max(sol_start, sol_end or sol_start)
            changed = True
        df_all = state.get("df")
        if isinstance(df_all, pd.DataFrame) and "camera" in df_all.columns:
            available_cams = sorted(set(df_all["camera"].dropna().astype(str)))
        else:
            available_cams = []
        wants_all_cams = _wants_all_cameras(cmd)
        cams = _parse_cameras(cmd, available_cams)
        if wants_all_cams and available_cams:
            cams = list(available_cams)
        if cams:
            filters_state["cameras"] = cams
            if wants_all_cams:
                filters_state["name_tokens"] = []
                filters_state["file_prefixes"] = []
                filters_state["file_name_contains"] = []
            changed = True
        size_bytes = _parse_size_bytes_from_text(cmd)
        if size_bytes is None and _intent_match("min_size", cmd):
            size_bytes = _parse_int(cmd, r"(\d{3,})")
        if size_bytes is not None:
            filters_state["min_img_size"] = int(size_bytes)
            changed = True
        if _intent_match("only_with_lbl", cmd):
            filters_state["only_with_lbl"] = True
            changed = True
        if _intent_match("dr_variants", cmd):
            found = _parse_dr_variants(cmd)
            if not found and any(t in cmd for t in _cfg_keywords("dr_family_words")):
                found = ["DRCL", "DRCX", "DRLX", "DRXX"]
            if found:
                filters_state["dr_variants"] = found
                changed = True
        if _intent_match("name_tokens", cmd):
            tokens = sorted(set(re.findall(r"\b(NCAM|FHAZ|RHAZ)\b", cmd.upper())))
            if tokens:
                filters_state["name_tokens"] = tokens
                changed = True
        if _intent_match("navcam_token", cmd):
            filters_state["navcam_only_iltlf"] = True
            navcam_rule_active = True
            changed = True
        if _intent_match("hazcam_token", cmd):
            filters_state["name_tokens"] = ["FHAZ", "RHAZ"]
            filters_state["file_prefixes"] = []
            filters_state["file_name_contains"] = []
            filters_state["hazcam_only_lb_edr"] = True
            hazcam_rule_active = True
            changed = True
        mastcam_mentioned = bool(re.search(r"\bmastcam\b", cmd))
        if not mastcam_mentioned and cams:
            mastcam_mentioned = any(_normalize_camera_key(str(c)) == "mastcam" for c in cams)
        if mastcam_mentioned:
            filters_state["mastcam_only_drcl"] = True
            changed = True
        else:
            cams_norm = [_normalize_camera_key(str(c)) for c in (cams or [])]
            if cams_norm and "mastcam" not in cams_norm and filters_state.get("mastcam_only_drcl"):
                filters_state["mastcam_only_drcl"] = False
                changed = True
        mahli_mentioned = bool(re.search(r"\bmahli\b", cmd))
        if not mahli_mentioned and cams:
            mahli_mentioned = any(_normalize_camera_key(str(c)) == "mahli" for c in cams)
        if mahli_mentioned:
            filters_state["mahli_only_drcl"] = True
            changed = True
        else:
            cams_norm = [_normalize_camera_key(str(c)) for c in (cams or [])]
            if cams_norm and "mahli" not in cams_norm and filters_state.get("mahli_only_drcl"):
                filters_state["mahli_only_drcl"] = False
                changed = True
        mardi_mentioned = bool(re.search(r"\bmardi\b", cmd))
        if not mardi_mentioned and cams:
            mardi_mentioned = any(_normalize_camera_key(str(c)) == "mardi" for c in cams)
        if mardi_mentioned and mardi_legacy_mode:
            filters_state["mardi_only_e01_drcx"] = True
            mardi_rule_active = True
            changed = True
        else:
            cams_norm = [_normalize_camera_key(str(c)) for c in (cams or [])]
            if (not mardi_legacy_mode or (cams_norm and "mardi" not in cams_norm)) and filters_state.get("mardi_only_e01_drcx"):
                filters_state["mardi_only_e01_drcx"] = False
                changed = True
        navcam_mentioned = bool(re.search(r"\bnavcam\b", cmd))
        if not navcam_mentioned and cams:
            navcam_mentioned = any(_normalize_camera_key(str(c)) == "navcam" for c in cams)
        if navcam_mentioned and has_operational_words:
            filters_state["navcam_only_iltlf"] = True
            navcam_rule_active = True
            changed = True
        else:
            cams_norm = [_normalize_camera_key(str(c)) for c in (cams or [])]
            if cams_norm and "navcam" not in cams_norm and filters_state.get("navcam_only_iltlf"):
                filters_state["navcam_only_iltlf"] = False
                changed = True
        hazcam_mentioned = bool(re.search(r"\bhazcam\b", cmd))
        if not hazcam_mentioned and cams:
            hazcam_mentioned = any(_normalize_camera_key(str(c)) == "hazcam" for c in cams)
        if hazcam_mentioned:
            filters_state["hazcam_only_lb_edr"] = True
            hazcam_rule_active = True
            changed = True
        else:
            cams_norm = [_normalize_camera_key(str(c)) for c in (cams or [])]
            if cams_norm and "hazcam" not in cams_norm and filters_state.get("hazcam_only_lb_edr"):
                filters_state["hazcam_only_lb_edr"] = False
                changed = True
        wants_download_and_process = (
            _intent_match("download_and_process", cmd)
            or (has_download_word and has_convert_word)
            or (has_fetch_word and has_convert_word)
        )
        wants_download_only = (
            (has_download_word or has_fetch_word or _intent_match("download_selection", cmd))
            and not wants_download_and_process
        )
        wants_process_only = has_convert_word and not has_download_word and not has_fetch_word and not wants_download_and_process
        has_explain_intent = _contains_word(
            cmd,
            [
                "spiega",
                "spiegami",
                "parla",
                "parlami",
                "confronta",
                "differenza",
                "consigli",
                "consiglio",
                "descrivi",
                "riassumi",
                "explain",
                "describe",
                "difference",
                "compare",
                "advice",
                "tips",
                "summarize",
                "overview",
            ],
        )
        if changed and has_explain_intent and not _has_workflow_action_words(cmd) and not wants_download_and_process and not wants_download_only and not wants_process_only and not wants_organize:
            state["filters"] = original_filters
            return False, ""
        all_variants = any(t in cmd for t in _cfg_keywords("all_variants"))
        per_camera_limits = _parse_camera_quota_map(cmd, available_cams)
        if requested_each_camera and requested_each_camera > 0:
            f_tmp = state.get("filters", {}) or {}
            if not isinstance(f_tmp, dict):
                f_tmp = {}
            target_cams = cams or (f_tmp.get("cameras") or [])
            if not target_cams:
                df_eff = state.get("df_filtered")
                if isinstance(df_eff, pd.DataFrame) and "camera" in df_eff.columns and len(df_eff) > 0:
                    target_cams = sorted({str(v) for v in df_eff["camera"].dropna().astype(str) if str(v).strip()})
            for cam_name in target_cams:
                if str(cam_name) not in per_camera_limits:
                    per_camera_limits[str(cam_name)] = int(requested_each_camera)
            if requested_max_images is not None and int(requested_max_images) == int(requested_each_camera) and not re.search(
                r"\b(?:totali|totale|total|overall|max(?:imum)?)\b",
                cmd,
                re.IGNORECASE,
            ):
                requested_max_images = None
        if requested_max_images is None and per_camera_limits:
            try:
                quota_sum = sum(int(v) for v in per_camera_limits.values() if int(v) > 0)
                if quota_sum > 0:
                    requested_max_images = quota_sum
            except Exception:
                pass

        parser_debug = ""
        filter_msg = ""
        if changed:
            n = self._apply_filters()
            filter_msg = t("filters_applied_rows", rows=n) + "\n" + self._selection_report()
            if not (wants_download_and_process or wants_download_only):
                return True, _append_parser_debug(filter_msg, parser_debug)
        if _intent_match("reset_filters", cmd):
            n = _reset_filters_state(state)
            return True, t("filters_reset_rows", rows=n)
        f_eff = state.get("filters", {}) or {}
        if not isinstance(f_eff, dict):
            f_eff = {}
        sol_s = f_eff.get("sol_start")
        sol_e = f_eff.get("sol_end")
        if sol_s is not None:
            sol_txt = f"{min(sol_s, sol_e or sol_s)}..{max(sol_s, sol_e or sol_s)}"
        else:
            sol_txt = "-"
        cam_values: list[str] = []
        df_eff = state.get("df_filtered")
        if isinstance(df_eff, pd.DataFrame) and len(df_eff) > 0 and "camera" in df_eff.columns:
            cam_values = sorted({str(v) for v in df_eff["camera"].dropna().astype(str) if str(v).strip()})
        if not cam_values:
            cam_values = [str(v) for v in (f_eff.get("cameras") or []) if str(v).strip()]
        cams_txt = ",".join(cam_values) if cam_values else "-"
        min_size_eff = f_eff.get("min_img_size")
        min_size_txt = str(min_size_eff) if min_size_eff is not None else "-"
        max_txt = str(requested_max_images) if requested_max_images is not None else "-"
        actions: list[str] = []
        if wants_download_and_process:
            actions.append("download+process")
        elif wants_download_only:
            actions.append("download")
        elif wants_process_only:
            actions.append("process")
        if wants_organize:
            actions.append("organize")
        action_txt = ",".join(actions) if actions else "-"
        parser_debug = (
            f"[parser-plan] sol={sol_txt}; cameras={cams_txt}; min_size={min_size_txt}; "
            f"max_images={max_txt}; random={'yes' if wants_random else 'no'}; "
            f"per_camera={json.dumps(per_camera_limits, ensure_ascii=False) if per_camera_limits else '-'}; "
            f"navcam_rule={'on' if bool(f_eff.get('navcam_only_iltlf')) else 'off'}; "
            f"hazcam_rule={'on' if bool(f_eff.get('hazcam_only_lb_edr')) else 'off'}; "
            f"mastcam_drcl_rule={'on' if bool(f_eff.get('mastcam_only_drcl')) else 'off'}; "
            f"mahli_drcl_rule={'on' if bool(f_eff.get('mahli_only_drcl')) else 'off'}; "
            f"mardi_legacy_mode={'on' if mardi_legacy_mode else 'off'}; "
            f"mardi_drcl_e01e00c00_rule={'on' if bool(f_eff.get('mardi_only_e01_drcx')) else 'off'}; "
            f"all_variants={'yes' if all_variants else 'no'}; actions={action_txt}"
        )
        if _intent_match("show_filters", cmd):
            return True, json.dumps(state.get("filters", {}), ensure_ascii=False)
        if _intent_match("selection_report", cmd):
            return True, _append_parser_debug(self._selection_report(), parser_debug)
        if _intent_match("selection_list", cmd):
            return True, _append_parser_debug(self._selection_list_text(state), parser_debug)
        if wants_organize and not (has_download_word or has_convert_word or has_fetch_word):
            ok, msg = organize_photos_simple_layout()
            return True, _append_parser_debug(msg, parser_debug)
        if _intent_match("choose_path", cmd):
            ok, path = choose_download_path_dialog()
            return True, t("path_set", path=path) if ok else t("path_not_selected")
        if _intent_match("set_download_path", cmd) and "=" in cmd:
            set_path = set_download_path(cmd.split("=", 1)[1], persist=True)
            return True, t("path_set", path=set_path)
        if wants_download_and_process:
            if isinstance(state.get("filters"), dict) and state["filters"].get("only_with_lbl"):
                state["filters"]["only_with_lbl"] = False
                changed = True
            total = self._count_records_for_action(
                "download_process",
                all_variants=all_variants,
                max_images=requested_max_images,
                random_sample=wants_random,
                per_camera_limits=per_camera_limits,
            )
            availability_note = ""
            if requested_max_images is not None and int(requested_max_images) > total:
                availability_note = t("parser_requested_actionable", requested=int(requested_max_images), available=int(total))
            if total <= 0:
                out_msg = t("no_results_after_filters")
                if availability_note:
                    out_msg = f"{availability_note}\n{out_msg}"
                out_msg = f"{filter_msg}\n\n{out_msg}".strip() if filter_msg else out_msg
                return True, _append_parser_debug(out_msg, parser_debug)
            if requested_max_images is None and total > DEFAULT_BULK_CONFIRM_THRESHOLD:
                state["pending_bulk_action"] = {"type": "download_process", "all_variants": all_variants, "total": total, "per_camera_limits": per_camera_limits}
                modal_msg = t("bulk_modal_required_notice", total=total, action=t("bulk_action_download_process"))
                out_msg = f"{filter_msg}\n\n{modal_msg}".strip() if filter_msg else modal_msg
                if availability_note:
                    out_msg = f"{availability_note}\n{out_msg}"
                return True, out_msg
            action_msg = run_download_and_process_interleaved(
                all_variants=all_variants,
                progress_emit=progress_emit,
                max_images=requested_max_images,
                random_sample=wants_random,
                per_camera_limits=per_camera_limits,
            )
            if availability_note:
                action_msg = f"{availability_note}\n{action_msg}"
            if wants_organize:
                _, org_msg = organize_photos_simple_layout()
                action_msg = f"{action_msg}\n\n{org_msg}"
            out_msg = f"{filter_msg}\n\n{action_msg}".strip() if filter_msg else action_msg
            return True, _append_parser_debug(out_msg, parser_debug)
        if wants_download_only:
            total = self._count_records_for_action("download", all_variants=all_variants, max_images=requested_max_images, random_sample=wants_random, per_camera_limits=per_camera_limits)
            availability_note = ""
            if requested_max_images is not None and int(requested_max_images) > total:
                availability_note = t("parser_requested_available", requested=int(requested_max_images), available=int(total))
            if total <= 0:
                out_msg = t("no_results_after_filters")
                if availability_note:
                    out_msg = f"{availability_note}\n{out_msg}"
                out_msg = f"{filter_msg}\n\n{out_msg}".strip() if filter_msg else out_msg
                return True, _append_parser_debug(out_msg, parser_debug)
            if requested_max_images is None and total > DEFAULT_BULK_CONFIRM_THRESHOLD:
                state["pending_bulk_action"] = {"type": "download", "all_variants": all_variants, "total": total, "per_camera_limits": per_camera_limits}
                modal_msg = t("bulk_modal_required_notice", total=total, action=t("bulk_action_download"))
                out_msg = f"{filter_msg}\n\n{modal_msg}".strip() if filter_msg else modal_msg
                if availability_note:
                    out_msg = f"{availability_note}\n{out_msg}"
                return True, out_msg
            action_msg = run_download(
                all_variants=all_variants,
                progress_emit=progress_emit,
                max_images=requested_max_images,
                random_sample=wants_random,
                per_camera_limits=per_camera_limits,
            )
            if availability_note:
                action_msg = f"{availability_note}\n{action_msg}"
            if wants_organize:
                _, org_msg = organize_photos_simple_layout()
                action_msg = f"{action_msg}\n\n{org_msg}"
            out_msg = f"{filter_msg}\n\n{action_msg}".strip() if filter_msg else action_msg
            return True, _append_parser_debug(out_msg, parser_debug)
        if wants_process_only:
            action_msg = run_process(
                all_variants=all_variants,
                progress_emit=progress_emit,
                max_images=requested_max_images,
                random_sample=wants_random,
                per_camera_limits=per_camera_limits,
            )
            if wants_organize:
                _, org_msg = organize_photos_simple_layout()
                action_msg = f"{action_msg}\n\n{org_msg}"
            out_msg = f"{filter_msg}\n\n{action_msg}".strip() if filter_msg else action_msg
            return True, _append_parser_debug(out_msg, parser_debug)
        if _intent_match("catalog_update_help", cmd):
            return True, t("catalog_update_help")
        if _intent_match("catalog_update", cmd):
            return True, run_catalog_update_from_text(command)
        if _intent_match("tag_selection", cmd):
            requested_path = normalize_text(state.get("download_path", ""))
            ok_path, path = _ensure_writable_download_path(requested_path)
            if not ok_path:
                return True, t("output_path_required")
            if path != requested_path:
                set_download_path(path, persist=True)
            dfsel = get_selection_df(state, False)
            recs = records_from_dataframe(dfsel, require_lbl=False)
            if not recs:
                return True, t("selection_empty_short")
            out = Path(path).expanduser()
            out.mkdir(parents=True, exist_ok=True)
            queue = out / f"download_queue_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
            with queue.open("w", encoding="utf-8") as f:
                for r in recs:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            return True, t("tagged_records", count=len(recs), queue=queue)
        return False, ""
