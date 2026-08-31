from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from catalog_manager.distribution import install_remote_pds_release  # noqa: E402
from devtools.validate_pds_release import validate_release  # noqa: E402


TEST_ROOT = ROOT / "data" / "catalog_json_rebuild" / "distribution_failure_tests"
SOURCE_PARQUET = ROOT / "data" / "catalog" / "Catalog_PDS.parquet"
SOURCE_MANIFEST = ROOT / "data" / "catalog" / "Catalog_PDS.manifest.json"
MANIFEST_SCHEMA = ROOT / "config" / "pds_release_manifest_schema.json"
DATA_SCHEMA = ROOT / "config" / "pds_catalog_schema.json"


def main() -> None:
    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    results: list[tuple[str, bool, str]] = []

    with tempfile.TemporaryDirectory(prefix="pds-failure-tests-", dir=TEST_ROOT) as temporary:
        work = Path(temporary)

        bad_manifest = work / "bad.manifest.json"
        altered = json.loads(json.dumps(manifest))
        altered["parquet"]["row_count"] += 1
        bad_manifest.write_text(json.dumps(altered), encoding="utf-8")
        errors = validate_release(SOURCE_PARQUET, bad_manifest, MANIFEST_SCHEMA, DATA_SCHEMA)
        results.append(("altered manifest rejected", bool(errors), errors[0] if errors else "unexpected pass"))

        bad_parquet = work / "Catalog_PDS.parquet"
        shutil.copy2(SOURCE_PARQUET, bad_parquet)
        with bad_parquet.open("r+b") as stream:
            stream.seek(-1, 2)
            final_byte = stream.read(1)
            stream.seek(-1, 2)
            stream.write(bytes([final_byte[0] ^ 0x01]))
        errors = validate_release(bad_parquet, SOURCE_MANIFEST, MANIFEST_SCHEMA, DATA_SCHEMA)
        results.append(("corrupted Parquet rejected", bool(errors), errors[0] if errors else "unexpected pass"))

        target = work / "preserved_install" / "data" / "catalog"
        target.mkdir(parents=True)
        installed = target / "Catalog_PDS.parquet"
        sentinel = b"existing-catalog-must-survive"
        installed.write_bytes(sentinel)

        def interrupted_download(_url: str, destination: Path, _progress, **_kwargs) -> None:
            destination.write_bytes(b"partial-download")
            raise ConnectionError("simulated connection interruption")

        rejected = False
        try:
            install_remote_pds_release(
                ROOT,
                target_dir=target,
                _remote_manifest=manifest,
                _download_impl=interrupted_download,
            )
        except ConnectionError:
            rejected = True
        preserved = installed.read_bytes() == sentinel
        leftovers = list(target.glob(".pds-release-*"))
        results.append(("interrupted download rejected", rejected, "expected ConnectionError"))
        results.append(("existing catalog preserved", preserved, f"bytes={installed.read_bytes()!r}"))
        results.append(("temporary staging cleaned", not leftovers, f"leftovers={leftovers}"))

    for name, passed, detail in results:
        print(f"{'PASS' if passed else 'FAIL'} - {name}: {detail}")
    failures = [name for name, passed, _detail in results if not passed]
    if failures:
        raise SystemExit("PDS distribution failure tests failed: " + ", ".join(failures))
    print(f"ALL PDS DISTRIBUTION FAILURE TESTS PASSED ({len(results)}/{len(results)})")


if __name__ == "__main__":
    main()
