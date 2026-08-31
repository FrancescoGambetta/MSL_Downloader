"""Loads and compiles camera_rules.json into the flat matcher structure `CatalogFilterService` scans against.

camera_rules.json can express a camera's rule two ways: the current
per-source `"rules": {"pds": {...}, "raw": {...}}` block, or (PDS-only)
a set of legacy top-level keys directly on the camera entry (see
`legacy_pds_constraints`). `compile_camera_rules` normalizes both into one
`items` list with pre-computed alias regexes so the actual per-row filtering
in `CatalogFilterService` doesn't have to re-parse the raw JSON per row.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable


class CatalogRulesService:
    """Reads camera_rules.json, merges it over the fallback, and compiles it into the per-camera matcher list."""

    def __init__(
        self,
        *,
        normalize_text: Callable[[Any], str],
        norm_ascii: Callable[[str], str],
    ) -> None:
        self._normalize_text = normalize_text
        self._norm_ascii = norm_ascii

    def deep_merge(self, dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
        """Recursively merge `src` into `dst` (dict values merge; everything else is overwritten)."""
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                dst[k] = self.deep_merge(dict(dst[k]), v)
            else:
                dst[k] = v
        return dst

    def load_camera_rules_from_path(self, *, fallback: dict[str, Any], path: Path) -> dict[str, Any]:
        """Read `path` (camera_rules.json) merged over `fallback`, or just `fallback` if the file is missing/invalid."""
        out = dict(fallback)
        if not path.exists():
            return out
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return self.deep_merge(out, raw)
        except Exception:
            pass
        return out

    def norm_token_list(self, values: Any) -> list[str]:
        """Normalize a list of tokens to unique, non-empty, uppercased strings (order preserved), or [] if `values` isn't a list."""
        if not isinstance(values, list):
            return []
        out: list[str] = []
        seen: set[str] = set()
        for v in values:
            tok = self._normalize_text(v).upper()
            if not tok or tok in seen:
                continue
            seen.add(tok)
            out.append(tok)
        return out

    def norm_alias_list(self, values: Any) -> list[str]:
        """Normalize a list of camera-name aliases to unique, non-empty, ASCII-folded lowercase strings, or [] if `values` isn't a list."""
        if not isinstance(values, list):
            return []
        out: list[str] = []
        seen: set[str] = set()
        for v in values:
            tok = self._norm_ascii(str(v))
            if not tok or tok in seen:
                continue
            seen.add(tok)
            out.append(tok)
        return out

    def compact_ascii(self, text: str) -> str:
        """ASCII-fold `text` and strip everything but letters/digits, for alias matching that ignores spaces/punctuation (e.g. "Nav Cam" -> "navcam")."""
        return re.sub(r"[^a-z0-9]+", "", self._norm_ascii(text))

    def camera_rules_items(self, rules_cfg: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        """Return `(camera_name, rule_dict)` pairs from camera_rules.json, supporting both the nested `"cameras": {...}` layout and top-level camera keys."""
        if not isinstance(rules_cfg, dict):
            return []
        reserved = {"raw_global_rules", "version", "schema_version", "cameras"}
        out: list[tuple[str, dict[str, Any]]] = []
        nested = rules_cfg.get("cameras")
        if isinstance(nested, dict):
            for k, v in nested.items():
                if isinstance(v, dict):
                    out.append((str(k), v))
        for k, v in rules_cfg.items():
            if k in reserved:
                continue
            if isinstance(v, dict):
                out.append((str(k), v))
        return out

    def legacy_pds_constraints(self, rule: dict[str, Any]) -> dict[str, Any]:
        """Extract the pre-`"rules"` top-level PDS constraint keys straight off a camera rule entry (backward compatibility)."""
        keys = (
            "suffix_equals_any",
            "filename_prefix_any",
            "filename_contains_all",
            "filename_contains_any",
            "min_img_size_bytes",
            "min_img_size_exempt_markers_any",
        )
        out: dict[str, Any] = {}
        for k in keys:
            if k in rule:
                out[k] = rule.get(k)
        return out

    def source_constraints(self, rule: dict[str, Any], source_name: str) -> tuple[str, dict[str, Any]] | None:
        """Return `(filter_key, constraints)` for `source_name` ("pds"/"raw") from a camera rule -- from its `"rules"` block if present, else (PDS only) from the legacy top-level keys. None if this camera has no rule for that source."""
        filter_key_default = self._normalize_text(rule.get("filter_key"))
        rules_block = rule.get("rules")
        if isinstance(rules_block, dict):
            src_rule = rules_block.get(source_name)
            if not isinstance(src_rule, dict):
                return None
            filter_key = self._normalize_text(src_rule.get("apply_when_filter_key")) or self._normalize_text(src_rule.get("filter_key")) or filter_key_default
            return filter_key, src_rule

        if source_name == "pds":
            legacy = self.legacy_pds_constraints(rule)
            if not legacy:
                return None
            return filter_key_default, legacy
        return None

    def compile_camera_rules(
        self,
        raw: dict[str, Any],
        *,
        camera_alias_defaults: dict[str, list[str]],
    ) -> dict[str, Any]:
        """Compile `raw` (camera_rules.json contents) into `{"raw_global_rules": ..., "items": [...]}`, one item per camera with pre-built alias-matching regexes and per-source (PDS/RAW) filter constraints."""
        compiled: dict[str, Any] = {
            "raw_global_rules": raw.get("raw_global_rules", {}) if isinstance(raw, dict) else {},
            "items": [],
        }
        for cam_name, rule in self.camera_rules_items(raw):
            if not isinstance(rule, dict):
                continue
            cam_key = self._norm_ascii(str(cam_name))
            aliases = [cam_key]
            aliases.extend(self.norm_alias_list(camera_alias_defaults.get(cam_key, [])))
            aliases.extend(self.norm_alias_list(rule.get("camera_aliases_any") or []))
            alias_boundaries = [
                rf"(?:^|[^a-z0-9]){re.escape(alias)}(?:[^a-z0-9]|$)"
                for alias in aliases
                if alias
            ]
            alias_compacts = [self.compact_ascii(alias) for alias in aliases if self.compact_ascii(alias)]
            markers = self.norm_token_list(rule.get("camera_markers_any") or [])

            sources: dict[str, dict[str, Any]] = {}
            for source_name in ("pds", "raw"):
                resolved = self.source_constraints(rule, source_name)
                if resolved is None:
                    continue
                filter_key, constraints = resolved
                if not isinstance(constraints, dict):
                    continue
                sources[source_name] = {
                    "filter_key": self._normalize_text(filter_key),
                    "suffix_any": self.norm_token_list(constraints.get("suffix_equals_any") or []),
                    "prefix_any": self.norm_token_list(constraints.get("filename_prefix_any") or []),
                    "contains_all": self.norm_token_list(constraints.get("filename_contains_all") or []),
                    "contains_any": self.norm_token_list(constraints.get("filename_contains_any") or []),
                    "exempt_markers": self.norm_token_list(constraints.get("min_img_size_exempt_markers_any") or []),
                    "min_img_size_bytes": constraints.get("min_img_size_bytes"),
                }

            compiled["items"].append(
                {
                    "camera_name": str(cam_name),
                    "camera_key": cam_key,
                    "alias_boundaries": alias_boundaries,
                    "alias_compacts": alias_compacts,
                    "markers": markers,
                    "sources": sources,
                }
            )
        return compiled

