# `app/` (shared backend library)

This folder used to be the Streamlit "MSL Downloader" app. Its own UI
(`app.py`, `ui.py`, `ui_panels/`, `help.py`, `Guida.md`, `Styles/css.py`) has
been removed now that the React frontend (`frontend/`) replaced it. What is
left here is imported directly by `webapi/` as a library, not run on its own.

## Main files

- `actions.py`: facade layer used by `webapi/main.py` and
  `webapi/download_service.py` — plain functions that delegate to
  `services/*.py` (download/process pipeline, command/reply handling,
  catalog updates).
- `catalog.py`: catalog facade (camera_rules.json loading, filtering,
  dataframe cleanup), used directly by `webapi/catalog_service.py` too.
- `runtime.py`: runtime config, session defaults, cached catalog/selection/
  output I/O; used directly by `webapi/main.py`, `download_service.py` and
  `session_service.py`.
- `session.py`: per-session lifecycle and background catalog preload, still
  used by `actions.py`.
- `bulk_reply_parser.py`: reply parsing for the bulk-download confirmation
  flow (used by `services/local_command_handler_service.py`).
- `i18n_app.json`, `i18n_helper.py`: translation strings, read directly by
  `webapi/i18n_state.py` for backend/log messages.

## Subfolders

- `services/`: business logic in smaller units; each `*_service.py` defines
  one `XxxService` class, used both here and directly by `webapi/`.
- `Styles/themes.py`: theme name constants, still imported by `session.py`
  for its default theme values.
- `utils/folder_dialog.py`: native OS folder-picker dialog, used by
  `actions.py`.

Note: `actions.py`, `runtime.py`, `session.py` and `catalog.py` still
`import streamlit` at the top (left over from the Streamlit era). That is
why `streamlit` stays a real dependency in the project's `requirements.txt`
even though there is no Streamlit UI left in this repo.
