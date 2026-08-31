"""FastAPI routes for the new React login screen, mounted under /api/session/
by webapi/main.py. Thin HTTP layer over session_service.py, mirroring
webapi/catalog_manager_routes.py's own approach.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from webapi import session_service as ss

router = APIRouter(prefix="/api/session", tags=["session"])


class LoginRequest(BaseModel):
    name: str


@router.post("/login")
def login(payload: LoginRequest) -> dict[str, Any]:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    return ss.login(name)


@router.get("/last-name")
def last_name() -> dict[str, str]:
    """The last person who logged in, anywhere -- pre-fills the login screen's name field."""
    return {"display_name": ss.last_display_name()}


class ActionRequest(BaseModel):
    user_norm: str
    session_id: str
    type: str
    payload: Optional[dict[str, Any]] = None


@router.post("/action")
def action(payload: ActionRequest) -> dict[str, str]:
    ss.log_action(payload.user_norm, payload.session_id, payload.type, payload.payload)
    return {"status": "ok"}


class LogoutRequest(BaseModel):
    user_norm: str
    session_id: str


@router.post("/logout")
def logout(payload: LogoutRequest) -> dict[str, str]:
    ss.logout(payload.user_norm, payload.session_id)
    return {"status": "ok"}
