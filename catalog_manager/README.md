# `catalog_manager/` (Catalog Manager)

Builds and maintains the two local catalogs (`Catalog_PDS.parquet`/`.json` and
`Catalog_RawArch.parquet`/`.json`) that the rest of the app reads from, with
two sources: **PDS** and **RAW Archive**.

This package has no UI of its own: it is used through the main app, via the
React frontend's Catalog Manager tabs, which call
`webapi/catalog_manager_routes.py` and `webapi/catalog_manager_service.py`,
which wrap this package.

## Main files

- `jobs.py`: job orchestration — launches every background operation as a
  detached `workers/` subprocess and tracks its state as a JSON file under
  `data/catalog/jobs/{active,completed}/`.
- `services.py`: read only catalog health/freshness inspection (local Parquet
  shape + optional remote vs local comparison) — the backend for the
  dashboard's status cards.
- `catalog_install.py`: atomic, validated install of a staged (JSON, Parquet)
  catalog pair into place, with automatic rollback on failure — used by every
  worker that produces a new catalog version.
- `customization.py`: per camera product type/processing level (or camera
  prefix/marker) compatibility data and selection to CLI flag translation,
  shared by the customization UI and the customization/update workers.
- `distribution.py`: download and install pre built catalog releases (an
  alternative to scanning PDS/RAW from scratch) — the first run "Download and
  Install" flow.
- `product_composition.py`: read only product segment inventory (filename
  code breakdown per camera) derived from the local Parquet catalogs.
- `bootstrap.py`: persists the user's first run choice of whether to also
  generate the local JSON views, or download only.

## `workers/`

Background job workers, each a standalone CLI script launched by `jobs.py` as
a detached subprocess (`python -m catalog_manager.workers.<name> --job-id
...`), never imported directly:

- `integrity_check_worker.py`: read only PDS/RAW integrity check (discover
  remote, diff against local).
- `pds_update_worker.py` / `raw_update_worker.py`: scan and install a catalog
  update.
- `pds_repair_worker.py` / `raw_repair_worker.py`: re scan and install just
  the locations an integrity check found missing.
- `customization_worker.py`: apply a per camera product selection.
- `json_rebuild_worker.py`: regenerate one catalog's JSON view from its
  parquet, on demand.
- `bootstrap_worker.py`: the first run counterpart of `json_rebuild_worker.py`
  — both catalogs' JSON in one pass, only for whichever is missing.
