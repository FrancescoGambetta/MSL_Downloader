# Catalog data (`data/catalog/`)

This folder contains the *runtime* catalog artifacts used by the app.

- `Catalog_PDS.parquet`: main catalog (PDS-derived)
- `Catalog_RawArch.parquet`: optional RAW archive catalog (if present)

Notes:
- These files can be large. If you want a lighter distribution, regenerate/download them on demand instead of bundling them.
- The Streamlit runtime paths default to these locations unless overridden by `config/runtime_paths.json`.

