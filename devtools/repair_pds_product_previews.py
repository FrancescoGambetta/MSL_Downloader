"""Rebuild existing preview assets after improvements to the PDS decoder."""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from download_pds_product_examples import _build_one


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "catalog_manager" / "assets" / "pds_product_examples"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument(
        "--only-older-than",
        default="",
        help="Rigenera soltanto le anteprime mancanti o modificate prima di questa data ISO locale.",
    )
    args = parser.parse_args()

    output = args.output_dir.resolve()
    manifest_path = output / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    examples = list(payload.get("examples", []))
    cutoff = datetime.fromisoformat(args.only_older_than) if args.only_older_than else None
    indices: list[int] = []
    for i, item in enumerate(examples):
        if str(item.get("camera", "")).lower() != args.camera.lower():
            continue
        preview = output / str(item.get("preview", ""))
        if cutoff is not None and preview.exists() and datetime.fromtimestamp(preview.stat().st_mtime) >= cutoff:
            continue
        indices.append(i)
    print(f"Anteprime {args.camera} da rigenerare: {len(indices)}", flush=True)
    started = time.monotonic()

    def candidate(item: dict) -> dict:
        result = {k: v for k, v in item.items() if k not in {"status", "error", "bytes", "preview"}}
        result["key"] = tuple(item["combination"])
        return result

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(
                _build_one,
                candidate(examples[index]),
                output,
                args.timeout,
                int(payload.get("preview_settings", {}).get("max_side", 1200)),
                int(payload.get("preview_settings", {}).get("jpeg_quality", 82)),
                args.retries,
                True,
            ): index
            for index in indices
        }
        for done, future in enumerate(as_completed(futures), 1):
            index = futures[future]
            result = future.result()
            examples[index] = result
            print(f"[{done}/{len(futures)}] {result['product_id']}: {result['status']}", flush=True)

    payload["examples"] = examples
    summary = payload.setdefault("summary", {})
    summary["previews_ready"] = sum(item.get("status") in {"ok", "existing"} for item in examples)
    summary["conversion_errors"] = sum(item.get("status") == "error" for item in examples)
    summary["elapsed_seconds"] = round(time.monotonic() - started, 3)
    payload["generated_at_unix"] = time.time()
    temporary = manifest_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(manifest_path)
    print(f"Manifest aggiornato: {manifest_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
