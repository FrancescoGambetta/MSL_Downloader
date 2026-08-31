"""Reply parsing for the bulk-download confirmation modal.

This module used to be the full natural-language command parser behind an
in-app chat/AI feature. That feature was removed from the UI (the app is
builder/filters-only now, ``ui_mode`` is hard-locked to ``"builder"``), so
almost all of the original parsing logic became unreachable and was deleted.

What's left is only what the bulk-download confirmation reply still needs:
recognizing "procedi"/"annulla"/a number typed in reply to "you're about to
download N images" (see ``LocalCommandHandlerService.handle_local`` in
``services/local_command_handler_service.py`` and ``submit_command`` in
``actions.py``), plus the config loader that feeds it (``prompt_rules.json``)
and a couple of low-level text-normalization helpers shared with that flow.
"""

from __future__ import annotations

import copy
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Optional

import streamlit as st

from runtime import normalize_text

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _norm_ascii(text: str) -> str:
    """Lowercase/trim `text` and strip diacritics (accents), e.g. "annullà" -> "annulla".

    Used before running the cancel/proceed keyword matching so that accented
    or differently-cased replies still match.
    """
    txt = normalize_text(text)
    if not txt:
        return ""
    return unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode("ascii")


# Word -> integer lookup used to accept a typed-out number ("tre", "three",
# "trois"...) anywhere the bulk-reply flow expects a numeric limit, across
# the languages the UI supports (IT/EN/FR/ES/DE). German entries are already
# ASCII-normalized (e.g. "funf"/"fuenf" for "fünf") to match after
# `_norm_ascii` has stripped diacritics from the user's input.
_NUMBER_WORDS_MAP: dict[str, int] = {
    "zero": 0,
    # IT
    "uno": 1, "una": 1, "un": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5,
    "sei": 6, "sette": 7, "otto": 8, "nove": 9, "dieci": 10, "undici": 11, "dodici": 12,
    # EN
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    # FR
    "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "sept": 7,
    "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12,
    # ES
    "dos": 2, "cuatro": 4, "seis": 6, "siete": 7, "ocho": 8,
    "diez": 10, "once": 11, "doce": 12,
    # DE (ASCII normalized)
    "eins": 1, "eine": 1, "einen": 1, "zwei": 2, "drei": 3, "vier": 4, "funf": 5, "fuenf": 5,
    "sechs": 6, "sieben": 7, "acht": 8, "zehn": 10, "elf": 11, "zwolf": 12, "zwoelf": 12,
}


def _replace_written_numbers(text: str) -> str:
    """Replace every whole-word number written out in any supported language with digits."""
    out = text
    for word, num in _NUMBER_WORDS_MAP.items():
        out = re.sub(rf"\b{re.escape(word)}\b", str(num), out, flags=re.IGNORECASE)
    return out


def _deep_merge(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge `src` into `dst` (dict values merge; everything else is overwritten).

    Used to layer a user-editable JSON config (`prompt_rules.json`) on top of
    the built-in fallback defaults without requiring the JSON file to repeat
    every key.
    """
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            dst[k] = _deep_merge(dict(dst[k]), v)
        else:
            dst[k] = v
    return dst


# Built-in fallback used when config/parser_defaults.json is missing or
# invalid, so the bulk-reply flow always has something to work with even on
# a fresh checkout.
_PARSER_DEFAULTS_FALLBACK: dict[str, Any] = {
    "prompt_rules_defaults": {
        "normalize_replacements": [
            [r"\bdl\b", "download"],
            [r"\bproc\b", "process"],
            [r"\bdb\b", "database"],
            [r"\bstp\b", ""],
            [r"\bpls\b", ""],
            [r"\bplz\b", ""],
            [r"\btelecharge(?:r|ment)?\b", "download"],
            [r"\btelecharg\b", "download"],
            [r"\btraite(?:r|ment)?\b", "process"],
            [r"\bconvertis\b", "convert"],
            [r"\bconvertir\b", "convert"],
            [r"\bmontre\b", "show"],
            [r"\baffiche\b", "show"],
            [r"\bdossier\b", "folder"],
            [r"\bchemin\b", "path"],
            [r"\bliste\b", "list"],
            [r"\bselectionne(?:r)?\b", "seleziona"],
            [r"\bscarca\b", "scarica"],
            [r"\bscarcia\b", "scarica"],
            [r"\bproccessa\b", "processa"],
            [r"\bproccesa\b", "processa"],
            [r"\bproccess\b", "process"],
            [r"\bcam\b", "camera"],
        ],
        "compact_follow_tokens": ["navcam", "hazcam", "camera", "scarica", "download", "processa", "process", "converti", "convert", "kb", "mb", "gb"],
        "bulk_cancel_words": ["annulla", "cancel", "cancella", "stop", "abort", "abbrechen", "annuler", "cancelar", "arreter"],
        "bulk_proceed_words": ["procedi", "proceed", "continue", "continua", "ok", "go", "proceder", "procedez", "weiter", "fortfahren"],
    },
}


def _load_parser_defaults() -> dict[str, Any]:
    """Load config/parser_defaults.json, merged on top of the built-in fallback."""
    out = copy.deepcopy(_PARSER_DEFAULTS_FALLBACK)
    p = PROJECT_ROOT / "config" / "parser_defaults.json"
    if not p.exists():
        return out
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return _deep_merge(out, raw)
    except Exception:
        pass
    return out


_PARSER_DEFAULTS = _load_parser_defaults()
_PROMPT_RULES_DEFAULT: dict[str, Any] = dict(_PARSER_DEFAULTS.get("prompt_rules_defaults", _PARSER_DEFAULTS_FALLBACK["prompt_rules_defaults"]))


def _prompt_rules_path() -> Path:
    return PROJECT_ROOT / "config" / "prompt_rules.json"


@st.cache_data(show_spinner=False)
def _load_prompt_rules_cached(mtime: float) -> dict[str, Any]:
    """Read config/prompt_rules.json, cached and keyed on its mtime.

    The `mtime` argument (not `_mtime`) is what makes `st.cache_data` bust
    the cache whenever the file changes on disk -- see `load_prompt_rules`,
    which always passes the file's current mtime in.
    """
    out = dict(_PROMPT_RULES_DEFAULT)
    p = _prompt_rules_path()
    if not p.exists():
        return out
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return _deep_merge(out, raw)
    except Exception:
        pass
    return out


def load_prompt_rules() -> dict[str, Any]:
    """Return the effective prompt-rules config (defaults + prompt_rules.json overrides)."""
    p = _prompt_rules_path()
    try:
        mtime = float(p.stat().st_mtime) if p.exists() else 0.0
    except Exception:
        mtime = 0.0
    return _load_prompt_rules_cached(mtime)


def _pr_list(key: str, fallback: list[str]) -> list[str]:
    """Read a list-valued key from prompt_rules.json, falling back to `fallback` if absent/invalid."""
    rules = load_prompt_rules()
    vals = rules.get(key, fallback) if isinstance(rules, dict) else fallback
    if not isinstance(vals, list):
        return fallback
    return [str(x) for x in vals if normalize_text(x)]


def _contains_word(text: str, words: list[str]) -> bool:
    """True if any of `words` appears in `text` as a whole word (case-sensitive by caller's choice)."""
    for w in words:
        if re.search(rf"\b{re.escape(w)}\b", text):
            return True
    return False


def _parse_int(text: str, pattern: str) -> Optional[int]:
    """Extract the first regex capture group from `text` as an int, or None if not found/invalid."""
    m = re.search(pattern, text, re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _normalize_command_for_parser(text: str) -> str:
    """Normalize a raw bulk-reply string before keyword/number matching.

    Applies ASCII-folding, splits letters glued to digits ("5kb" -> "5 kb"),
    the configurable abbreviation/typo replacements from prompt_rules.json,
    written-number-to-digit conversion, and a couple of hardcoded typo fixes
    that predate the config file.
    """
    cmd = _norm_ascii(text)
    cmd = re.sub(r"([a-z])(\d)", r"\1 \2", cmd, flags=re.IGNORECASE)
    cmd = re.sub(r"(\d)([a-z])", r"\1 \2", cmd, flags=re.IGNORECASE)
    replacements_raw = load_prompt_rules().get("normalize_replacements", _PROMPT_RULES_DEFAULT["normalize_replacements"])
    replacements: list[tuple[str, str]] = []
    if isinstance(replacements_raw, list):
        for item in replacements_raw:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                replacements.append((str(item[0]), str(item[1])))
    if not replacements:
        replacements = [(str(a), str(b)) for a, b in _PROMPT_RULES_DEFAULT["normalize_replacements"]]
    out = cmd
    for pat, rep in replacements:
        out = re.sub(pat, rep, out)
    # Tolerate a few frequent human typos without changing intent semantics.
    out = re.sub(r"\bslezion(\w*)\b", r"selezion\1", out, flags=re.IGNORECASE)
    out = re.sub(r"\bproecss(\w*)\b", r"process\1", out, flags=re.IGNORECASE)
    out = re.sub(r"\bprocesa(\w*)\b", r"processa\1", out, flags=re.IGNORECASE)
    out = re.sub(r"\borganizare(\w*)\b", r"organizzare\1", out, flags=re.IGNORECASE)
    out = _replace_written_numbers(out)
    out = re.sub(r"\bsol(?=\d)", "sol ", out, flags=re.IGNORECASE)
    follow_tokens = _pr_list("compact_follow_tokens", _PROMPT_RULES_DEFAULT["compact_follow_tokens"])
    if follow_tokens:
        follow_re = "|".join(re.escape(tk) for tk in follow_tokens)
        out = re.sub(rf"(\d)(?=({follow_re})\b)", r"\1 ", out, flags=re.IGNORECASE)
    out = re.sub(r"\s+", " ", out).strip()
    return out


def _bulk_confirmation_text(total: int, *, action_type: str = "download_process") -> str:
    """Return the "you're about to download/process N images" prompt, in the active UI language."""
    action_label = "download/process"
    if normalize_text(action_type) == "download":
        action_label = "download"
    lang = normalize_text(st.session_state.get("lang", "it")).lower()
    if lang == "en":
        return (
            f"You are about to {action_label} {total} images.\n"
            "Reply with one of: Proceed | <number> | Cancel\n"
            "Example: 100"
        )
    if lang == "fr":
        return (
            f"Vous etes sur le point de telecharger/traiter {total} images.\n"
            "Repondez avec: Proceder | <nombre> | Annuler\n"
            "Exemple: 100"
        )
    if lang == "es":
        return (
            f"Estas a punto de descargar/procesar {total} imagenes.\n"
            "Responde con: Proceder | <numero> | Cancelar\n"
            "Ejemplo: 100"
        )
    if lang == "de":
        return (
            f"Du bist dabei, {total} Bilder herunterzuladen/zu verarbeiten.\n"
            "Antworte mit: Weiter | <Zahl> | Abbrechen\n"
            "Beispiel: 100"
        )
    return (
        f"Stai per {action_label} {total} immagini.\n"
        "Rispondi con: Procedi | <numero> | Annulla\n"
        "Esempio: 100"
    )


def _bulk_cancelled_text() -> str:
    """Return the "operation canceled" confirmation, in the active UI language."""
    lang = normalize_text(st.session_state.get("lang", "it")).lower()
    return {
        "en": "Operation canceled.",
        "fr": "Operation annulee.",
        "es": "Operacion cancelada.",
        "de": "Vorgang abgebrochen.",
    }.get(lang, "Operazione annullata.")


def _no_pending_bulk_text() -> str:
    """Return the "nothing to reply to" message, in the active UI language."""
    lang = normalize_text(st.session_state.get("lang", "it")).lower()
    return {
        "en": "No pending operation.",
        "fr": "Aucune operation en attente.",
        "es": "No hay ninguna operacion pendiente.",
        "de": "Kein ausstehender Vorgang.",
    }.get(lang, "Nessuna operazione in attesa.")


def _bulk_cancel_words() -> list[str]:
    """Words that count as "cancel" in a bulk-confirmation reply, from prompt_rules.json."""
    return _pr_list("bulk_cancel_words", _PROMPT_RULES_DEFAULT["bulk_cancel_words"])


def _bulk_proceed_words() -> list[str]:
    """Words that count as "proceed" in a bulk-confirmation reply, from prompt_rules.json."""
    return _pr_list("bulk_proceed_words", _PROMPT_RULES_DEFAULT["bulk_proceed_words"])
