from __future__ import annotations

import unicodedata
from typing import Any, Callable


class TextUtilsService:
    def __init__(
        self,
        *,
        normalize_text: Callable[[Any], str],
    ) -> None:
        self._normalize_text = normalize_text

    def norm_ascii(self, text: str) -> str:
        txt = self._normalize_text(text)
        if not txt:
            return ""
        return unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode("ascii")

