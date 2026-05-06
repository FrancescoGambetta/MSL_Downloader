from __future__ import annotations

import re
from typing import Any, Callable, Optional

import pandas as pd


class CatalogFilterService:
    def __init__(
        self,
        *,
        normalize_text: Callable[[Any], str],
        norm_ascii: Callable[[str], str],
        load_compiled_camera_rules: Callable[[], dict[str, Any]],
        load_camera_rules: Callable[[], dict[str, Any]],
        reduce_raw_burst_sequences: Callable[[pd.DataFrame, int], pd.DataFrame],
    ) -> None:
        self._normalize_text = normalize_text
        self._norm_ascii = norm_ascii
        self._load_compiled_camera_rules = load_compiled_camera_rules
        self._load_camera_rules = load_camera_rules
        self._reduce_raw_burst_sequences = reduce_raw_burst_sequences

    def filter_dataframe(
        self,
        df: pd.DataFrame,
        filters: dict[str, Any],
        *,
        progress: Optional[Callable[[float, str], None]] = None,
    ) -> pd.DataFrame:
        # Avoid eager full DataFrame copies: every filter step below creates a new
        # frame anyway, so copying the entire catalog up-front is wasted work.
        out = df
        if len(out) == 0:
            return out.copy()

        f = filters or {}
        if progress is not None:
            try:
                progress(0.02, "SOL range")
            except Exception:
                pass
        if "sol" in out.columns:
            if f.get("sol_start") is not None:
                out = out[out["sol"].fillna(-1).astype(float) >= float(f["sol_start"])]
            if f.get("sol_end") is not None:
                out = out[out["sol"].fillna(-1).astype(float) <= float(f["sol_end"])]
        if progress is not None:
            try:
                progress(0.10, "Camere")
            except Exception:
                pass
        cams = f.get("cameras") or []
        if cams and "camera" in out.columns:
            # Vectorized normalize for speed (camera names are ASCII in our datasets).
            lowered = {
                re.sub(r"[^a-z0-9]+", "", self._norm_ascii(str(c)).lower())
                for c in cams
                if self._norm_ascii(str(c))
            }
            cam_compact = (
                out["camera"]
                .fillna("")
                .astype(str)
                .str.lower()
                .str.replace(r"[^a-z0-9]+", "", regex=True)
            )
            out = out[cam_compact.isin(lowered)]
        if progress is not None:
            try:
                progress(0.16, "Sorgente")
            except Exception:
                pass
        if "source" in out.columns:
            allow_pds = bool(f.get("source_pds", True))
            allow_raw = bool(f.get("source_raw", True))
            src = out["source"].fillna("").astype(str).str.lower()
            if allow_pds and not allow_raw:
                out = out[src.eq("pds")]
            elif allow_raw and not allow_pds:
                out = out[src.eq("raw")]
            elif not allow_pds and not allow_raw:
                return out.iloc[0:0].copy()
        if progress is not None:
            try:
                progress(0.22, "Min size / LBL")
            except Exception:
                pass
        if f.get("min_img_size") is not None and "img_size_bytes" in out.columns:
            threshold = float(f["min_img_size"])
            size_series = pd.to_numeric(out["img_size_bytes"], errors="coerce")
            keep_known = size_series >= threshold
            if "source" in out.columns:
                # RAW catalog often does not provide size metadata; keep those rows
                # and apply effective min-size during action/download.
                is_raw = out["source"].fillna("").astype(str).str.lower().eq("raw")
                unknown_size = size_series.isna()
                keep_unknown_raw = is_raw & unknown_size
                out = out[keep_known | keep_unknown_raw]
            else:
                out = out[keep_known]
        if f.get("only_with_lbl") and "lbl_url" in out.columns:
            out = out[out["lbl_url"].astype(str).str.len() > 0]
        if progress is not None:
            try:
                progress(0.30, "Varianti / token")
            except Exception:
                pass
        dr = [str(v).upper() for v in (f.get("dr_variants") or []) if str(v).strip()]
        if dr and "_suffix_code" in out.columns:
            out = out[out["_suffix_code"].astype(str).isin(dr)]
        tokens = [str(v).upper() for v in (f.get("name_tokens") or []) if str(v).strip()]
        if tokens and "_file_name" in out.columns:
            nup = out["_file_name"].astype(str).str.upper()
            mask = pd.Series(False, index=out.index)
            for tok in tokens:
                mask = mask | nup.str.contains(tok, regex=False)
            out = out[mask]
        prefixes = [str(v).upper() for v in (f.get("file_prefixes") or []) if str(v).strip()]
        if prefixes and "_file_name" in out.columns:
            nup = out["_file_name"].astype(str).str.upper()
            mask = pd.Series(False, index=out.index)
            for pref in prefixes:
                mask = mask | nup.str.startswith(pref)
            out = out[mask]
        must_contain = [str(v).upper() for v in (f.get("file_name_contains") or []) if str(v).strip()]
        if must_contain and "_file_name" in out.columns:
            nup = out["_file_name"].astype(str).str.upper()
            mask = pd.Series(True, index=out.index)
            for tok in must_contain:
                mask = mask & nup.str.contains(tok, regex=False)
            out = out[mask]

        if progress is not None:
            try:
                progress(0.36, "Regole camera")
            except Exception:
                pass
        compiled_rules = self._load_compiled_camera_rules()
        rules_cfg = self._load_camera_rules()
        source_raw_mask = (
            out["source"].fillna("").astype(str).str.lower().eq("raw")
            if "source" in out.columns
            else pd.Series(False, index=out.index)
        )
        source_pds_mask = (
            out["source"].fillna("").astype(str).str.lower().eq("pds")
            if "source" in out.columns
            else pd.Series(True, index=out.index)
        )
        cam_norm = out["camera"].astype(str).apply(self._norm_ascii) if "camera" in out.columns else pd.Series([""] * len(out), index=out.index)
        cam_compact = cam_norm.str.replace(r"[^a-z0-9]+", "", regex=True) if "camera" in out.columns else pd.Series([""] * len(out), index=out.index)
        suffix = out["_suffix_code"].astype(str).str.upper() if "_suffix_code" in out.columns else pd.Series([""] * len(out), index=out.index)
        nup = out["_file_name"].astype(str).str.upper() if "_file_name" in out.columns else pd.Series([""] * len(out), index=out.index)

        selected_cam_keys = {self._norm_ascii(str(c)) for c in cams if self._normalize_text(c)}
        candidate_rules = []
        for item in compiled_rules.get("items", []):
            if not isinstance(item, dict):
                continue
            cam_key = self._normalize_text(item.get("camera_key"))
            if selected_cam_keys and cam_key and cam_key not in selected_cam_keys:
                continue
            sources = item.get("sources", {})
            if not isinstance(sources, dict):
                continue
            any_source_enabled = False
            for source_data in sources.values():
                if not isinstance(source_data, dict):
                    continue
                filter_key = self._normalize_text(source_data.get("filter_key"))
                if not filter_key or bool(f.get(filter_key)):
                    any_source_enabled = True
                    break
            if any_source_enabled:
                candidate_rules.append(item)

        rules_total = max(1, len(candidate_rules))
        target_mask_cache: dict[str, pd.Series] = {}
        for idx_rule, item in enumerate(candidate_rules):
            cam_name = self._normalize_text(item.get("camera_name")) or "camera"
            if progress is not None:
                try:
                    # Rules take most of the time; map them to the 0.36..0.92 segment.
                    base = 0.36 + (0.56 * (idx_rule / float(rules_total)))
                    progress(min(0.92, max(0.36, base)), f"Regole: {str(cam_name)}")
                except Exception:
                    pass
            cam_key = self._normalize_text(item.get("camera_key"))
            is_target = target_mask_cache.get(cam_key)
            if is_target is None:
                if "camera" in out.columns:
                    target_mask = pd.Series(False, index=out.index)
                    for pat in item.get("alias_boundaries", []) or []:
                        target_mask = target_mask | cam_norm.str.contains(pat, regex=True)
                    for alias_compact in item.get("alias_compacts", []) or []:
                        target_mask = target_mask | cam_compact.str.contains(re.escape(alias_compact), regex=True)
                    if "_file_name" in out.columns:
                        for mk in item.get("markers", []) or []:
                            target_mask = target_mask | nup.str.contains(mk, regex=False)
                    is_target = target_mask
                else:
                    markers = item.get("markers", []) or []
                    if markers and "_file_name" in out.columns:
                        target_mask = pd.Series(False, index=out.index)
                        for mk in markers:
                            target_mask = target_mask | nup.str.contains(mk, regex=False)
                        is_target = target_mask
                    else:
                        continue
                target_mask_cache[cam_key] = is_target

            sources = item.get("sources", {})
            for source_name in ("pds", "raw"):
                source_data = sources.get(source_name) if isinstance(sources, dict) else None
                if not isinstance(source_data, dict):
                    continue
                filter_key = self._normalize_text(source_data.get("filter_key"))
                if filter_key and not bool(f.get(filter_key)):
                    continue

                source_mask = source_pds_mask if source_name == "pds" else source_raw_mask
                scoped_target = is_target & source_mask
                if not bool(scoped_target.any()):
                    continue

                ok_mask = pd.Series(True, index=out.index)

                suffix_any = source_data.get("suffix_any") or []
                if suffix_any:
                    if "_suffix_code" not in out.columns:
                        continue
                    ok_mask = ok_mask & suffix.isin(suffix_any)

                prefix_any = source_data.get("prefix_any") or []
                if prefix_any:
                    if "_file_name" not in out.columns:
                        continue
                    ok_mask = ok_mask & nup.str.startswith(tuple(prefix_any))

                contains_all = source_data.get("contains_all") or []
                if contains_all:
                    if "_file_name" not in out.columns:
                        continue
                    for tok in contains_all:
                        ok_mask = ok_mask & nup.str.contains(tok, regex=False)

                contains_any = source_data.get("contains_any") or []
                if (
                    source_name == "raw"
                    and cam_key == "mastcam"
                    and bool(f.get("mastcam_raw_include_c00"))
                ):
                    contains_any = list(contains_any) + ["C00"]
                if contains_any:
                    if "_file_name" not in out.columns:
                        continue
                    any_mask = pd.Series(False, index=out.index)
                    for tok in contains_any:
                        any_mask = any_mask | nup.str.contains(tok, regex=False)
                    ok_mask = ok_mask & any_mask

                min_img_size_bytes = source_data.get("min_img_size_bytes")
                if min_img_size_bytes is not None:
                    if "img_size_bytes" not in out.columns:
                        continue
                    try:
                        threshold = float(min_img_size_bytes)
                    except Exception:
                        threshold = -1.0
                    if threshold >= 0:
                        size_series = pd.to_numeric(out["img_size_bytes"], errors="coerce").fillna(-1.0)
                        size_ok = size_series >= threshold
                        exempt_markers = source_data.get("exempt_markers") or []
                        if exempt_markers and "_file_name" in out.columns:
                            exempt_mask = pd.Series(False, index=out.index)
                            for mk in exempt_markers:
                                exempt_mask = exempt_mask | nup.str.contains(mk, regex=False)
                            size_ok = size_ok | exempt_mask
                        ok_mask = ok_mask & size_ok

                out = out[(~scoped_target) | ok_mask]

        # RAW global rules from config.
        if len(out) > 0 and "_file_name" in out.columns:
            raw_rules = rules_cfg.get("raw_global_rules", {}) if isinstance(rules_cfg, dict) else {}
            if isinstance(raw_rules, dict):
                source_raw_mask = (
                    out["source"].fillna("").astype(str).str.lower().eq("raw")
                    if "source" in out.columns
                    else pd.Series(False, index=out.index)
                )
                if bool(source_raw_mask.any()):
                    nup = out["_file_name"].astype(str).str.upper()
                    drop_tokens = [str(x).upper() for x in (raw_rules.get("drop_filename_contains_any") or []) if self._normalize_text(x)]
                    if drop_tokens:
                        keep_mask = pd.Series(True, index=out.index)
                        for tok in drop_tokens:
                            keep_mask = keep_mask & (~nup.str.contains(tok, regex=False))
                        out = out[(~source_raw_mask) | keep_mask]

            reduce_cfg = raw_rules.get("reduce_bursts", {}) if isinstance(raw_rules, dict) else {}
            if isinstance(reduce_cfg, dict):
                apply_key = self._normalize_text(reduce_cfg.get("apply_when_filter_key")) or "raw_reduce_bursts"
                keep_key = self._normalize_text(reduce_cfg.get("keep_per_group_filter_key")) or "raw_burst_keep_per_group"
                default_keep = int(reduce_cfg.get("default_keep_per_group", 1) or 1)
            else:
                apply_key = "raw_reduce_bursts"
                keep_key = "raw_burst_keep_per_group"
                default_keep = 1

            if bool(f.get(apply_key)):
                keep_per_group = int(f.get(keep_key, default_keep) or default_keep)
                out = self._reduce_raw_burst_sequences(out, keep_per_group=max(1, keep_per_group))

        if progress is not None:
            try:
                progress(0.92, "Finalizzazione")
            except Exception:
                pass
        return out.reset_index(drop=True)

