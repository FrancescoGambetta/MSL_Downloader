"""Small, dependency-free i18n loader for the app's flat `i18n_app.json` translation file."""

import json
import os
from functools import lru_cache


I18N_PATH = os.path.join(os.path.dirname(__file__), "i18n_app.json")
DEFAULT_LANG = "en"


@lru_cache(maxsize=8)
def _load_i18n_cached(path: str, mtime: float) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_i18n(path: str = I18N_PATH) -> dict:
    """Load and parse i18n_app.json, cached and re-read whenever its mtime changes."""
    # Same staleness class as the st.cache_data fixes elsewhere: lru_cache keyed
    # only on `path` never re-reads the file once cached, so editing
    # i18n_app.json while the app is running had no effect until restart.
    # Adding mtime to the key busts the cache when the file actually changes.
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        mtime = 0.0
    return _load_i18n_cached(path, mtime)


def language_options(i18n_data: dict) -> dict:
    """Return the `{code: display_name}` map declared under `_meta.languages` in i18n_app.json."""
    return i18n_data.get("_meta", {}).get("languages", {})


def translate(i18n_data: dict, lang: str, key: str, **kwargs) -> str:
    """Look up `key` in `lang`, falling back to DEFAULT_LANG ("en") and then to `key` itself if missing everywhere."""
    fallback = i18n_data.get(DEFAULT_LANG, {})
    text = i18n_data.get(lang, {}).get(key, fallback.get(key, key))
    return text.format(**kwargs) if kwargs else text
