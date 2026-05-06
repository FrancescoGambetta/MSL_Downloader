from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

import pandas as pd
import requests


@dataclass
class MinSizePreparationResult:
    df: pd.DataFrame
    stats: dict[str, int]
    threshold: int


class ActionDataPreparer:
    def __init__(
        self,
        *,
        normalize_text: Callable[[str], str],
        norm_ascii: Callable[[str], str],
        configured_min_img_size_bytes: Callable[[], int],
        get_selection_df: Callable[..., pd.DataFrame],
        route_selection_by_catalog_boundary: Callable[[pd.DataFrame], pd.DataFrame],
    ) -> None:
        self._normalize_text = normalize_text
        self._norm_ascii = norm_ascii
        self._configured_min_img_size_bytes = configured_min_img_size_bytes
        self._get_selection_df = get_selection_df
        self._route_selection_by_catalog_boundary = route_selection_by_catalog_boundary

    def remote_size_cache(self, state: Optional[dict[str, Any]] = None) -> dict[str, int]:
        """
        Returns the remote image-size cache.

        If `state` is provided (e.g. `st.session_state`), the cache is stored there.
        Otherwise, an instance-local cache is used (useful for unit tests).
        """
        if state is not None:
            cache = state.get("_remote_img_size_cache")
            if isinstance(cache, dict):
                return cache
            cache = {}
            state["_remote_img_size_cache"] = cache
            return cache

        cache = getattr(self, "_remote_img_size_cache_local", None)
        if isinstance(cache, dict):
            return cache
        cache = {}
        setattr(self, "_remote_img_size_cache_local", cache)
        return cache

    def probe_remote_img_size_bytes(
        self,
        state: Optional[dict[str, Any]],
        img_url: str,
        timeout_sec: int = 20,
        *,
        session: Optional[requests.Session] = None,
    ) -> Optional[int]:
        url = self._normalize_text(img_url)
        if not url:
            return None
        cache = self.remote_size_cache(state)
        if url in cache:
            cached = int(cache.get(url, -1))
            return cached if cached >= 0 else None

        def content_len(resp: requests.Response) -> Optional[int]:
            raw = self._normalize_text(resp.headers.get("Content-Length"))
            if not raw:
                return None
            try:
                val = int(raw)
                return val if val >= 0 else None
            except Exception:
                return None

        size: Optional[int] = None
        head_resp: Optional[requests.Response] = None
        own_session = session is None
        session = session or requests.Session()
        try:
            try:
                head_resp = session.head(url, allow_redirects=True, timeout=timeout_sec)
                if int(getattr(head_resp, "status_code", 0)) < 400:
                    size = content_len(head_resp)
            except Exception:
                size = None
            finally:
                try:
                    if head_resp is not None:
                        head_resp.close()
                except Exception:
                    pass

            if size is None:
                get_resp: Optional[requests.Response] = None
                try:
                    get_resp = session.get(url, allow_redirects=True, timeout=timeout_sec, stream=True)
                    if int(getattr(get_resp, "status_code", 0)) < 400:
                        size = content_len(get_resp)
                except Exception:
                    size = None
                finally:
                    try:
                        if get_resp is not None:
                            get_resp.close()
                    except Exception:
                        pass
        finally:
            if own_session:
                try:
                    session.close()
                except Exception:
                    pass

        cache[url] = int(size) if size is not None else -1
        return size

    def prefilter_df_by_min_size(
        self,
        state: Optional[dict[str, Any]],
        df: pd.DataFrame,
        *,
        min_size_bytes: int,
        desired_count: Optional[int] = None,
        max_remote_checks: int = 60,
    ) -> tuple[pd.DataFrame, dict[str, int]]:
        stats = {
            "checked": 0,
            "kept": 0,
            "dropped_known_small": 0,
            "dropped_unknown_or_small": 0,
            "unchecked_kept": 0,
            "budget_exhausted": 0,
        }
        if min_size_bytes <= 0 or len(df) == 0 or "img_url" not in df.columns:
            return df, stats

        out = df.copy()
        if "img_size_bytes" in out.columns:
            sizes = pd.to_numeric(out["img_size_bytes"], errors="coerce")
        else:
            sizes = pd.Series([float("nan")] * len(out), index=out.index, dtype="float64")

        known = sizes.notna()
        keep_known = known & (sizes >= float(min_size_bytes))
        drop_known = known & (sizes < float(min_size_bytes))
        unknown = ~known
        stats["dropped_known_small"] = int(drop_known.sum())

        keep_mask = keep_known.copy()
        kept_so_far = int(keep_known.sum())
        target = int(desired_count) if isinstance(desired_count, int) and desired_count > 0 else None

        if bool(unknown.any()):
            unknown_idx = out.index[unknown]
            checks_budget = max(0, int(max_remote_checks))
            with requests.Session() as session:
                for idx in unknown_idx:
                    if target is not None and kept_so_far >= target:
                        break
                    if checks_budget <= 0:
                        stats["budget_exhausted"] = 1
                        break
                    img_url = self._normalize_text(out.at[idx, "img_url"])
                    size = self.probe_remote_img_size_bytes(state, img_url, session=session)
                    stats["checked"] += 1
                    checks_budget -= 1
                    if size is not None and int(size) >= int(min_size_bytes):
                        keep_mask.at[idx] = True
                        kept_so_far += 1
                        stats["kept"] += 1
                    else:
                        keep_mask.at[idx] = False
                        stats["dropped_unknown_or_small"] += 1

        filtered = out[keep_mask].copy().reset_index(drop=True)
        return filtered, stats

    def prepare_action_df(
        self,
        *,
        all_variants: bool = False,
        max_images: Optional[int] = None,
        random_sample: bool = False,
        per_camera_limits: Optional[dict[str, int]] = None,
        require_lbl: bool = False,
        selection_df: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        df = selection_df.copy() if isinstance(selection_df, pd.DataFrame) else self._get_selection_df(all_variants=all_variants)
        df = self._route_selection_by_catalog_boundary(df)
        if require_lbl and "lbl_url" in df.columns:
            df = df[df["lbl_url"].astype(str).str.len() > 0].copy()
        limits = per_camera_limits or {}
        if limits and "camera" in df.columns:
            out_parts: list[pd.DataFrame] = []
            matched_any_camera = False
            for cam_name, lim in limits.items():
                try:
                    lim_i = int(lim)
                except Exception:
                    continue
                if lim_i <= 0:
                    continue
                cam_mask = df["camera"].astype(str).apply(lambda x: self._norm_ascii(x) == self._norm_ascii(str(cam_name)))
                cam_df = df[cam_mask]
                if len(cam_df) == 0:
                    continue
                matched_any_camera = True
                take_n = min(lim_i, len(cam_df))
                picked = cam_df.sample(n=take_n).copy() if random_sample else cam_df.head(take_n).copy()
                out_parts.append(picked)
            if not matched_any_camera:
                return df.iloc[0:0].copy().reset_index(drop=True)
            if out_parts:
                selected = pd.concat(out_parts, axis=0).drop_duplicates()
                if max_images is not None and max_images > 0 and len(selected) > int(max_images):
                    selected = selected.sample(n=int(max_images)).copy() if random_sample else selected.head(int(max_images)).copy()
                return selected.reset_index(drop=True)
        if max_images is None or max_images <= 0 or len(df) <= max_images:
            return df
        return df.sample(n=int(max_images)).reset_index(drop=True) if random_sample else df.head(int(max_images)).reset_index(drop=True)

    def prepare_action_df_with_min_size(
        self,
        *,
        all_variants: bool = False,
        max_images: Optional[int] = None,
        random_sample: bool = False,
        per_camera_limits: Optional[dict[str, int]] = None,
        require_lbl: bool = False,
        selection_df: Optional[pd.DataFrame] = None,
    ) -> MinSizePreparationResult:
        min_size_threshold = self._configured_min_img_size_bytes()
        explicit_selection = isinstance(selection_df, pd.DataFrame) and len(selection_df) > 0
        empty_stats = {"checked": 0, "kept": 0, "dropped_known_small": 0, "dropped_unknown_or_small": 0}
        if min_size_threshold <= 0:
            return MinSizePreparationResult(
                df=self.prepare_action_df(
                    all_variants=all_variants,
                    max_images=max_images,
                    random_sample=random_sample,
                    per_camera_limits=per_camera_limits,
                    require_lbl=require_lbl,
                    selection_df=selection_df,
                ),
                stats=empty_stats,
                threshold=0,
            )
        if explicit_selection:
            return MinSizePreparationResult(
                df=self.prepare_action_df(
                    all_variants=all_variants,
                    max_images=max_images,
                    random_sample=random_sample,
                    per_camera_limits=per_camera_limits,
                    require_lbl=require_lbl,
                    selection_df=selection_df,
                ),
                stats=empty_stats,
                threshold=min_size_threshold,
            )

        desired_count: Optional[int] = None
        if isinstance(max_images, int) and max_images > 0:
            desired_count = int(max_images)
        if per_camera_limits:
            quota_sum = 0
            for _, lim in per_camera_limits.items():
                try:
                    li = int(lim)
                except Exception:
                    continue
                if li > 0:
                    quota_sum += li
            if quota_sum > 0:
                desired_count = quota_sum if desired_count is None else min(desired_count, quota_sum)

        pool = self.prepare_action_df(
            all_variants=all_variants,
            max_images=None,
            random_sample=random_sample,
            per_camera_limits=per_camera_limits,
            require_lbl=require_lbl,
            selection_df=selection_df,
        )
        max_checks = 60
        if desired_count is not None and int(desired_count) > 0:
            # With a strict min-size filter we prefer returning fewer items
            # over silently padding the result set with unchecked rows.
            # Increase the remote-size probe budget so RAW archive selections
            # can still find enough valid full-size images deeper in the pool.
            max_checks = min(len(pool), max(120, int(desired_count) * 25))
        sized_pool, stats = self.prefilter_df_by_min_size(
            None,
            pool,
            min_size_bytes=min_size_threshold,
            desired_count=desired_count,
            max_remote_checks=max_checks,
        )
        final_df = self.prepare_action_df(
            all_variants=all_variants,
            max_images=max_images,
            random_sample=random_sample,
            per_camera_limits=per_camera_limits,
            require_lbl=require_lbl,
            selection_df=sized_pool,
        )
        return MinSizePreparationResult(df=final_df, stats=stats, threshold=min_size_threshold)
