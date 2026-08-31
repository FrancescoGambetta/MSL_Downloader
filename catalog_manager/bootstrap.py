"""First-run bootstrap choice: has the user asked Catalog Manager to (re)generate the
JSON views from the local Parquet catalogs, or to skip that and rely on downloaded
JSON only? Persisted once so the app doesn't ask again on every restart; the actual
generation work happens in `workers/bootstrap_worker.py`, launched via
`catalog_manager.jobs.start_bootstrap_json_job`.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def state_path(project_root: Path) -> Path:
    """Return the path to the bootstrap-choice state file."""
    return project_root / "data" / "catalog" / "catalog_manager_bootstrap.json"


def load_bootstrap_state(project_root: Path) -> dict[str, Any]:
    """Load the saved bootstrap choice, defaulting to `{"schema_version": 1, "json_choice": None}` if never set or unreadable."""
    path = state_path(project_root)
    if not path.exists():
        return {"schema_version": 1, "json_choice": None}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {"schema_version": 1, "json_choice": None}
    except Exception:
        return {"schema_version": 1, "json_choice": None}


def save_bootstrap_choice(project_root: Path, choice: str) -> dict[str, Any]:
    """Persist the user's bootstrap choice (`"generate"` or `"download_only"`) atomically (write to a temp file, then `os.replace`)."""
    if choice not in {"generate", "download_only"}:
        raise ValueError(f"Unsupported bootstrap choice: {choice}")
    path = state_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "json_choice": choice,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return payload
