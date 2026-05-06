import json
import os
from functools import lru_cache


I18N_PATH = os.path.join(os.path.dirname(__file__), "i18n_app.json")
DEFAULT_LANG = "en"


@lru_cache(maxsize=1)
def load_i18n(path: str = I18N_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def language_options(i18n_data: dict) -> dict:
    return i18n_data.get("_meta", {}).get("languages", {})


def translate(i18n_data: dict, lang: str, key: str, **kwargs) -> str:
    fallback = i18n_data.get(DEFAULT_LANG, {})
    text = i18n_data.get(lang, {}).get(key, fallback.get(key, key))
    return text.format(**kwargs) if kwargs else text
