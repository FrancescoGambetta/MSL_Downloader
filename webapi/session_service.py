"""Bridge to app/services/session_store_service.py's per-user session JSON
files (`data/sessions/<NORMALIZED_NAME>.json`) for the new React frontend's
login screen. Reuses the exact same service the legacy Streamlit app used
for this (see `app/session.py`) instead of reimplementing it, so session
history stays in one place no matter which UI is running.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.session_store_service import SessionStoreService, _default_now_local, _default_now_utc  # noqa: E402
from runtime import normalize_text  # noqa: E402

_STORE = SessionStoreService(
    project_root=PROJECT_ROOT,
    normalize_text=normalize_text,
    now_local=_default_now_local,
    now_utc=_default_now_utc,
)


def login(display_name: str) -> dict[str, Any]:
    """Resume `display_name`'s most recent session, or start a new one if they have none yet."""
    user_norm = _STORE.normalize_user_name(display_name)
    if not user_norm:
        raise ValueError("empty name")
    user_norm, session_id = _STORE.resume_user_session(user_norm, display_name)
    return {"user_norm": user_norm, "session_id": session_id, "display_name": display_name}


def last_display_name() -> str:
    """The most recently logged-in user's display name across all session files, or "" if nobody has ever logged in -- lets the login screen pre-fill the name field."""
    sessions_dir = PROJECT_ROOT / "data" / "sessions"
    if not sessions_dir.exists():
        return ""
    latest_login = ""
    latest_name = ""
    for path in sessions_dir.glob("*.json"):
        data = _STORE.load_user_session_data(path.stem)
        login_at = str(data.get("last_login_at_utc") or "")
        if login_at > latest_login:
            latest_login = login_at
            latest_name = str(data.get("last_display_name") or "")
    return latest_name


def log_action(user_norm: str, session_id: str, event_type: str, payload: dict[str, Any] | None = None) -> None:
    _STORE.append_user_action(
        state={"current_user_norm": user_norm, "current_session_id": session_id},
        event_type=event_type,
        payload=payload,
    )


def logout(user_norm: str, session_id: str) -> None:
    _STORE.end_user_session(state={"current_user_norm": user_norm, "current_session_id": session_id})
