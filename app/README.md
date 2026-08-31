# `app/` (MSL Downloader — Streamlit application)

This folder contains the Streamlit app entrypoint and the "stable facade" modules used by the UI.
Run with `Run_App.bat` (project root) or `streamlit run app.py` from this directory.

The app is builder/filters-only: pick a Sol range, cameras, source (PDS/RAW) and
size filters, then Download + Process + Organize. There is no free-text
chat/command mode anymore — that feature was removed; see `bulk_reply_parser.py`'s
module docstring for what's left of it (only the bulk-confirmation reply parsing).

## Main files

- `app.py`: Streamlit entrypoint (UI orchestration, `ui_main()`)
- `ui.py`: the login page, boot page helpers, and small HTML-rendering utilities
- `actions.py`: facade layer — plain functions that pull `session_state` and delegate to `services/*.py`
- `catalog.py`: catalog facade (camera_rules.json loading, filtering, dataframe cleanup)
- `runtime.py`: runtime config, session_state defaults, cached catalog/selection/output I/O
- `session.py`: per-user session lifecycle (login/resume/logout) + background catalog preload
- `bulk_reply_parser.py`: reply parsing for the bulk-download confirmation modal (procedi/annulla/number)
- `i18n_app.json`, `i18n_helper.py`: translations and i18n helpers

## Subfolders

- `services/`: business logic in smaller, testable units (avoid Streamlit when possible). Each
  `*_service.py` defines one `XxxService` class; `actions.py`/`catalog.py`/`runtime.py`/`session.py`
  hold a lazily-created singleton of each and expose plain functions that inject `session_state`
  into them — see any of those modules' docstrings for the pattern.
- `ui_panels/`: UI components/panels (rendering + input collection) — sidebar, viewport, metadata
  pane, live log, bulk-confirm modal, Configurations expander.
- `Styles/`: CSS generation (`css.py`) and theme color palettes (`themes.py`).
- `utils/`: small utilities — the native OS folder-picker dialog (`folder_dialog.py`), and a
  standalone diagnostic dashboard (`app_bootstrap.py`, not launched by anything in this repo —
  see its module docstring).
