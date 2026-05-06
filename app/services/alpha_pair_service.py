from __future__ import annotations

from typing import Any, Callable, Optional

import pandas as pd


class AlphaPairService:
    def __init__(
        self,
        *,
        normalize_text: Callable[[Any], str],
        norm_ascii: Callable[[str], str],
        normalize_source: Callable[[Any], str],
        record_product_id: Callable[[dict[str, Any]], str],
    ) -> None:
        self._normalize_text = normalize_text
        self._norm_ascii = norm_ascii
        self._normalize_source = normalize_source
        self._record_product_id = record_product_id

    def attach_optional_alpha_pairs(
        self,
        records: list[dict[str, Any]],
        *,
        state: dict[str, Any],
        reference_df: Optional[pd.DataFrame] = None,
    ) -> tuple[list[dict[str, Any]], int]:
        if not records:
            return records, 0

        wants_any = False
        needed_mask_pids: set[str] = set()
        for r in records:
            try:
                if self._normalize_source(r.get("source")) != "pds":
                    continue
                cam = self._norm_ascii(self._normalize_text(r.get("camera"))).lower()
                if cam not in {"navcam", "hazcam"}:
                    continue
                pid = self._record_product_id(r).upper()
                if not pid or "MXYLF" in pid:
                    continue
                token = ""
                if "ILTLF" in pid:
                    token = "ILTLF"
                elif "ILT_F" in pid:
                    token = "ILT_F"
                elif "RADLF" in pid:
                    token = "RADLF"
                if not token:
                    continue
                needed_mask_pids.add(pid.replace(token, "MXYLF"))
                wants_any = True
            except Exception:
                continue
        if not wants_any:
            return records, 0

        ref = reference_df if isinstance(reference_df, pd.DataFrame) else state.get("df")
        if not isinstance(ref, pd.DataFrame) or len(ref) == 0:
            return records, 0
        required = {"product_id", "img_url"}
        if not required.issubset(set(ref.columns)):
            return records, 0

        cache_key = "_alpha_pair_map_mxylf_pds_navhaz"
        pair_map: dict[str, dict[str, Any]] = {}
        cached = state.get(cache_key)
        try:
            if isinstance(cached, dict) and cached.get("_df_id") == id(ref) and cached.get("_rows") == int(len(ref)):
                pm = cached.get("map")
                if isinstance(pm, dict):
                    pair_map = pm
        except Exception:
            pair_map = {}
        if not pair_map:
            tmp = ref
            if "source" in tmp.columns:
                src_s = tmp["source"].astype(str).str.strip().str.lower()
                tmp = tmp[src_s.eq("pds")]
            if "camera" in tmp.columns:
                cam_s = tmp["camera"].astype(str).str.strip().str.lower()
                tmp = tmp[cam_s.isin(["navcam", "hazcam"])]
            pid_s = tmp["product_id"].astype(str)
            tmp = tmp[pid_s.str.contains("MXYLF", case=False, na=False)]
            try:
                pid_u = tmp["product_id"].astype(str).str.upper()
                tmp = tmp[pid_u.isin(list(needed_mask_pids))]
            except Exception:
                pass
            tmp = tmp[tmp["img_url"].astype(str).str.len() > 0]
            has_lbl_col = "lbl_url" in tmp.columns
            pm: dict[str, dict[str, Any]] = {}
            for pid, img_url, lbl_url, cam in zip(
                tmp["product_id"].astype(str),
                tmp["img_url"].astype(str),
                (tmp["lbl_url"].astype(str) if has_lbl_col else [""] * len(tmp)),
                (tmp["camera"].astype(str) if "camera" in tmp.columns else [""] * len(tmp)),
            ):
                pid_u = self._normalize_text(pid).upper()
                img_u = self._normalize_text(img_url)
                if not pid_u or not img_u:
                    continue
                if pid_u not in pm:
                    pm[pid_u] = {"img_url": img_u, "lbl_url": self._normalize_text(lbl_url), "camera": self._normalize_text(cam)}
            pair_map = pm
            try:
                state[cache_key] = {"_df_id": id(ref), "_rows": int(len(ref)), "map": pair_map}
            except Exception:
                pass

        out: list[dict[str, Any]] = []
        paired = 0
        for rec in records:
            rec_out = dict(rec)
            src = self._normalize_source(rec_out.get("source"))
            cam = self._norm_ascii(self._normalize_text(rec_out.get("camera"))).lower()
            if src != "pds" or cam not in {"navcam", "hazcam"}:
                out.append(rec_out)
                continue
            pid = self._record_product_id(rec_out).upper()
            token = ""
            if "ILTLF" in pid:
                token = "ILTLF"
            elif "ILT_F" in pid:
                token = "ILT_F"
            elif "RADLF" in pid:
                token = "RADLF"
            if not token:
                out.append(rec_out)
                continue
            mask_pid = pid.replace(token, "MXYLF")
            mask_rec = pair_map.get(mask_pid)
            if not mask_rec:
                out.append(rec_out)
                continue
            mask_img_url = self._normalize_text(mask_rec.get("img_url"))
            if not mask_img_url:
                out.append(rec_out)
                continue
            rec_out["pair_product_id"] = mask_pid
            rec_out["pair_img_url"] = mask_img_url
            rec_out["pair_lbl_url"] = self._normalize_text(mask_rec.get("lbl_url"))
            rec_out["pair_kind"] = "mxylf_alpha"
            paired += 1
            out.append(rec_out)
        return out, paired
