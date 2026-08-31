# PDS local distribution simulation

The local folder `DRIVE DA SPOSTARE/PUBLIC_RELEASES/PDS/current` simulates the future public Google Drive release. It contains the stable filenames `Catalog_PDS.parquet` and `Catalog_PDS.manifest.json`.

The simulation copies both files into a temporary staging directory, validates the staged release, installs it into an isolated test destination, and validates the installed copy again. It never writes to runtime `data/catalog`.

Run with the project Conda environment:

```powershell
C:\Users\franc\anaconda3\envs\dwnapp\python.exe devtools\simulate_pds_catalog_install.py
```

Default isolated destination:

```text
data/catalog_json_rebuild/install_simulation/data/catalog/
```

When the Drive URLs exist, the staging and validation phases stay unchanged. Only the source-copy phase will be replaced by an HTTP/Drive download.

## Real remote test — 2026-07-28

The public Google Drive release was downloaded into an isolated first-install destination:

- manifest: 5,217 bytes in 1.13 seconds;
- Parquet: 23,158,625 bytes in 3.01 seconds (7.33 MB/s);
- staging validation: 6.42 seconds;
- total including final validation: 16.16 seconds;
- temporary leftovers: zero;
- runtime `data/catalog` changes: none.

## Failure tests

`devtools/test_pds_distribution_failures.py` verifies that:

- an altered manifest is rejected;
- a corrupted Parquet is rejected by SHA-256;
- an interrupted download cannot replace the installed catalog;
- the previously installed catalog remains byte-for-byte intact;
- temporary staging directories are removed after failure.

All five tests pass.

## Local JSON reconstruction

The installed official Parquet successfully generated `data/catalog/Catalog_PDS.json` in a detached background job:

- 387,276 products;
- 431,034,871 bytes (411.1 MiB);
- 35.84 seconds;
- camera counts match the Parquet;
- every `img_url` is unique;
- the JSON and Parquet URL sets are identical.

The first attempted job exposed a transient Windows file-lock conflict while Streamlit read the job state. State writes now use unique temporary files and retry atomic replacement on `PermissionError`. The failed attempt left no partial catalog.
