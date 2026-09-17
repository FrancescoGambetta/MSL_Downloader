# App structure (EN)

This document maps the project's folders. The supported way to run the app
is the React frontend talking to the FastAPI backend; an earlier Streamlit
interface still exists and is described where relevant below.

## Entry points

- `launchers/Avvia_MSL_App.bat` (Windows) / `.sh` (Linux/macOS, BETA): starts
  the backend (port 8000) and the frontend dev server (port 5173).
- Legacy: `streamlit run app/app.py` (MSL Downloader UI),
  `streamlit run catalog_manager/app.py` (Catalog Manager UI).

## `webapi/` (backend, FastAPI)

- `main.py`: app instance, CORS, `/api/health`, catalog search, download job
  endpoints (start/status/cancel), file and metadata serving.
- `download_service.py`: runs download/process jobs in a background thread,
  reusing `app/actions.py`'s pipeline functions directly (PDS decode, RAW
  Bayer demosaic, MARDI correction, ChemCam handling, output organization).
  In-memory job registry, no persistence across restarts.
- `catalog_service.py`: read only catalog search over the local PDS/RAW
  parquet catalogs.
- `catalog_manager_routes.py` / `catalog_manager_service.py`: wrap
  `catalog_manager/` (see below) for the frontend's Catalog Manager tabs.
- `session_routes.py` / `session_service.py`: login/session endpoints.
- `i18n_state.py`: per request thread language state, so job log messages
  come back translated.

## `frontend/` (UI, React + Vite + Tailwind)

See `frontend/AGENTS.md` for the file by file map. In short:
`src/pages/Home.jsx` (downloader), `src/pages/CatalogManager.jsx` (catalog
tabs), `src/lib/mslApi.js` / `catalogManagerApi.js` / `sessionApi.js`
(backend clients).

## `app/` (shared engine/session library)

Originally the Streamlit "MSL Downloader" app; its facade and service
modules are now also imported directly by `webapi/main.py` and
`download_service.py`, so this is not dead code even though its own UI is
legacy.

- `actions.py`, `catalog.py`, `runtime.py`, `session.py`: stable facade
  modules (download/process flows, catalog filters, runtime paths/output
  indexing, session state).
- `services/`: the underlying business logic (catalog, download/process,
  session store/preload, etc.).
- `ui.py`, `ui_panels/`, `Styles/`, `help.py`, `i18n_app.json`/
  `i18n_helper.py`: Streamlit only UI, used only by the legacy `app.py`
  interface (the backend imports `runtime`/`actions`, never these).

## `core/` (processing/engine pipeline)

Camera specific catalog builders (`make_msl_catalog.py`,
`make_msl_raw_catalog.py`, `make_msl_chemcam_*`,
`make_msl_catalog_pre3000.py`), the image decode/processing engine
(`engine_pipeline.py`, `portable_engine_adapter.py`), Metashape integration
(`metashape_engine.py`). Used by both `app/` and
`webapi/download_service.py`.

## `catalog_manager/` (catalog build/maintain orchestration)

See `catalog_manager/README.md`. Its `jobs.py`/`services.py`/`workers/` are
used both by its own legacy Streamlit UI (`app.py`) and by
`webapi/catalog_manager_routes.py` for the frontend's Catalog Manager tabs.
Background jobs here run as detached OS subprocesses with JSON state on disk
(`data/catalog/jobs/`), unlike `webapi/download_service.py`'s in process
background threads.

## Other folders

- `config/`: JSON configuration (runtime paths, catalog build config,
  camera rules, intent/parsing rules). See `config/README.md`.
- `data/`: local catalogs (parquet/JSON) and job state; not versioned in git
  (see `.gitignore`).
- `devtools/`: developer tools, including the pre publish smoke test
  (currently checks `core/` and the legacy `app/` only).
- `tests/`: Python tests.
- `docs/`: this documentation package.
