"""Crea una lista Markdown leggibile dal JSON di classificazione PDS."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _fmt(values: list[str] | tuple[str, ...]) -> str:
    return ", ".join(f"`{value}`" for value in values) if values else "—"


def _exact_camera(lines: list[str], name: str, camera: dict[str, Any]) -> None:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    examples: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in camera.get("combinations", []):
        descriptor = str(row.get("descriptor") or "UNKNOWN")
        suffix = str(row.get("processing_suffix") or "(nessuno)")
        grouped[descriptor][suffix] += int(row.get("count") or 0)
        key = (descriptor, suffix)
        for example in row.get("examples", []):
            if example not in examples[key] and len(examples[key]) < 2:
                examples[key].append(example)
    lines.extend((f"## {name}", "", "Combinazioni osservate nel campionamento:", ""))
    for descriptor in sorted(grouped):
        suffixes = sorted(grouped[descriptor])
        total = sum(grouped[descriptor].values())
        lines.append(f"- **{descriptor}** → {_fmt(suffixes)} _(osservazioni: {total:,})_".replace(",", "."))
    lines.append("")


def _engineering_camera(lines: list[str], name: str, camera: dict[str, Any]) -> None:
    lines.extend((f"## {name}", "", "Famiglie, varianti e prefissi camera osservati:", ""))
    for family, data in sorted((camera.get("families") or {}).items()):
        variants = sorted((data.get("variants") or {}).keys())
        prefixes = sorted((data.get("camera_prefixes") or {}).keys())
        lines.append(f"- **{family}** — varianti: {_fmt(variants)}; camere: {_fmt(prefixes)}")
    lines.append("")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    cameras = payload.get("cameras") or {}
    lines = [
        "# Prodotti PDS MSL osservati",
        "",
        "Lista ricavata dal censimento periodico delle directory NASA/PDS. È un inventario empirico: "
        "descrive ciò che è stato osservato nelle finestre campionate e non sostituisce la specifica ufficiale.",
        "",
        "> Le sigle sono mantenute senza interpretazioni non ancora verificate. La presenza nella lista non implica "
        "che il prodotto sia già incluso nei cataloghi locali.",
        "",
    ]
    display_names = {
        "mastcam": "Mastcam", "mahli": "MAHLI", "mardi": "MARDI",
        "chemcam": "ChemCam", "navcam": "Navcam", "hazcam": "Hazcam",
    }
    for key in ("mastcam", "mahli", "mardi", "chemcam"):
        if key in cameras:
            _exact_camera(lines, display_names[key], cameras[key])
    for key in ("navcam", "hazcam"):
        if key in cameras:
            _engineering_camera(lines, display_names[key], cameras[key])
    lines.extend((
        "## Uso previsto nella UI", "",
        "Questa lista servirà a costruire selettori gerarchici: prodotto comprensibile, codice NASA, "
        "varianti compatibili e prefissi camera. Le combinazioni non osservate non dovranno essere proposte automaticamente.",
        "",
    ))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8")
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
