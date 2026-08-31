"""Builds the exact set of records a download/process action will run on: selection -> per-camera limits -> optional min-size filtering.

The min-size path (`prepare_action_df_with_min_size`) is the interesting
one: since the catalog often doesn't know a RAW image's real size upfront,
it has to probe remote URLs (HEAD, falling back to a streamed GET) to find
out, under a checks budget. When per-camera quotas are active, each camera
gets its own probe budget/target (`per_camera_targets`) so that one camera
being checked first can never exhaust the whole batch's budget and starve
the others -- see `prefilter_df_by_min_size`'s per-camera branch.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

import pandas as pd
import requests


class ActionDataframeService:
    """Resolves the selection DataFrame for an action, applies per-camera/global caps, and (optionally) filters by real remote image size."""

    def __init__(
        self,
        *,
        normalize_text: Callable[[Any], str],
    ) -> None:
        self._normalize_text = normalize_text

    def configured_min_img_size_bytes(self, state: dict[str, Any]) -> int:
        """Return the current min-image-size filter threshold in bytes (0 if unset)."""
        try:
            filters = state.get("filters", {}) or {}
            val = filters.get("min_img_size")
            if val is None:
                return 0
            return max(0, int(float(val)))
        except Exception:
            return 0

    def remote_size_cache(self, state: dict[str, Any]) -> dict[str, int]:
        """Return (creating if needed) the session-scoped `img_url -> size_bytes` probe cache, so a URL is never probed twice."""
        cache = state.get("_remote_img_size_cache")
        if isinstance(cache, dict):
            return cache
        cache = {}
        state["_remote_img_size_cache"] = cache
        return cache

    def probe_remote_img_size_bytes(
        self,
        state: dict[str, Any],
        img_url: str,
        *,
        timeout_sec: int = 20,
        session: Optional[requests.Session] = None,
    ) -> Optional[int]:
        """Fetch `img_url`'s size via HTTP HEAD's Content-Length (falling back to a streamed GET if HEAD doesn't provide one), cached per session. Pass a shared `session` to reuse one connection across a probe batch."""
        url = self._normalize_text(img_url)
        if not url:
            return None
        cache = self.remote_size_cache(state)
        if url in cache:
            cached = int(cache.get(url, -1))
            return cached if cached >= 0 else None

        def _content_len(resp: requests.Response) -> Optional[int]:
            raw = self._normalize_text(resp.headers.get("Content-Length"))
            if not raw:
                return None
            try:
                val = int(raw)
                return val if val >= 0 else None
            except Exception:
                return None

        # Reuse the caller's session (one TCP/TLS connection reused across
        # every probe in a batch) when given one, instead of opening a fresh
        # connection per image via the bare `requests.head`/`requests.get`.
        client = session if session is not None else requests

        size: Optional[int] = None
        head_resp: Optional[requests.Response] = None
        try:
            head_resp = client.head(url, allow_redirects=True, timeout=timeout_sec)
            if int(getattr(head_resp, "status_code", 0)) < 400:
                size = _content_len(head_resp)
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
                get_resp = client.get(url, allow_redirects=True, timeout=timeout_sec, stream=True)
                if int(getattr(get_resp, "status_code", 0)) < 400:
                    size = _content_len(get_resp)
            except Exception:
                size = None
            finally:
                try:
                    if get_resp is not None:
                        get_resp.close()
                except Exception:
                    pass

        cache[url] = int(size) if size is not None else -1
        return size

    def _prefilter_probe_loop(
        self,
        state: dict[str, Any],
        out: pd.DataFrame,
        keep_mask: pd.Series,
        candidate_idx: pd.Index,
        *,
        min_size_bytes: int,
        target: Optional[int],
        kept_so_far: int,
        checks_budget: int,
        stats: dict[str, int],
        session: Optional[requests.Session] = None,
    ) -> tuple[int, bool]:
        """
        Probe remote sizes for `candidate_idx` rows, updating `keep_mask`/`stats`
        in place, until `target` is reached or `checks_budget` runs out.
        Returns (kept_so_far, budget_exhausted_before_target).
        """
        exhausted = False
        for idx in candidate_idx:
            if target is not None and kept_so_far >= target:
                break
            if checks_budget <= 0:
                exhausted = True
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
        if exhausted and target is not None and kept_so_far < target:
            for idx in candidate_idx:
                if kept_so_far >= target:
                    break
                try:
                    if bool(keep_mask.at[idx]):
                        continue
                except Exception:
                    pass
                keep_mask.at[idx] = True
                kept_so_far += 1
                stats["unchecked_kept"] += 1
        return kept_so_far, exhausted

    def prefilter_df_by_min_size(
        self,
        state: dict[str, Any],
        df: pd.DataFrame,
        *,
        min_size_bytes: int,
        desired_count: Optional[int] = None,
        max_remote_checks: int = 60,
        per_camera_targets: Optional[dict[str, int]] = None,
    ) -> tuple[pd.DataFrame, dict[str, int]]:
        """Filter `df` to rows meeting `min_size_bytes`: keeps known-large rows outright, drops known-small ones, and probes remote size for the rest up to a checks budget (padding with unchecked rows if the budget runs out before `desired_count`/`per_camera_targets` is reached).

        Pass `per_camera_targets` to give each camera its own probe budget
        and target so no single camera's rows can consume the whole batch's
        budget and leave another camera with zero results.
        """
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
        if not bool(unknown.any()):
            filtered = out[keep_mask].copy().reset_index(drop=True)
            return filtered, stats

        # One shared HTTP session for every remote size probe in this batch
        # (potentially dozens of HEAD/GET calls), instead of a fresh
        # connection per image -- meaningfully faster against the same host.
        with requests.Session() as session:
            has_per_camera_targets = bool(per_camera_targets) and "camera" in out.columns
            if has_per_camera_targets:
                # Give each camera its own remote-size-check budget and target,
                # so that checking one camera's rows first can never consume
                # another camera's share and leave it with zero results (a
                # global shared target let whichever camera happened to be
                # checked first "use up" the whole budget/target before the
                # others were ever probed).
                cam_series = out["camera"].astype(str).str.strip().str.lower()
                for cam_name, cam_target in per_camera_targets.items():
                    try:
                        cam_target_i = int(cam_target)
                    except Exception:
                        continue
                    if cam_target_i <= 0:
                        continue
                    cam_mask = cam_series == str(cam_name).strip().lower()
                    cam_unknown_idx = out.index[cam_mask & unknown]
                    if len(cam_unknown_idx) == 0:
                        continue
                    cam_kept_so_far = int(keep_mask.loc[cam_mask & known].sum())
                    cam_kept_so_far, cam_exhausted = self._prefilter_probe_loop(
                        state,
                        out,
                        keep_mask,
                        cam_unknown_idx,
                        min_size_bytes=min_size_bytes,
                        target=cam_target_i,
                        kept_so_far=cam_kept_so_far,
                        checks_budget=max(20, cam_target_i * 2),
                        stats=stats,
                        session=session,
                    )
                    if cam_exhausted:
                        stats["budget_exhausted"] = 1
                # Rows for a camera without an explicit target shouldn't
                # normally occur here (the caller already restricts candidates
                # to the requested cameras), but handle them conservatively:
                # leave them at their initial keep_known value (known-large
                # only, never probed -- there is no quota to bound how many
                # checks that'd cost).
            else:
                kept_so_far = int(keep_known.sum())
                target = int(desired_count) if isinstance(desired_count, int) and desired_count > 0 else None
                unknown_idx = out.index[unknown]
                _, exhausted = self._prefilter_probe_loop(
                    state,
                    out,
                    keep_mask,
                    unknown_idx,
                    min_size_bytes=min_size_bytes,
                    target=target,
                    kept_so_far=kept_so_far,
                    checks_budget=max(0, int(max_remote_checks)),
                    stats=stats,
                    session=session,
                )
                if exhausted:
                    stats["budget_exhausted"] = 1

        filtered = out[keep_mask].copy().reset_index(drop=True)
        return filtered, stats

    def prepare_action_df(
        self,
        *,
        all_variants: bool,
        max_images: Optional[int],
        random_sample: bool,
        per_camera_limits: Optional[dict[str, int]],
        require_lbl: bool,
        selection_df: Optional[pd.DataFrame],
        get_selection_df: Callable[..., pd.DataFrame],
        route_selection_by_catalog_boundary: Callable[[pd.DataFrame], pd.DataFrame],
        norm_ascii: Callable[[str], str],
    ) -> pd.DataFrame:
        """Resolve the selection DataFrame and apply per-camera limits and/or a global `max_images` cap.

        With `per_camera_limits`, each listed camera contributes up to its
        own limit (head or random sample), concatenated and then capped
        again by `max_images` if given. Without per-camera limits, just caps
        the whole selection by `max_images`.
        """
        df = selection_df.copy() if isinstance(selection_df, pd.DataFrame) else get_selection_df(all_variants=all_variants)
        df = route_selection_by_catalog_boundary(df)
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
                cam_mask = df["camera"].astype(str).apply(lambda x: norm_ascii(x) == norm_ascii(str(cam_name)))
                cam_df = df[cam_mask]
                if len(cam_df) == 0:
                    continue
                matched_any_camera = True
                take_n = min(lim_i, len(cam_df))
                if random_sample:
                    picked = cam_df.sample(n=take_n).copy()
                else:
                    picked = cam_df.head(take_n).copy()
                out_parts.append(picked)
            if not matched_any_camera:
                return df.iloc[0:0].copy().reset_index(drop=True)
            if out_parts:
                selected = pd.concat(out_parts, axis=0).drop_duplicates()
                if max_images is not None and max_images > 0 and len(selected) > int(max_images):
                    if random_sample:
                        selected = selected.sample(n=int(max_images)).copy()
                    else:
                        selected = selected.head(int(max_images)).copy()
                return selected.reset_index(drop=True)
        if max_images is None or max_images <= 0 or len(df) <= max_images:
            return df
        if random_sample:
            return df.sample(n=int(max_images)).reset_index(drop=True)
        return df.head(int(max_images)).reset_index(drop=True)

    def prepare_action_df_with_min_size(
        self,
        state: dict[str, Any],
        *,
        all_variants: bool,
        max_images: Optional[int],
        random_sample: bool,
        per_camera_limits: Optional[dict[str, int]],
        require_lbl: bool,
        selection_df: Optional[pd.DataFrame],
        get_selection_df: Callable[..., pd.DataFrame],
        route_selection_by_catalog_boundary: Callable[[pd.DataFrame], pd.DataFrame],
        norm_ascii: Callable[[str], str],
    ) -> tuple[pd.DataFrame, dict[str, int], int]:
        """`prepare_action_df` plus min-image-size filtering. Returns `(df, probe_stats, min_size_threshold_used)`.

        Skips size-probing entirely when there's no size threshold
        configured, or the caller passed an explicit `selection_df` (an
        already-decided set of rows -- e.g. from the bulk-confirm reply --
        shouldn't be second-guessed by a size filter). Otherwise builds an
        oversized candidate pool first (per-camera limits are set to an
        effectively unbounded cap here on purpose, so the size-probe step
        has real room to search past a few undersized candidates -- see the
        comment below), filters that pool by size, then re-applies the real
        `per_camera_limits`/`max_images` as the final truncation step.
        """
        min_size_threshold = self.configured_min_img_size_bytes(state)
        explicit_selection = isinstance(selection_df, pd.DataFrame) and len(selection_df) > 0
        if min_size_threshold <= 0:
            return (
                self.prepare_action_df(
                    all_variants=all_variants,
                    max_images=max_images,
                    random_sample=random_sample,
                    per_camera_limits=per_camera_limits,
                    require_lbl=require_lbl,
                    selection_df=selection_df,
                    get_selection_df=get_selection_df,
                    route_selection_by_catalog_boundary=route_selection_by_catalog_boundary,
                    norm_ascii=norm_ascii,
                ),
                {"checked": 0, "kept": 0, "dropped_known_small": 0, "dropped_unknown_or_small": 0},
                0,
            )

        if explicit_selection:
            return (
                self.prepare_action_df(
                    all_variants=all_variants,
                    max_images=max_images,
                    random_sample=random_sample,
                    per_camera_limits=per_camera_limits,
                    require_lbl=require_lbl,
                    selection_df=selection_df,
                    get_selection_df=get_selection_df,
                    route_selection_by_catalog_boundary=route_selection_by_catalog_boundary,
                    norm_ascii=norm_ascii,
                ),
                {"checked": 0, "kept": 0, "dropped_known_small": 0, "dropped_unknown_or_small": 0},
                min_size_threshold,
            )

        desired_count: Optional[int] = None
        if isinstance(max_images, int) and max_images > 0:
            desired_count = int(max_images)
        per_camera_targets: Optional[dict[str, int]] = None
        if per_camera_limits:
            per_camera_targets = {}
            quota_sum = 0
            for cam_name, lim in per_camera_limits.items():
                try:
                    li = int(lim)
                except Exception:
                    continue
                if li > 0:
                    quota_sum += li
                    per_camera_targets[str(cam_name)] = li
            if quota_sum > 0:
                desired_count = quota_sum if desired_count is None else min(desired_count, quota_sum)

        # When per-camera quotas are active, the pool must give the size-probe
        # step real room to search: capping each camera to exactly its target
        # count *before* checking sizes means a few undersized rows there are
        # enough to permanently under-deliver that camera, even when the
        # catalog has plenty more candidates that would pass the size filter.
        # Pass a very high per-camera cap here (prepare_action_df clamps it to
        # however many rows actually exist for that camera) so the real quota
        # is only applied as the final truncation step, after size-filtering.
        pool_camera_limits = per_camera_limits
        if per_camera_limits:
            pool_camera_limits = {cam: 10**9 for cam in per_camera_limits}
        pool = self.prepare_action_df(
            all_variants=all_variants,
            max_images=None,
            random_sample=random_sample,
            per_camera_limits=pool_camera_limits,
            require_lbl=require_lbl,
            selection_df=selection_df,
            get_selection_df=get_selection_df,
            route_selection_by_catalog_boundary=route_selection_by_catalog_boundary,
            norm_ascii=norm_ascii,
        )
        max_checks = 60
        if desired_count is not None and int(desired_count) > 0:
            max_checks = min(60, max(20, int(desired_count) * 2))
        sized_pool, stats = self.prefilter_df_by_min_size(
            state,
            pool,
            min_size_bytes=min_size_threshold,
            desired_count=desired_count,
            max_remote_checks=max_checks,
            per_camera_targets=per_camera_targets,
        )
        final_df = self.prepare_action_df(
            all_variants=all_variants,
            max_images=max_images,
            random_sample=random_sample,
            per_camera_limits=per_camera_limits,
            require_lbl=require_lbl,
            selection_df=sized_pool,
            get_selection_df=get_selection_df,
            route_selection_by_catalog_boundary=route_selection_by_catalog_boundary,
            norm_ascii=norm_ascii,
        )
        return final_df, stats, min_size_threshold

