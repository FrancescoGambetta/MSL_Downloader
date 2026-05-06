# App structure (EN)

This document describes the structure of the Streamlit application under `app/`.

## Main entrypoint

- `app/app.py`: main user-facing Streamlit app (run this with Streamlit)

## UI

- `app/ui_panels/`: UI panels (sidebar, config panel, live log, viewport, metadata, modals)
- `app/ui.py`: shared UI helpers (small reusable blocks)
- `app/Styles/`: CSS + theme helpers
- `app/help.py`: in-app help overlay
- `app/i18n_app.json`, `app/i18n_helper.py`: UI translations

## Facade modules (stable internal API)

These modules are kept stable so refactors don't break imports/reruns:
- `app/actions.py`: user actions and operational flows (download/process/organize, command handling, catalog update)
- `app/catalog.py`: catalog facade (filters, analytics, selection helpers)
- `app/runtime.py`: runtime paths + persistence helpers + output indexing
- `app/session.py`: Streamlit session state, login/session handling, preload

## Services (business logic)

- `app/services/`: the bulk of the logic is implemented as focused service classes (catalog, runtime, download/process, session store/preload, etc.)

## Shared dependencies outside `app/`

The app relies on:
- `core/` (processing/engine pipeline)
- `config/` (runtime paths, intent config, catalog config, camera rules)
- `data/catalog/` (parquet catalogs)
- local-only runtime folders: `cache/` and `data/sessions/` (kept empty in the published repo)

## Run

From the project root:

```powershell
streamlit run .\\app\\app.py
```

