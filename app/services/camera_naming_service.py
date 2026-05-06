from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable


class CameraNamingService:
    def __init__(
        self,
        *,
        normalize_text: Callable[[Any], str],
    ) -> None:
        self._normalize_text = normalize_text

    def camera_folder_for_filename(self, filename: str) -> str:
        up = self._normalize_text(filename).upper()
        stem = Path(up).stem
        if re.search(r"^\d{4}MH", stem):
            return "MAHLI"
        if "FHAZ" in up or "RHAZ" in up:
            return "HAZ"
        if "TRAV" in up:
            return "TRAV"
        if "NCAM" in up or up.startswith(("NLB_", "NRB_", "NAB_", "NRA_", "NLA_", "NAA_")):
            return "NAV"
        if "MAHLI" in up or "MHLI" in up:
            return "MAHLI"
        if "MARDI" in up or re.search(r"^\d{4}MD", stem):
            return "MARDI"
        if "CHEMCAM" in up or "CCAM" in up or "RMI" in up:
            return "CHEMCAM"
        if re.search(r"^\d{4}M[LR]", stem) or "MASTCAM" in up:
            return "MASTCAM"
        return ""

