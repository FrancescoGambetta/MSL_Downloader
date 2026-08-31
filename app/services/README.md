# `app/services/` (application services)

Services implement the app's business logic (catalog ops, filtering, IO, download/process
orchestration, etc.), kept Streamlit-agnostic wherever possible so they're easier to reason about
and test in isolation.

Guideline used in this codebase:
- `ui_panels/*.py` do rendering and collect user input.
- `actions.py` / `catalog.py` / `runtime.py` / `session.py` are the facade layer: plain functions
  that pull whatever `st.session_state` a service needs and delegate to it. Each keeps a lazy
  singleton of its services in a module-level `_XXX_SERVICE` global, built by a `_get_xxx_service()`
  function on first use — see any of those four modules' docstrings for the concrete pattern.
- Services themselves take `state`/plain callables as explicit parameters instead of importing
  Streamlit or `session_state` directly, so they stay unit-testable on their own.

Every file here defines exactly one `XxxService` class (see each file's own docstring for what it
covers); grouped roughly by what they operate on:

**Catalog loading & filtering**
- `catalog_io_service.py` — parquet loading, derived columns (`_row_id`, `_suffix_code`, ...)
- `catalog_rules_service.py` — loads/compiles `camera_rules.json`
- `catalog_filter_service.py` — the core filter engine (Sol/camera/source/size/camera_rules)
- `catalog_apply_filters_service.py` — orchestrates "Apply filters" (PDS+RAW in parallel, dedup, cache)
- `catalog_dataframe_ops_service.py` — cross-source dedup, RAW burst-sequence reduction
- `catalog_selection_service.py` — PDS catalog boundary (max Sol, known-missing Sols), source routing

**Runtime/config/session**
- `runtime_paths_service.py` — resolves every configurable path, manages the download path + app_ui_config.json
- `runtime_selection_store_service.py` — persisted row-selection store (`cache/selected_rows.bin`)
- `runtime_output_index_service.py` — finds already-saved output files without repeated full scans
- `session_store_service.py` — per-user session history (`data/sessions/<user>.json`)
- `session_preload_service.py` — background catalog+intent-config preload at login
- `app_config_service.py` — persisted download-path management

**Action/selection preparation**
- `selection_service.py` — filter defaults/reset, resolves the effective selection DataFrame
- `action_dataframe_service.py` — builds the exact record set for an action, incl. min-size remote-size probing
- `text_utils_service.py`, `camera_naming_service.py` — small text-normalization / filename→camera helpers
- `record_output_utils_service.py` — per-record output-path helpers, skip-if-already-downloaded detection

**Download/process pipeline**
- `download_processing_service.py` — the three download/process workflows (`run_download`, `run_process`, `run_download_and_process_interleaved`) + timing diagnostics
- `image_processing_service.py` — camera-specific post-processing: MARDI dewarp/crop, Mastcam Bayer debayer, ChemCam TIFF→JPEG, RAW Archive EXIF/metadata
- `alpha_pair_service.py` — matches Navcam/Hazcam images to their MXYLF mask counterpart
- `output_organizer_service.py` — post-download folder organization (by camera / by Sol / combined)
- `output_size_enforcement_service.py` — deletes already-saved images under the configured minimum size

**Command handling & dispatch**
- `local_command_handler_service.py` — handles bulk-download-confirmation modal replies (the only "command" surface left after the chat/parser UI was removed)
