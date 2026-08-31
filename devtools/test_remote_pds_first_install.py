from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path

import requests

from validate_pds_release import validate_release


ROOT = Path(__file__).resolve().parents[1]


def _download(url: str, destination: Path) -> tuple[int, float]:
    started = time.perf_counter()
    downloaded = 0
    last_report = 0
    with requests.get(url, stream=True, timeout=(30, 180)) as response:
        response.raise_for_status()
        content_type = str(response.headers.get("Content-Type") or "").lower()
        if "text/html" in content_type:
            raise RuntimeError("Google Drive returned HTML instead of the requested file")
        total_text = response.headers.get("Content-Length")
        total = int(total_text) if total_text and total_text.isdigit() else None
        with destination.open("wb") as stream:
            for block in response.iter_content(chunk_size=1024 * 1024):
                if not block:
                    continue
                stream.write(block)
                downloaded += len(block)
                current_mb = downloaded // (5 * 1024 * 1024)
                if current_mb > last_report:
                    last_report = current_mb
                    suffix = f"/{total / 1048576:.1f} MB" if total else " MB"
                    print(f"  downloaded {downloaded / 1048576:.1f}{suffix}")
    return downloaded, time.perf_counter() - started


def main() -> None:
    parser = argparse.ArgumentParser(description="Exercise a real remote PDS first install without touching runtime catalogs.")
    parser.add_argument(
        "--destination",
        type=Path,
        default=ROOT / "data" / "catalog_json_rebuild" / "remote_first_install" / "data" / "catalog",
    )
    args = parser.parse_args()
    destination = args.destination.resolve()
    allowed_root = (ROOT / "data" / "catalog_json_rebuild").resolve()
    if allowed_root not in destination.parents:
        raise SystemExit(f"Unsafe test destination: {destination}")

    config = json.loads((ROOT / "config" / "catalog_distribution_sources.json").read_text(encoding="utf-8"))["pds"]
    manifest_schema = ROOT / "config" / "pds_release_manifest_schema.json"
    data_schema = ROOT / "config" / "pds_catalog_schema.json"
    destination.mkdir(parents=True, exist_ok=True)
    final_parquet = destination / "Catalog_PDS.parquet"
    final_manifest = destination / "Catalog_PDS.manifest.json"
    started = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix=".remote-pds-test-", dir=destination.parent) as temporary:
        staging = Path(temporary)
        staged_manifest = staging / final_manifest.name
        staged_parquet = staging / final_parquet.name
        print("Downloading manifest...")
        manifest_bytes, manifest_seconds = _download(str(config["manifest"]["download_url"]), staged_manifest)
        print("Downloading Parquet...")
        parquet_bytes, parquet_seconds = _download(str(config["parquet"]["download_url"]), staged_parquet)
        validation_started = time.perf_counter()
        errors = validate_release(staged_parquet, staged_manifest, manifest_schema, data_schema)
        validation_seconds = time.perf_counter() - validation_started
        if errors:
            raise SystemExit("Staged release rejected: " + "; ".join(errors))

        os.replace(staged_parquet, final_parquet)
        os.replace(staged_manifest, final_manifest)

    final_errors = validate_release(final_parquet, final_manifest, manifest_schema, data_schema)
    if final_errors:
        raise SystemExit("Installed test release rejected: " + "; ".join(final_errors))
    leftovers = list(destination.parent.glob(".remote-pds-test-*"))
    elapsed = time.perf_counter() - started
    speed = parquet_bytes / 1048576 / parquet_seconds if parquet_seconds else 0.0
    print("REMOTE PDS FIRST-INSTALL TEST PASSED")
    print(f"- Manifest: {manifest_bytes:,} bytes in {manifest_seconds:.2f} s")
    print(f"- Parquet: {parquet_bytes:,} bytes in {parquet_seconds:.2f} s ({speed:.2f} MB/s)")
    print(f"- Staging validation: {validation_seconds:.2f} s")
    print(f"- Total including final validation: {elapsed:.2f} s")
    print(f"- Temporary leftovers: {len(leftovers)}")
    print(f"- Isolated installation: {destination}")
    print("- Runtime data/catalog was not modified")


if __name__ == "__main__":
    main()
