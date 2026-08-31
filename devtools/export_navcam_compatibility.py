from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: export_navcam_compatibility.py CENSUS_JSON OUTPUT_JSON")
    source = Path(sys.argv[1])
    output = Path(sys.argv[2])
    payload = json.loads(source.read_text(encoding="utf-8"))
    observed: dict[str, dict[str, set[str]]] = {}
    for row in payload.get("combinations", []):
        if str(row.get("camera", "")).casefold() != "navcam":
            continue
        prefix = str(row.get("camera_prefix", "")).upper()
        # descriptor_or_tokens also contains unrelated five-character tokens
        # (for example NCAM, TRAV and the camera prefix).  Reading all of them
        # and crossing them with every camera creates combinations that never
        # existed.  Extract the product marker from an observed product name.
        marker = ""
        for example in row.get("examples", []):
            match = re.match(r"^[A-Z0-9]{3}_\d+([A-Z0-9_]{5})", str(example).upper())
            if match:
                marker = match.group(1)
                break
        if len(prefix) != 3 or len(marker) != 5:
            continue
        observed.setdefault(marker[:3], {}).setdefault(prefix, set()).add(marker[3:])
    serializable = {
        family: {prefix: sorted(variants) for prefix, variants in sorted(prefixes.items())}
        for family, prefixes in sorted(observed.items())
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(serializable, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
