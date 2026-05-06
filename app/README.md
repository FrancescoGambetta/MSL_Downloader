# `app/` (Streamlit application)

This folder contains the Streamlit app entrypoint and the “stable facade” modules used by the UI.

## Main files

- `app.py`: Streamlit entrypoint (UI orchestration)
- `ui.py`: UI helpers / composition glue
- `actions.py`: high-level actions triggered by user commands (download/process/update)
- `catalog.py`: catalog facade (load/filter/selection helpers)
- `runtime.py`: runtime/session_state initialization + shared helpers
- `session.py`: session/state handling utilities
- `parser.py`: command parsing (parser-first workflow)
- `i18n_app.json`, `i18n_helper.py`: translations and i18n helpers

## Subfolders

- `services/`: business logic in smaller, testable units (avoid Streamlit when possible)
- `ui_panels/`: UI components/panels (rendering + input collection)
- `Styles/`: CSS/themes
- `utils/`: small utilities (dialogs, bootstrap helpers, etc.)

