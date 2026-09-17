# `devtools/` (developer tools)

Helper scripts used during development and pre-publish checks for MSL Downloader. None of these run automatically; call them by hand as needed.

- `prepublish_smoke.py`: compiles `app/` and `core/`, validates JSON config, checks that the core Python modules still import and that camera rules compile.
  ```bash
  python devtools/prepublish_smoke.py --skip-catalog
  ```
- Catalog maintenance/inspection one-offs: `audit_*.py`, `build_*.py`, `census_*.py`, `download_*.py`, `export_*.py`, `fill_*.py`, `repair_*.py`, `retry_and_classify_*.py`, `simulate_*.py`, `test_*.py`, `validate_*.py`, `write_*.py`, `compare_legacy_downloaders.py`, `canonicalize_pds_product_previews.py`. Each is a standalone script for a specific catalog task (building filtered catalogs, auditing PDS/RAW round trips, backfilling previews, validating a release manifest, etc.); read its own docstring/`--help` before running it.
- `tools/`: standalone scripts unrelated to catalog maintenance (EXIF helpers, PDS3 IMG to PNG decoding).

If you publish this project, make sure the documentation matches what you actually ship.
