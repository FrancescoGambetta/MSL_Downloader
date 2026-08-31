# `catalog_manager/` (Catalog Manager — Streamlit application)

A separate Streamlit app ("Make Catalog") from MSL Downloader (`app/`), run on its own
port for maintaining the two local catalogs (`Catalog_PDS.parquet`/`.json` and
`Catalog_RawArch.parquet`/`.json`) that MSL Downloader reads from. Run with
`AVVIA_CATALOG_MANAGER_TEMP.bat` (project root) or `streamlit run app.py` from this
directory.

## Reorganization done in this pass

- New `workers/` subpackage, holding the 8 background-job worker scripts (previously
  flat in this folder) — see below.
- `job_worker.py` renamed to `workers/integrity_check_worker.py`: it's the read-only
  integrity-check worker for both PDS and RAW, but its old name broke the naming
  convention every other worker follows (named after its specific operation).
- No class renames — this codebase has exactly one class (`CatalogStatus` in
  `services.py`), already well-named.

## Main files

- `app.py` (2800+ lines): the Streamlit entrypoint — dashboard cards, integrity-check
  panels, JSON/official-release panels, product-composition breakdown, and the
  per-camera customization UIs. See its module docstring for the full picture.
- `jobs.py`: job orchestration — launches every background operation as a detached
  `workers/` subprocess and tracks its state as a JSON file under
  `data/catalog/jobs/{active,completed}/`.
- `services.py`: read-only catalog health/freshness inspection (local Parquet shape +
  optional remote-vs-local comparison) — the backend for the dashboard's status cards.
- `catalog_install.py`: atomic, validated install of a staged (JSON, Parquet) catalog
  pair into place, with automatic rollback on failure — used by every worker that
  produces a new catalog version.
- `customization.py`: per-camera product-type/processing-level (or camera-prefix/marker)
  compatibility data and selection-to-CLI-flag translation, shared by the customization
  UI and the customization/update workers.
- `distribution.py`: download and install pre-built catalog releases (an alternative to
  scanning PDS/RAW from scratch) — the first-run "Download & Install" flow.
- `product_composition.py`: read-only product-segment inventory (filename-code
  breakdown per camera) derived from the local Parquet catalogs.
- `bootstrap.py`: persists the user's first-run choice of whether to also generate the
  local JSON views, or download-only.
- `i18n_catalog.py`: translation strings added after the first UI pass, merged into
  `app.py`'s own `TEXT` dict at import time (Catalog Manager has its own i18n, separate
  from `app/i18n_app.json`).

## `workers/`

Background job workers, each a standalone CLI script launched by `jobs.py` as a detached
subprocess (`python -m catalog_manager.workers.<name> --job-id ...`), never imported
directly by the Streamlit app:

- `integrity_check_worker.py`: read-only PDS/RAW integrity check (discover remote,
  diff against local).
- `pds_update_worker.py` / `raw_update_worker.py`: scan and install a catalog update.
- `pds_repair_worker.py` / `raw_repair_worker.py`: re-scan and install just the
  locations an integrity check found missing.
- `customization_worker.py`: apply a per-camera product selection.
- `json_rebuild_worker.py`: regenerate one catalog's JSON view from its parquet, on
  demand.
- `bootstrap_worker.py`: the first-run counterpart of `json_rebuild_worker.py` — both
  catalogs' JSON in one pass, only for whichever is missing.

## Dead code removed in this pass

- `services.py`: `fetch_remote_latest_sol` — superseded by the per-camera
  `fetch_pds_remote_status`/`fetch_raw_remote_status`, confirmed unreferenced anywhere
  in the repo.
- `app.py`: an unused nested `joined_summary_badges` helper, and ~45 lines of hardcoded
  Italian labels/descriptions in `render_engineering_customization` that were being
  silently discarded (only the product codes were ever used; the real labels/help text
  come from `tr()`) — replaced with a plain code-only table.
- `catalog_install.py`: an unused `typing.Any` import.
- `workers/customization_worker.py`: an unused `CAMERA_OPTIONS` import.
- `workers/integrity_check_worker.py`: an unused `local_urls` local variable (the
  local/remote diff only ever compares by `product_id`, never by URL).

Found via `python -m pyflakes catalog_manager/*.py catalog_manager/workers/*.py`
(unused imports/locals) plus a grep-based reference count per public top-level function
(unused functions) — the same method used for `app/`'s and `core/`'s dead-code sweeps.

## Notes from this pass

- All Python files were syntax-checked (`ast.parse`), pyflakes-clean, and import-checked
  (every `catalog_manager.*` and `catalog_manager.workers.*` module imports cleanly).
- Two `__file__`-relative `ROOT` computations (`workers/bootstrap_worker.py`,
  `workers/json_rebuild_worker.py`) had to be fixed from `.parent.parent` to
  `.parent.parent.parent` after the move into `workers/`, or they would have resolved
  one directory too shallow (`catalog_manager/` instead of the project root).
- The last remaining Italian runtime strings (a couple of `_emit`-style progress
  messages, one error message) were translated to English for consistency with the rest
  of the documentation pass; the large `TEXT`/`EXTRA_TRANSLATIONS` dictionaries in
  `app.py`/`i18n_catalog.py` are legitimate UI translation data and were left untouched.
