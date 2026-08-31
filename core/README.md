# `core/` (catalog builders and the download/process engine)

This folder is the shared, UI-independent backend: everything that talks to the PDS/RAW
Archive over HTTP, builds/maintains the local catalogs, and turns a catalog record into a
downloaded, EXIF-tagged JPG. It has no Streamlit dependency and is used by both `app/`
(MSL Downloader) and `catalog_manager/` (Make Catalog)'s background workers.

No files or folders needed reorganizing here (the flat layout was already clear); classes
were already well-named. This pass only added English module/function docstrings
throughout and translated the last few leftover Italian strings to English.

**`mastcam_bayer_cli.py` is off-limits — never modify it, for any reason.** It is the
Bayer-demosaic pipeline used by `engine_pipeline.py`'s Mastcam processing; treat it as a
frozen, external dependency.

## Catalog builders

- `make_msl_pds_catalog.py`: the unified, atomic PDS catalog builder/orchestrator — runs
  `make_msl_catalog.py` (standard cameras) and `make_msl_chemcam_catalog.py` (ChemCam RMI)
  as isolated sub-builders and merges their output atomically, so a crash never leaves the
  main catalog half-written.
- `make_msl_catalog.py`: the standard-camera (Mastcam/MAHLI/Navcam/MARDI/Hazcam) PDS
  scanner — discovery, LBL enrichment, rover-CSV geo lookup, incremental checkpointing.
  Also home to shared low-level helpers (`PDSClient`, `_extract_links_with_sizes`, JSON
  I/O, ...) reused by `make_msl_chemcam_catalog.py` and `make_msl_catalog_pre3000.py`.
- `make_msl_chemcam_catalog.py`: ChemCam RMI RDR discovery/build (its own TIF+LBL naming
  scheme, on a different PDS node than the standard cameras).
- `make_msl_catalog_pre3000.py`: the legacy pre-Sol-3000 PDS builder, with its own reduced
  camera selection rules; also the source of `_record_is_allowed`, reused by
  `make_msl_catalog.py`'s `camera_rules.json`-based filtering (imported late to avoid a
  circular import between the two modules).
- `make_msl_raw_catalog.py`: incremental MSL RAW Archive catalog updater (standard cameras).
- `make_msl_chemcam_raw_catalog.py`: incremental MSL RAW Archive catalog updater for
  ChemCam PRC images.

## Download/process engine

- `engine_pipeline.py`: the download-and-process engine — fetch IMG+LBL over HTTP, decode
  PDS image data, write EXIF/GPS-tagged JPGs, optionally apply the Mastcam Bayer pipeline.
  Entry points: `process_single_product` and `process_products_from_catalog`.
- `metashape_engine.py`: the pure-data half of the engine — LBL parsing, rover-CSV GPS
  matching, `.meta.json` construction. No I/O, no image decoding.
- `portable_engine_adapter.py`: bridges the app's catalog DataFrame world to
  `engine_pipeline`'s record/download world (DataFrame → records, concurrent downloads).
- `default_camera_meta.py`: hard-coded calibration fallbacks used when a product's LBL has
  no usable calibration fields.
- `mastcam_bayer_cli.py`: **off-limits, see above.**

## One-off maintenance / repair scripts

These are standalone CLI tools (argparse + `main()` + `__main__` guard) run manually to fix
or migrate existing catalog/output data — none of them are imported by the app or by
`catalog_manager/`'s workers, by design.

- `backfill_chemcam_fixed_exif.py`: add documented nominal ChemCam RMI optics to existing
  JPG/meta outputs.
- `backfill_chemcam_pds_output_metadata.py`: backfill ChemCam PDS output metadata from the
  official PDS catalog.
- `upgrade_chemcam_pds_output_metadata.py`: upgrade existing ChemCam PDS output metadata to
  the standard rich schema.
- `repair_chemcam_catalog_labels.py`: retry only ChemCam catalog records whose PDS label
  previously failed to parse.
- `merge_chemcam_pds_catalog.py`: merge the validated ChemCam PDS catalog into the
  application's PDS Parquet.
- `merge_chemcam_raw_catalog.py`: merge the validated ChemCam RAW catalog into the
  application's RAW Parquet.

## JSON ⟷ Parquet conversion

- `pds_json_rebuild.py`: regenerate `Catalog_PDS.json` from `Catalog_PDS.parquet` (parquet
  is authoritative; the JSON is a derived, streamable view Catalog Manager displays/exports).
- `raw_json_rebuild.py`: the same conversion, both directions, for `Catalog_RawArch`.

## Misc

- `catalog_runner.py`: runs the unified PDS builder as a subprocess and streams its stdout
  as events — used only by `app/utils/app_bootstrap.py`, an apparently-orphaned standalone
  diagnostic dashboard not launched by anything else in this repo (see that file's module
  docstring; left in place pending an explicit decision, not deleted unilaterally).

## Notes from this pass

- No dead code was found and removed in `core/` (unlike `app/`'s chat-era cruft): the
  "unreferenced" files above are legitimate one-off maintenance scripts, confirmed via
  `argparse`/`main()`/`__main__` entry points, not orphaned leftovers.
- All Python files were syntax-checked (`ast.parse`) and validated with
  `devtools/devtools/prepublish_smoke.py` after this pass.
