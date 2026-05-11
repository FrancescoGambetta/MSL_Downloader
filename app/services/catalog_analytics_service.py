from __future__ import annotations

import re
from typing import Any, Callable, Optional

import pandas as pd


class CatalogAnalyticsService:
    def __init__(
        self,
        *,
        normalize_text: Callable[[Any], str],
        norm_ascii: Callable[[str], str],
    ) -> None:
        self._normalize_text = normalize_text
        self._norm_ascii = norm_ascii

    def selection_report(self, state: dict[str, Any], *, t: Callable[..., str]) -> str:
        df = state["selected_df"] if "selected_df" in state else state.get("df_filtered", pd.DataFrame())
        if not isinstance(df, pd.DataFrame) or len(df) == 0:
            return t("selection_empty")
        if "sol" in df.columns:
            s = pd.to_numeric(df["sol"], errors="coerce").dropna()
            if len(s) > 0:
                start, end, sols = int(s.min()), int(s.max()), int(s.nunique())
                if "camera" in df.columns:
                    cameras = [self._normalize_text(c) for c in df["camera"].dropna().astype(str).tolist() if self._normalize_text(c)]
                    unique_cams = sorted({c for c in cameras if c})
                    if len(unique_cams) == 1:
                        return t(
                            "report_natural_single_camera",
                            rows=len(df),
                            camera=unique_cams[0],
                            sols=sols,
                            start=start,
                            end=end,
                        )
                return t("report_natural_generic", rows=len(df), sols=sols, start=start, end=end)
        return t("report_rows", rows=len(df))

    def report_scope_text(self, state: dict[str, Any], *, t: Callable[..., str], use_filtered: bool) -> str:
        total_rows = len(state["df"]) if "df" in state else 0
        if use_filtered:
            filtered_rows = len(state["df_filtered"]) if "df_filtered" in state else 0
            return t("report_scope_filtered", rows_filtered=filtered_rows, rows_total=total_rows)
        return t("report_scope_full", rows_total=total_rows)

    def catalog_content_report(self, state: dict[str, Any], *, t: Callable[..., str], use_filtered: bool = True) -> str:
        df = state.get("df_filtered") if use_filtered else state.get("df")
        if not isinstance(df, pd.DataFrame) or len(df) == 0:
            return f"{self.report_scope_text(state, t=t, use_filtered=use_filtered)}\n{t('db_empty')}"
        lines = [self.report_scope_text(state, t=t, use_filtered=use_filtered)]
        if "camera" in df.columns:
            vc = df["camera"].astype(str).value_counts().head(10)
            lines.append(t("report_top_cameras", values=", ".join(f"{k}:{v}" for k, v in vc.items())))
        if "sol" in df.columns:
            s = pd.to_numeric(df["sol"], errors="coerce").dropna()
            if len(s):
                start, end, sols = int(s.min()), int(s.max()), int(s.nunique())
                if "camera" in df.columns:
                    cameras = [self._normalize_text(c) for c in df["camera"].dropna().astype(str).tolist() if self._normalize_text(c)]
                    unique_cams = sorted({c for c in cameras if c})
                    if len(unique_cams) == 1:
                        lines.insert(
                            0,
                            t(
                                "report_natural_single_camera",
                                rows=len(df),
                                camera=unique_cams[0],
                                sols=sols,
                                start=start,
                                end=end,
                            ),
                        )
                    else:
                        lines.insert(0, t("report_natural_generic", rows=len(df), sols=sols, start=start, end=end))
                else:
                    lines.insert(0, t("report_natural_generic", rows=len(df), sols=sols, start=start, end=end))
        if "img_size_bytes" in df.columns:
            sz = pd.to_numeric(df["img_size_bytes"], errors="coerce").dropna()
            if len(sz):
                known = int(sz.count())
                pct = (known / max(len(df), 1)) * 100.0
                lines.append(t("report_known_img_size", known=known, total=len(df), pct=f"{pct:.1f}"))
        return "\n".join(lines)

    def camera_types_report(self, state: dict[str, Any], *, t: Callable[..., str]) -> str:
        df = state.get("df")
        if not isinstance(df, pd.DataFrame):
            return t("camera_types_missing_column")
        if "camera" not in df.columns:
            return t("camera_types_missing_column")
        cams = sorted({str(v).strip() for v in df["camera"].dropna().astype(str) if str(v).strip()})
        if not cams:
            return t("camera_types_none")
        return "\n".join(
            [
                t("camera_types_title", count=len(cams)),
                *[f"- {c}" for c in cams],
            ]
        )

    def query_uses_filtered_context(self, cmd: str) -> bool:
        cmdn = self._norm_ascii(cmd)
        return any(
            phrase in cmdn
            for phrase in (
                "filtri",
                "filters",
                "filtered",
                "con questi filtri",
                "with these filters",
                "con filtro",
                "con i filtri",
            )
        )

    def query_uses_global_context(self, cmd: str) -> bool:
        cmdn = self._norm_ascii(cmd)
        return any(
            phrase in cmdn
            for phrase in (
                "database totale",
                "intero database",
                "tutto il database",
                "entire database",
                "whole database",
                "all database",
                "global database",
                "full database",
                "total database",
            )
        )

    def count_query_camera_matches(self, cmd: str, available_cameras: list[str]) -> list[str]:
        cmdn = self._norm_ascii(cmd)
        cmd_compact = re.sub(r"[^a-z0-9]+", "", cmdn)
        matches: list[str] = []
        alias_map = {
            "navcam": ["navcam", "nav cam", "ncam"],
            "hazcam": ["hazcam", "haz cam", "fhaz", "rhaz"],
            "mastcam": ["mastcam", "mast cam", "mcam"],
            "mahli": ["mahli", "m h l i"],
            "mardi": ["mardi", "m a r d i"],
            "chemcam": ["chemcam", "chem cam", "ccam", "rmi"],
        }
        for cam in available_cameras:
            camn = self._norm_ascii(cam)
            if not camn:
                continue
            aliases = {camn, re.sub(r"[^a-z0-9]+", "", camn)}
            for key, vals in alias_map.items():
                if key in camn:
                    aliases.update(vals)
            hit = False
            for alias in aliases:
                alias_n = self._norm_ascii(alias)
                if not alias_n:
                    continue
                if re.search(rf"\\b{re.escape(alias_n)}\\b", cmdn):
                    hit = True
                    break
                alias_compact = re.sub(r"[^a-z0-9]+", "", alias_n)
                if alias_compact and alias_compact in cmd_compact:
                    hit = True
                    break
            if hit:
                matches.append(cam)
        return list(dict.fromkeys(matches))

    def query_is_count(self, cmd: str) -> bool:
        cmdn = self._norm_ascii(cmd)
        tokens = (
            "quante",
            "quanti",
            "how many",
            "combien",
            "wie viele",
            "cuantas",
            "cuantos",
        )
        return any(tok in cmdn for tok in tokens)

    def query_is_max_sol(self, cmd: str) -> bool:
        cmdn = self._norm_ascii(cmd)
        has_sol = "sol" in cmdn
        max_patterns = (
            r"\bcon\s+piu\b",
            r"\bpiu\b",
            r"\bmassim[oa]?\b",
            r"\bmax(?:imum)?\b",
            r"\bmost\b",
            r"\bhighest\b",
            r"\bplus\b",
            r"\bmehr\b",
            r"\bmas\b",
            r"\bmayor\b",
        )
        has_max = any(re.search(pat, cmdn) for pat in max_patterns)
        return has_sol and has_max

    def is_analytics_query(self, command: str) -> bool:
        cmd = self._normalize_text(command)
        return self.query_is_count(cmd) or self.query_is_max_sol(cmd)

    def parse_size_bytes_from_query(self, text: str) -> Optional[int]:
        t = self._norm_ascii(text).replace(",", ".")
        m = re.search(r"(\d+(?:\.\d+)?)\s*(kb|mb|gb|b)\b", t, re.IGNORECASE)
        if not m:
            m = re.search(r"(?:>=|>|min(?:imum)?|almeno|piu grandi di|piu grande di)\s*(\d{1,9})\b", t, re.IGNORECASE)
            if m:
                try:
                    return int(float(m.group(1)))
                except Exception:
                    return None
            return None
        try:
            value = float(m.group(1))
        except Exception:
            return None
        unit = m.group(2).lower()
        if unit == "kb":
            return int(value * 1024)
        if unit == "mb":
            return int(value * 1024 * 1024)
        if unit == "gb":
            return int(value * 1024 * 1024 * 1024)
        return int(value)

    def parse_sol_range_from_query(self, text: str) -> tuple[Optional[int], Optional[int]]:
        t = self._norm_ascii(text)
        separators = r"(?:a|al|to|au|hasta|bis|fino(?:\s+a|al)?|until|till|through|thru|jusqu'?a|ifno|fno|\-|\.\.)"
        separators_with_and = rf"(?:{separators}|(?:e|and|et|y)(?:\\s+(?:il|lo|la|l|the|el|le))?)"
        patterns = [
            rf"\b(?:da|dal|from|de|del|between|tra|entre)?\s*sol(?:\s*range)?\s*(\d{{1,5}})\s*{separators_with_and}\s*(?:sol\s*)?(\d{{1,5}})\b",
            rf"\bsol\s*(\d{{1,5}})\s*{separators_with_and}\s*(?:sol\s*)?(\d{{1,5}})\b",
        ]
        for pat in patterns:
            m = re.search(pat, t, re.IGNORECASE)
            if m:
                return int(m.group(1)), int(m.group(2))
        m = re.search(r"\bsol\s*(\d{1,5})(?=\D|$)", t, re.IGNORECASE)
        if m:
            v = int(m.group(1))
            return v, v
        return None, None

    def format_size_human(self, size_bytes: int) -> str:
        val = float(size_bytes)
        if val >= 1024 * 1024 * 1024:
            return f"{val / (1024 * 1024 * 1024):.2f} GB"
        if val >= 1024 * 1024:
            return f"{val / (1024 * 1024):.2f} MB"
        if val >= 1024:
            return f"{val / 1024:.2f} KB"
        return f"{int(val)} B"

    def analytics_use_filtered_scope(
        self,
        state: dict[str, Any],
        command: str,
        *,
        filters_active: Callable[[], bool],
    ) -> bool:
        cmd = self._normalize_text(command)
        if self.query_uses_filtered_context(cmd):
            return True
        if self.query_uses_global_context(cmd):
            return False
        return filters_active()

    def database_count_report(self, state: dict[str, Any], command: str, *, t: Callable[..., str], use_filtered: bool = False) -> str:
        cmd = self._normalize_text(command)
        df = state.get("df_filtered") if use_filtered else state.get("df")
        if not isinstance(df, pd.DataFrame) or len(df) == 0:
            return f"{self.report_scope_text(state, t=t, use_filtered=use_filtered)}\n{t('db_empty')}"

        if "camera" not in df.columns:
            return f"{self.report_scope_text(state, t=t, use_filtered=use_filtered)}\n{t('report_rows', rows=len(df))}"

        available_cameras = [str(v).strip() for v in df["camera"].dropna().astype(str).tolist() if str(v).strip()]
        picked = self.count_query_camera_matches(cmd, sorted(set(available_cameras)))
        if picked:
            cam_norms = {self._norm_ascii(c) for c in picked if self._norm_ascii(c)}
            if cam_norms:
                # Fast exact match on compact normalization (covers spaces/punctuation differences).
                norm_set = {re.sub(r"[^a-z0-9]+", "", cn.lower()) for cn in cam_norms if cn}
                cam_compact = df["camera"].fillna("").astype(str).str.lower().str.replace(r"[^a-z0-9]+", "", regex=True)
                sub = df[cam_compact.isin(norm_set)].copy()
            else:
                sub = df.iloc[0:0].copy()
        else:
            sub = df.copy()

        sol_start, sol_end = self.parse_sol_range_from_query(cmd)
        if sol_start is not None and "sol" in sub.columns:
            low = min(sol_start, sol_end or sol_start)
            high = max(sol_start, sol_end or sol_start)
            sol_series = pd.to_numeric(sub["sol"], errors="coerce")
            sub = sub[(sol_series >= float(low)) & (sol_series <= float(high))].copy()

        size_bytes = self.parse_size_bytes_from_query(cmd)
        size_note = ""
        if size_bytes is not None:
            if "img_size_bytes" in sub.columns:
                sub = sub[pd.to_numeric(sub["img_size_bytes"], errors="coerce").fillna(-1) >= float(size_bytes)].copy()
                size_note = t("report_size_filter_applied", size=self.format_size_human(size_bytes))
            else:
                size_note = t("report_size_filter_missing_col", size=self.format_size_human(size_bytes))

        if len(sub) == 0:
            return f"{self.report_scope_text(state, t=t, use_filtered=use_filtered)}\n{t('report_rows', rows=0)}"

        if "sol" in sub.columns:
            s = pd.to_numeric(sub["sol"], errors="coerce").dropna()
            if len(s):
                start, end, sols = int(s.min()), int(s.max()), int(s.nunique())
                if picked and len(picked) == 1:
                    msg = t(
                        "report_natural_single_camera",
                        rows=len(sub),
                        camera=picked[0],
                        sols=sols,
                        start=start,
                        end=end,
                    )
                    body = f"{msg}\n{size_note}".strip() if size_note else msg
                    return f"{self.report_scope_text(state, t=t, use_filtered=use_filtered)}\n{body}"
                msg = t("report_natural_generic", rows=len(sub), sols=sols, start=start, end=end)
                body = f"{msg}\n{size_note}".strip() if size_note else msg
                return f"{self.report_scope_text(state, t=t, use_filtered=use_filtered)}\n{body}"

        if picked and len(picked) == 1:
            msg = t("report_rows", rows=len(sub))
            body = f"{msg}\n{size_note}".strip() if size_note else msg
            return f"{self.report_scope_text(state, t=t, use_filtered=use_filtered)}\n{body}"
        msg = t("report_rows", rows=len(sub))
        body = f"{msg}\n{size_note}".strip() if size_note else msg
        return f"{self.report_scope_text(state, t=t, use_filtered=use_filtered)}\n{body}"

    def database_max_sol_report(self, state: dict[str, Any], command: str, *, t: Callable[..., str], use_filtered: bool = False) -> str:
        cmd = self._normalize_text(command)
        df = state.get("df_filtered") if use_filtered else state.get("df")
        if not isinstance(df, pd.DataFrame) or len(df) == 0:
            return f"{self.report_scope_text(state, t=t, use_filtered=use_filtered)}\n{t('db_empty')}"
        if "sol" not in df.columns:
            return f"{self.report_scope_text(state, t=t, use_filtered=use_filtered)}\n{t('report_no_sol_data')}"

        base = df
        picked: list[str] = []
        if "camera" in df.columns:
            available_cameras = [str(v).strip() for v in df["camera"].dropna().astype(str).tolist() if str(v).strip()]
            picked = self.count_query_camera_matches(cmd, sorted(set(available_cameras)))
            if picked:
                cam_norms = {self._norm_ascii(c) for c in picked if self._norm_ascii(c)}
                norm_set = {re.sub(r"[^a-z0-9]+", "", cn.lower()) for cn in cam_norms if cn}
                cam_compact = df["camera"].fillna("").astype(str).str.lower().str.replace(r"[^a-z0-9]+", "", regex=True)
                base = df[cam_compact.isin(norm_set)].copy()

        sol_start, sol_end = self.parse_sol_range_from_query(cmd)
        if sol_start is not None and "sol" in base.columns:
            low = min(sol_start, sol_end or sol_start)
            high = max(sol_start, sol_end or sol_start)
            sol_series = pd.to_numeric(base["sol"], errors="coerce")
            base = base[(sol_series >= float(low)) & (sol_series <= float(high))].copy()

        size_bytes = self.parse_size_bytes_from_query(cmd)
        size_note = ""
        if size_bytes is not None:
            if "img_size_bytes" in base.columns:
                base = base[pd.to_numeric(base["img_size_bytes"], errors="coerce").fillna(-1) >= float(size_bytes)].copy()
                size_note = t("report_size_filter_applied", size=self.format_size_human(size_bytes))
            else:
                size_note = t("report_size_filter_missing_col", size=self.format_size_human(size_bytes))

        if len(base) == 0:
            return f"{self.report_scope_text(state, t=t, use_filtered=use_filtered)}\n{t('report_rows', rows=0)}"

        sol_series = pd.to_numeric(base["sol"], errors="coerce").dropna().astype(int)
        if len(sol_series) == 0:
            return f"{self.report_scope_text(state, t=t, use_filtered=use_filtered)}\n{t('report_no_sol_data')}"

        counts = sol_series.value_counts()
        max_count = int(counts.max())
        top_sols = sorted([int(idx) for idx, val in counts.items() if int(val) == max_count])
        if not top_sols:
            return f"{self.report_scope_text(state, t=t, use_filtered=use_filtered)}\n{t('report_no_sol_data')}"
        if picked and len(picked) == 1:
            if len(top_sols) == 1:
                msg = t("report_max_sol_single_camera", camera=picked[0], sol=top_sols[0], count=max_count)
                body = f"{msg}\n{size_note}".strip() if size_note else msg
                return f"{self.report_scope_text(state, t=t, use_filtered=use_filtered)}\n{body}"
            msg = t(
                "report_max_sol_single_camera_tie",
                camera=picked[0],
                sols=", ".join(str(s) for s in top_sols),
                count=max_count,
            )
            body = f"{msg}\n{size_note}".strip() if size_note else msg
            return f"{self.report_scope_text(state, t=t, use_filtered=use_filtered)}\n{body}"
        if len(top_sols) == 1:
            msg = t("report_max_sol_generic", sol=top_sols[0], count=max_count)
            body = f"{msg}\n{size_note}".strip() if size_note else msg
            return f"{self.report_scope_text(state, t=t, use_filtered=use_filtered)}\n{body}"
        msg = t("report_max_sol_generic_tie", sols=", ".join(str(s) for s in top_sols), count=max_count)
        body = f"{msg}\n{size_note}".strip() if size_note else msg
        return f"{self.report_scope_text(state, t=t, use_filtered=use_filtered)}\n{body}"
