from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional


class SessionStoreService:
    def __init__(
        self,
        *,
        project_root: Path,
        normalize_text: Callable[[Any], str],
        now_local: Callable[[], datetime],
        now_utc: Callable[[], datetime],
    ) -> None:
        self._project_root = project_root
        self._normalize_text = normalize_text
        self._now_local = now_local
        self._now_utc = now_utc

    def sessions_root(self) -> str:
        return str(self._project_root / "data" / "sessions")

    def normalize_user_name(self, name: str) -> str:
        raw = self._normalize_text(name)
        if not raw:
            return ""
        cleaned = re.sub(r"\\s+", " ", raw).strip()
        return cleaned.upper()

    def user_session_path(self, user_norm: str) -> Path:
        safe = re.sub(r"[^A-Z0-9_ -]", "_", user_norm).strip().replace(" ", "_")
        safe = safe or "USER"
        return Path(self._project_root / "data" / "sessions" / f"{safe}.json")

    def load_user_session_data(self, user_norm: str) -> dict[str, Any]:
        p = self.user_session_path(user_norm)
        if not p.exists():
            return {}
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}

    def save_user_session_data(self, user_norm: str, data: dict[str, Any]) -> None:
        p = self.user_session_path(user_norm)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def now_local_iso(self) -> str:
        return self._now_local().isoformat(timespec="seconds")

    def now_utc_iso(self) -> str:
        return self._now_utc().isoformat(timespec="seconds")

    def start_user_session(self, display_name: str) -> tuple[str, str]:
        user_norm = self.normalize_user_name(display_name)
        now = self.now_local_iso()
        now_utc = self.now_utc_iso()
        user_data = self.load_user_session_data(user_norm)
        sessions = user_data.get("sessions", []) if isinstance(user_data.get("sessions"), list) else []
        session_id = f"{self._now_local().strftime('%Y%m%d-%H%M%S')}"

        session_obj = {
            "session_id": session_id,
            "started_at": now,
            "started_at_utc": now_utc,
            "ended_at": None,
            "actions": [],
        }
        sessions.append(session_obj)
        user_data["user_norm"] = user_norm
        user_data["last_display_name"] = self._normalize_text(display_name) or user_norm
        user_data["last_login_at"] = now
        user_data["last_login_at_utc"] = now_utc
        user_data["sessions"] = sessions
        self.save_user_session_data(user_norm, user_data)
        return user_norm, session_id

    def get_latest_session_info(self, user_norm: str) -> Optional[dict[str, Any]]:
        data = self.load_user_session_data(user_norm)
        sessions = data.get("sessions", []) if isinstance(data.get("sessions"), list) else []
        if not sessions:
            return None
        last = sessions[-1]
        if not isinstance(last, dict):
            return None
        return {
            "session_id": self._normalize_text(last.get("session_id")),
            "started_at": self._normalize_text(last.get("started_at")),
            "ended_at": self._normalize_text(last.get("ended_at")),
            "last_display_name": self._normalize_text(data.get("last_display_name")) or user_norm,
        }

    def resume_user_session(self, user_norm: str, display_name: str) -> tuple[str, str]:
        data = self.load_user_session_data(user_norm)
        sessions = data.get("sessions", []) if isinstance(data.get("sessions"), list) else []
        if not sessions:
            return self.start_user_session(display_name)
        now = self.now_local_iso()
        now_utc = self.now_utc_iso()
        target = sessions[-1] if isinstance(sessions[-1], dict) else {}
        session_id = self._normalize_text(target.get("session_id")) or f"{self._now_local().strftime('%Y%m%d-%H%M%S')}"
        target["session_id"] = session_id
        target["last_active_at"] = now
        target["last_active_at_utc"] = now_utc
        target["resumed_at"] = now
        target["resumed_at_utc"] = now_utc
        target["ended_at"] = None
        target["ended_at_utc"] = None
        sessions[-1] = target
        data["sessions"] = sessions
        data["user_norm"] = user_norm
        data["last_display_name"] = self._normalize_text(display_name) or user_norm
        data["last_login_at"] = now
        data["last_login_at_utc"] = now_utc
        self.save_user_session_data(user_norm, data)
        return user_norm, session_id

    def append_user_action(
        self,
        *,
        state: dict[str, Any],
        event_type: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> None:
        user_norm = self._normalize_text(state.get("current_user_norm"))
        session_id = self._normalize_text(state.get("current_session_id"))
        if not user_norm or not session_id:
            return
        data = self.load_user_session_data(user_norm)
        sessions = data.get("sessions", []) if isinstance(data.get("sessions"), list) else []
        now = self.now_local_iso()
        now_utc = self.now_utc_iso()
        for session_obj in reversed(sessions):
            if not isinstance(session_obj, dict):
                continue
            if self._normalize_text(session_obj.get("session_id")) == session_id:
                actions = session_obj.get("actions", []) if isinstance(session_obj.get("actions"), list) else []
                actions.append(
                    {
                        "timestamp": now,
                        "timestamp_utc": now_utc,
                        "type": self._normalize_text(event_type),
                        "payload": payload or {},
                    }
                )
                session_obj["actions"] = actions
                session_obj["last_active_at"] = now
                session_obj["last_active_at_utc"] = now_utc
                break
        data["sessions"] = sessions
        self.save_user_session_data(user_norm, data)

    def end_user_session(self, *, state: dict[str, Any]) -> None:
        user_norm = self._normalize_text(state.get("current_user_norm"))
        session_id = self._normalize_text(state.get("current_session_id"))
        if not user_norm or not session_id:
            return
        data = self.load_user_session_data(user_norm)
        sessions = data.get("sessions", []) if isinstance(data.get("sessions"), list) else []
        now = self.now_local_iso()
        now_utc = self.now_utc_iso()
        for session_obj in reversed(sessions):
            if not isinstance(session_obj, dict):
                continue
            if self._normalize_text(session_obj.get("session_id")) == session_id:
                session_obj["ended_at"] = now
                session_obj["ended_at_utc"] = now_utc
                session_obj["last_active_at"] = now
                session_obj["last_active_at_utc"] = now_utc
                break
        data["sessions"] = sessions
        self.save_user_session_data(user_norm, data)


def _default_now_local() -> datetime:
    return datetime.now()


def _default_now_utc() -> datetime:
    return datetime.now(timezone.utc)
