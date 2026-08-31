"""Tiny text-normalization helper shared by other services (ASCII-folding)."""

from __future__ import annotations

import unicodedata
from typing import Any, Callable


class TextUtilsService:
    """Wraps `norm_ascii`, the accent-stripping helper used for fuzzy/whole-word text matching."""

    def __init__(
        self,
        *,
        normalize_text: Callable[[Any], str],
    ) -> None:
        self._normalize_text = normalize_text

    def norm_ascii(self, text: str) -> str:
        """Lowercase-trim `text` and strip diacritics via Unicode NFKD decomposition, e.g. "café" -> "cafe"."""
        txt = self._normalize_text(text)
        if not txt:
            return ""
        return unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode("ascii")
