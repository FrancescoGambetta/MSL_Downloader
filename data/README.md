# `data/` (runtime data)

Data used by the app at runtime.

Subfolders:
- `catalog/`: runtime catalog parquet files (required to run the app if you bundle data)
- `reference/`: reference datasets (e.g. geo CSV/parquet)
- `sessions/`: local sessions (normally empty on publish; keep `.gitkeep` only)
- `catalog_json_rebuild/`: work area to rebuild large JSON catalogs without mixing with official runtime catalogs

