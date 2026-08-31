from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

from validate_pds_release import validate_release


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate a safe PDS release installation from a local Drive-like folder.")
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "DRIVE DA SPOSTARE" / "PUBLIC_RELEASES" / "PDS" / "current",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=ROOT / "data" / "catalog_json_rebuild" / "install_simulation" / "data" / "catalog",
    )
    args = parser.parse_args()
    source = args.source.resolve()
    destination = args.destination.resolve()
    source_parquet = source / "Catalog_PDS.parquet"
    source_manifest = source / "Catalog_PDS.manifest.json"
    manifest_schema = ROOT / "config" / "pds_release_manifest_schema.json"
    data_schema = ROOT / "config" / "pds_catalog_schema.json"

    if not source_parquet.exists() or not source_manifest.exists():
        raise SystemExit(f"Incomplete source release: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pds-install-", dir=destination.parent) as temporary:
        staging = Path(temporary)
        staged_parquet = staging / source_parquet.name
        staged_manifest = staging / source_manifest.name
        shutil.copy2(source_parquet, staged_parquet)
        shutil.copy2(source_manifest, staged_manifest)
        errors = validate_release(staged_parquet, staged_manifest, manifest_schema, data_schema)
        if errors:
            print("Installation rejected before touching the destination:")
            for error in errors:
                print(f"- {error}")
            raise SystemExit(1)

        destination.mkdir(parents=True, exist_ok=True)
        installed_parquet = destination / source_parquet.name
        installed_manifest = destination / source_manifest.name
        shutil.copy2(staged_parquet, installed_parquet)
        shutil.copy2(staged_manifest, installed_manifest)

    final_errors = validate_release(installed_parquet, installed_manifest, manifest_schema, data_schema)
    if final_errors:
        raise SystemExit("Post-install validation unexpectedly failed: " + "; ".join(final_errors))
    print("PDS local installation simulation PASSED")
    print(f"- Source: {source}")
    print(f"- Installed copy: {destination}")
    print("- Runtime data/catalog was not modified")


if __name__ == "__main__":
    main()
