from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

import psutil


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.raw_json_rebuild import raw_json_to_parquet_streaming, rebuild_raw_json_streaming  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Scalable RAW Parquet -> JSON -> Parquet audit")
    parser.add_argument("--sol-start", type=int, default=None)
    parser.add_argument("--sol-end", type=int, default=None)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output_dir = (ROOT / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    source = ROOT / "data" / "catalog" / "Catalog_RawArch.parquet"
    schema = ROOT / "config" / "raw_catalog_schema.json"
    json_path = output_dir / "Catalog_RawArch.json"
    rebuilt_path = output_dir / "Catalog_RawArch.roundtrip.parquet"
    report_path = output_dir / "streaming_roundtrip_report.json"
    process = psutil.Process()
    peak = {"rss": process.memory_info().rss}
    stop = threading.Event()

    def monitor() -> None:
        while not stop.wait(0.1):
            peak["rss"] = max(peak["rss"], process.memory_info().rss)

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    started = time.perf_counter()
    last_print = 0.0

    def progress(done: int, total: int, camera: str) -> None:
        nonlocal last_print
        now = time.monotonic()
        if done == total or now - last_print >= 2:
            print(f"progress={done:,}/{total:,} camera={camera}")
            last_print = now

    try:
        build = rebuild_raw_json_streaming(source, json_path, schema, progress, sol_start=args.sol_start, sol_end=args.sol_end)
        rebuild = raw_json_to_parquet_streaming(json_path, rebuilt_path, schema)
    finally:
        stop.set()
        thread.join()
    passed = (
        build["rows"] == rebuild["rows"]
        and build["camera_counts"] == rebuild["camera_counts"]
        and build["record_sha256"] == rebuild["record_sha256"]
    )
    report = {
        "status": "PASS" if passed else "FAIL",
        "sol_start": args.sol_start,
        "sol_end": args.sol_end,
        "build": build,
        "rebuild": rebuild,
        "elapsed_seconds": time.perf_counter() - started,
        "peak_rss_bytes": peak["rss"],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"status={report['status']} rows={build['rows']:,} elapsed={report['elapsed_seconds']:.2f}s peak_rss_GB={peak['rss']/1073741824:.2f}")
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
