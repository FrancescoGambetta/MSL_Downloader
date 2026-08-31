"""Per-thread current language for webapi log/translated messages.

Each download job runs in its own background thread (`download_service._run_job`);
the frontend tells us which UI language the user has selected when it starts a job
(`DownloadStartRequest.lang`), and this thread-local lets every message that thread
produces -- both this module's own `t()` calls and `app/actions.py`'s injected
translator (see `main.py::app_actions.set_translator`) -- come back in the right
language, without threading `lang` through every single function call.

Falls back to Italian for any request path that never calls `set_current_lang`
(e.g. catalog search, which has no per-job thread of its own).
"""

from __future__ import annotations

import threading
from pathlib import Path

from i18n_helper import load_i18n, translate

_APP_DIR = Path(__file__).resolve().parent.parent / "app"
_I18N = load_i18n(str(_APP_DIR / "i18n_app.json"))
_local = threading.local()


def set_current_lang(lang: str) -> None:
    _local.lang = lang if lang in _I18N else "it"


def get_current_lang() -> str:
    return getattr(_local, "lang", "it")


def t(key: str, **kwargs) -> str:
    try:
        return translate(_I18N, get_current_lang(), key, **kwargs)
    except Exception:  # noqa: BLE001
        return key.format(**kwargs) if kwargs else key
