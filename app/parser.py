from __future__ import annotations

import copy
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Callable, Optional

import streamlit as st

from runtime import load_json, normalize_text, _resolve_intent_config


PROJECT_ROOT = Path(__file__).resolve().parent.parent

_T: Callable[..., str] = lambda key, **kwargs: key.format(**kwargs) if kwargs else key


def _norm_ascii(text: str) -> str:
    txt = normalize_text(text)
    if not txt:
        return ""
    return unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode("ascii")


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
    out = text
    for word, num in _NUMBER_WORDS_MAP.items():
        out = re.sub(rf"\b{re.escape(word)}\b", str(num), out, flags=re.IGNORECASE)
    return out


def set_translator(fn: Callable[..., str]) -> None:
    global _T
    _T = fn


def t(key: str, **kwargs: Any) -> str:
    try:
        return _T(key, **kwargs)
    except Exception:
        return key.format(**kwargs) if kwargs else key


def _cfg_keywords(group: str) -> list[str]:
    cfg = st.session_state.get("intent_cfg", {})
    vals = cfg.get("keywords", {}).get(group, []) if isinstance(cfg, dict) else []
    return [normalize_text(x).lower() for x in vals if normalize_text(x)]


def _deep_merge(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            dst[k] = _deep_merge(dict(dst[k]), v)
        else:
            dst[k] = v
    return dst


_PARSER_DEFAULTS_FALLBACK: dict[str, Any] = {
    "prompt_rules_defaults": {
        "requested_count_patterns": [
            r"\b(?:scarica|download|processa|process|converti|convert|organizza|organize)\s+(?:solo|only\s+)?(\d{1,6})\b",
            r"\b(\d{1,6})\s*(?:immagini|images|image|foto|photos)\b",
            r"\b(\d{1,6})\s*(?:totali|totale|total|overall|au total|en total)\b",
            r"\b(?:totali|totale|total|overall|au total|en total)\s*[:=]?\s*(\d{1,6})\b",
            r"\bmax(?:imum)?\s*[:=]?\s*(\d{1,6})\b",
            r"\b(\d{1,6})\s*(?:random|casuali|aleatoire|aleatoires|aleatorias|zufallig|zufallige)\b",
        ],
        "each_camera_count_patterns": [
            r"\b(\d{1,4})\s*(?:immagini|images|image|foto|photos)?\s*(?:per|for|pour|por|pro)\s*(?:ogni|each|chaque|cada|jede)\s*(?:camera|cameras|camere|camara|kameras?)\b",
            r"\b(?:per|for|pour|por|pro)\s*(?:ogni|each|chaque|cada|jede)\s*(?:camera|cameras|camere|camara|kameras?)\s*(\d{1,4})\b",
        ],
        "random_words": ["random", "casuali", "casuale", "aleatoire", "aleatorias", "zufallig", "zufallige"],
        "organize_words": ["organize", "organizza", "organiser", "organizar", "organisieren"],
        "workflow_action_patterns": [
            r"\bscaric\w*\b",
            r"\bdownload\w*\b",
            r"\bprocess\w*\b",
            r"\bconvert\w*\b",
            r"\borgani(?:zz|s)\w*\b",
            r"\brandom\b",
            r"\bcasual\w*\b",
            r"\bsol\b",
            r"\b\d+\s*(?:kb|mb|gb)\b",
            r"\bselezion\w*\b",
            r"\bselect\w*\b",
        ],
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
        "all_cameras_patterns": [
            r"\b(?:tutte|tutti|tutto)\s+le?\s*camera(?:s)?\b",
            r"\ball\s+(?:the\s+)?camera(?:s)?\b",
            r"\btoutes?\s+les?\s+camera(?:s)?\b",
            r"\btodas?\s+las?\s+camara(?:s)?\b",
            r"\balle\s+kameras?\b",
        ],
        "unsupported_url_tokens": ["image url", "image urls", "url immagini", "url delle immagini", "urls for images", "urls of images"],
        "unsupported_url_listing_verbs": ["show", "list", "mostra", "elenca", "dammi"],
        "camera_list_camera_words": ["camera", "cameras", "camere", "camara", "camaras", "kamera", "kameras", "instrument", "instruments"],
        "camera_list_list_words": ["list", "lista", "elenco", "show", "mostra", "display", "which", "quali", "what", "dammi", "fammi"],
        "camera_list_action_words": ["scaric", "download", "process", "convert", "organizz", "organize", "selezion", "select", "random", "casual", "sol", "kb", "mb"],
        "bulk_cancel_words": ["annulla", "cancel", "cancella", "stop", "abort", "abbrechen", "annuler", "cancelar", "arreter"],
        "bulk_proceed_words": ["procedi", "proceed", "continue", "continua", "ok", "go", "proceder", "procedez", "weiter", "fortfahren"],
    },
    "camera_rules_defaults": {
        "mastcam": {"filter_key": "mastcam_only_drcl", "suffix_equals_any": ["DRCL"]},
        "mahli": {"filter_key": "mahli_only_drcl", "suffix_equals_any": ["DRCL"]},
        "mardi": {"filter_key": "mardi_only_e01_drcx", "suffix_equals_any": ["DRCL"], "filename_contains_any": ["E01_", "E00_", "C00_"]},
        "navcam": {"filter_key": "navcam_only_iltlf", "filename_prefix_any": ["NLB_", "NRB_"], "filename_contains_all": ["ILTLF"], "camera_markers_any": ["NCAM"]},
        "hazcam": {"filter_key": "hazcam_only_lb_edr", "filename_prefix_any": ["FLB_", "RLB_"], "filename_contains_all": ["ILT_F"], "camera_markers_any": ["FHAZ", "RHAZ"]},
    },
}


def _load_parser_defaults() -> dict[str, Any]:
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
_CAMERA_RULES_DEFAULT: dict[str, Any] = dict(_PARSER_DEFAULTS.get("camera_rules_defaults", _PARSER_DEFAULTS_FALLBACK["camera_rules_defaults"]))


def _prompt_rules_path() -> Path:
    return PROJECT_ROOT / "config" / "prompt_rules.json"


@st.cache_data(show_spinner=False)
def load_prompt_rules() -> dict[str, Any]:
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


def _pr_list(key: str, fallback: list[str]) -> list[str]:
    rules = load_prompt_rules()
    vals = rules.get(key, fallback) if isinstance(rules, dict) else fallback
    if not isinstance(vals, list):
        return fallback
    return [str(x) for x in vals if normalize_text(x)]


def _intent_match(intent_id: str, cmd: str) -> bool:
    cfg = st.session_state.get("intent_cfg", {})
    rule = cfg.get("intents", {}).get(intent_id, {}) if isinstance(cfg, dict) else {}
    if not isinstance(rule, dict):
        return False
    cmd_low = _norm_ascii(cmd)

    def _tok(s: str) -> list[str]:
        out = re.findall(r"[a-z0-9]+", _norm_ascii(s))
        return [t for t in out if t]

    def _stem(t: str) -> str:
        for suf in ("mente", "zione", "zioni", "ing", "ed", "es", "s", "i", "e"):
            if len(t) > 4 and t.endswith(suf):
                return t[: -len(suf)]
        return t

    cmd_tokens = _tok(cmd_low)
    cmd_stems = {_stem(t) for t in cmd_tokens}

    def _phrase_match(phrase: str) -> bool:
        p = _norm_ascii(phrase)
        if not p:
            return False
        if p in cmd_low:
            return True
        pt = _tok(p)
        if not pt:
            return False
        pstems = {_stem(t) for t in pt}
        return pstems.issubset(cmd_stems)

    contains = [normalize_text(x).lower() for x in rule.get("contains", []) if normalize_text(x)]
    if contains and not any(_phrase_match(x) for x in contains):
        return False
    contains_any = [normalize_text(x).lower() for x in rule.get("contains_any", []) if normalize_text(x)]
    if contains_any and not any(_phrase_match(x) for x in contains_any):
        return False
    requires_any = [normalize_text(x).lower() for x in rule.get("requires_any", []) if normalize_text(x)]
    if requires_any and not any(_phrase_match(x) for x in requires_any):
        return False
    requires_all_any = rule.get("requires_all_any", [])
    if isinstance(requires_all_any, list) and requires_all_any:
        for group in requires_all_any:
            if not isinstance(group, list) or not group:
                return False
            alts = [normalize_text(x).lower() for x in group if normalize_text(x)]
            if not alts or not any(_phrase_match(x) for x in alts):
                return False
    return bool(contains or contains_any or requires_any)


def _parse_sol_range(text: str) -> tuple[Optional[int], Optional[int]]:
    t = _norm_ascii(text)
    separators = r"(?:a|al|to|au|hasta|bis|fino(?:\s+a|al)?|until|till|through|thru|jusqu'?a|ifno|fno|\-|–|—|/|\.\.)"
    separators_with_and = rf"(?:{separators}|(?:e|and|et|y)(?:\s+(?:il|lo|la|l|the|el|le))?)"
    patterns = [
        rf"\b(?:da|dal|from|de|del|between|tra|entre)?\s*sol(?:\s*range)?\s*(\d{{1,5}})\s*{separators_with_and}\s*(?:sol\s*)?(\d{{1,5}})\b",
        rf"\bsol\s*(\d{{1,5}})\s*{separators_with_and}\s*(?:sol\s*)?(\d{{1,5}})\b",
    ]
    for pat in patterns:
        m = re.search(pat, t, re.IGNORECASE)
        if m:
            return int(m.group(1)), int(m.group(2))
    m2 = re.search(r"\bsol\s*(\d{1,5})(?=\D|$)", text, re.IGNORECASE)
    if m2:
        v = int(m2.group(1))
        return v, v
    return None, None


def _split_multi_range_blocks(text: str) -> list[str]:
    cmd = _normalize_command_for_parser(text)
    separators = r"(?:a|al|to|au|hasta|bis|fino(?:\s+a|al)?|until|till|through|thru|jusqu'?a|ifno|fno|\-|–|—|/|\.\.)"
    separators_with_and = rf"(?:{separators}|(?:e|and|et|y)(?:\s+(?:il|lo|la|l|the|el|le))?)"
    patterns = [
        rf"\b(?:da|dal|from|de|del|between|tra|entre)?\s*sol(?:\s*range)?\s*\d{{1,5}}\s*{separators_with_and}\s*(?:sol\s*)?\d{{1,5}}\b",
        rf"\bsol\s*\d{{1,5}}\s*{separators_with_and}\s*(?:sol\s*)?\d{{1,5}}\b",
    ]
    spans: list[tuple[int, int]] = []
    for pat in patterns:
        for m in re.finditer(pat, cmd, re.IGNORECASE):
            spans.append((m.start(), m.end()))
    spans = sorted(set(spans))
    if len(spans) < 2:
        return []
    blocks: list[str] = []
    prev_end = 0
    for idx, (_start, end) in enumerate(spans):
        block = cmd[0:end] if idx == 0 else cmd[prev_end:end]
        block = re.sub(r"^(?:[,;]|\b(?:e|and|et|y|poi|then|quindi)\b\s*)+", "", block, flags=re.IGNORECASE).strip(" ,;")
        if block:
            blocks.append(block)
        prev_end = end
    return blocks


def _parse_int(text: str, pattern: str) -> Optional[int]:
    m = re.search(pattern, text, re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _parse_requested_image_count(text: str) -> Optional[int]:
    patterns = _pr_list("requested_count_patterns", _PROMPT_RULES_DEFAULT["requested_count_patterns"])
    for pat in patterns:
        n = _parse_int(text, pat)
        if n is not None and n > 0:
            return int(n)
    return None


def _parse_each_camera_count(text: str) -> Optional[int]:
    patterns = _pr_list("each_camera_count_patterns", _PROMPT_RULES_DEFAULT["each_camera_count_patterns"])
    for pat in patterns:
        n = _parse_int(text, pat)
        if n is not None and n > 0:
            return int(n)
    return None


def _parse_camera_quota_map(text: str, available: list[str]) -> dict[str, int]:
    cmd = _norm_ascii(text)
    out: dict[str, int] = {}
    for cam in available:
        cam_name = str(cam)
        aliases = _camera_aliases(cam_name)
        if not aliases:
            continue
        for alias in aliases:
            alias_key = _normalize_camera_key(alias)
            if not alias_key:
                continue
            cam_pat = re.escape(alias_key).replace(r"\ ", r"\s+")
            patterns = [
                rf"\b(\d{{1,4}})\s*(?:immagini|images|image|foto|photos)?\s*(?:di|for|pour|de|del|della|per)?\s*{cam_pat}\b",
                rf"\b{cam_pat}\s*(?:[:=\-]|\s)\s*(\d{{1,4}})\b",
            ]
            matched = False
            for pat in patterns:
                n = _parse_int(cmd, pat)
                if n is not None and n > 0:
                    out[cam_name] = int(n)
                    matched = True
                    break
            if matched:
                break
    return out


def _wants_random_sample(text: str) -> bool:
    words = _pr_list("random_words", _PROMPT_RULES_DEFAULT["random_words"])
    return any(re.search(rf"\b{w}\b", text, re.IGNORECASE) for w in words)


def _wants_organize_step(text: str) -> bool:
    if re.search(r"\borgani(?:zz|s)\w*\b", text, re.IGNORECASE):
        return True
    return any(re.search(rf"\b{w}\b", text, re.IGNORECASE) for w in _pr_list("organize_words", _PROMPT_RULES_DEFAULT["organize_words"]))


def _has_workflow_action_words(text: str) -> bool:
    cmd = _norm_ascii(text)
    patterns = _pr_list("workflow_action_patterns", _PROMPT_RULES_DEFAULT["workflow_action_patterns"])
    return any(re.search(p, cmd, re.IGNORECASE) for p in patterns)


def _append_parser_debug(msg: str, debug_line: str) -> str:
    base = normalize_text(msg)
    dbg = normalize_text(debug_line)
    if not dbg:
        return base
    return f"{base}\n{dbg}" if base else dbg


def _contains_word(text: str, words: list[str]) -> bool:
    for w in words:
        if re.search(rf"\b{re.escape(w)}\b", text):
            return True
    return False


def _has_download_intent(text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:scaric\w*|download\w*|telecharg\w*|acquis\w*|prelev\w*|ottien\w*|obten\w*)\b",
            text,
            re.IGNORECASE,
        )
    )


def _has_process_intent(text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:process\w*|processa\w*|convert\w*|elabor\w*|trait\w*|traite\w*|trasform\w*|transform\w*|genera\w*)\b",
            text,
            re.IGNORECASE,
        )
    )


def _normalize_command_for_parser(text: str) -> str:
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


def _normalize_camera_key(text: str) -> str:
    s = _norm_ascii(text or "")
    s = s.replace("_", " ").replace("-", " ")
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _camera_aliases(cam_name: str) -> set[str]:
    key = _normalize_camera_key(cam_name)
    if not key:
        return set()
    aliases: set[str] = {key, key.replace(" ", "")}
    if "navcam" in key:
        aliases.update({"navcam", "nav cam", "ncam"})
    if "hazcam" in key:
        aliases.update({"hazcam", "haz cam", "fhaz", "rhaz"})
    if "mastcam" in key:
        aliases.update({"mastcam", "mast cam", "mcam"})
    if "mahli" in key:
        aliases.update({"mahli"})
    if "mardi" in key:
        aliases.update({"mardi"})
    if "chemcam" in key:
        aliases.update({"chemcam", "chem cam", "ccam", "rmi"})
    return {a for a in aliases if a}


def _parse_cameras(text: str, available: list[str]) -> list[str]:
    lowered = _norm_ascii(text)
    normalized_text = _normalize_camera_key(text)
    compact_text = normalized_text.replace(" ", "")
    picked: list[str] = []
    for cam in available:
        aliases = _camera_aliases(str(cam))
        for alias in aliases:
            alias_key = _normalize_camera_key(alias)
            if not alias_key:
                continue
            alias_compact = alias_key.replace(" ", "")
            if alias_key in normalized_text or (alias_compact and alias_compact in compact_text):
                picked.append(str(cam))
                break
    m = re.search(r"camera[s]?\s*[:=]?\s*([a-z0-9_,\-\s]+)", lowered)
    if m:
        for p in [x.strip() for x in m.group(1).split(",") if x.strip()]:
            p_key = _normalize_camera_key(p)
            for cam in available:
                aliases = _camera_aliases(str(cam))
                match = False
                for alias in aliases:
                    alias_key = _normalize_camera_key(alias)
                    if not alias_key:
                        continue
                    if alias_key == p_key or alias_key.replace(" ", "") == p_key.replace(" ", ""):
                        match = True
                        break
                if match:
                    if str(cam) not in picked:
                        picked.append(str(cam))
                    break
    return sorted(set(picked))


def _wants_all_cameras(text: str) -> bool:
    cmd = _norm_ascii(text)
    patterns = _pr_list("all_cameras_patterns", _PROMPT_RULES_DEFAULT["all_cameras_patterns"])
    return any(re.search(p, cmd, re.IGNORECASE) for p in patterns)


def _is_unsupported_image_url_request(cmd: str) -> bool:
    url_tokens = _pr_list("unsupported_url_tokens", _PROMPT_RULES_DEFAULT["unsupported_url_tokens"])
    listing_verbs = _pr_list("unsupported_url_listing_verbs", _PROMPT_RULES_DEFAULT["unsupported_url_listing_verbs"])
    has_url_request = any(token in cmd for token in url_tokens)
    has_listing_verb = any(token in cmd for token in listing_verbs)
    return has_url_request and has_listing_verb


def _parse_dr_variants(text: str) -> list[str]:
    raw = sorted(set(re.findall(r"\bDR[A-Z0-9]{2}\b", text.upper())))
    alias = {"DRLC": "DRCL"}
    valid = {"DRCL", "DRCX", "DRLX", "DRXX"}
    out = []
    for token in raw:
        mapped = alias.get(token, token)
        if mapped in valid:
            out.append(mapped)
    return sorted(set(out))


def _parse_size_bytes_from_text(text: str) -> Optional[int]:
    t_ = text.lower().replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(kb|mb|gb|b)\b", t_, re.IGNORECASE)
    if not m:
        m = re.search(r"(?:>=|>|min(?:imum)?|almeno|piu grandi di|piu grande di)\s*(\d{3,})\b", t_, re.IGNORECASE)
        if m:
            try:
                return int(float(m.group(1)))
            except Exception:
                return None
        return None
    try:
        value = float(m.group(1))
    except Exception:
        return None
    unit = m.group(2).lower()
    if unit == "kb":
        return int(value * 1024)
    if unit == "mb":
        return int(value * 1024 * 1024)
    if unit == "gb":
        return int(value * 1024 * 1024 * 1024)
    return int(value)


def _is_camera_list_request(text: str) -> bool:
    cmd = _norm_ascii(text)

    def _has_any(words: list[str]) -> bool:
        return any(re.search(rf"\b{re.escape(w)}\b", cmd) for w in words)

    camera_words = _pr_list("camera_list_camera_words", _PROMPT_RULES_DEFAULT["camera_list_camera_words"])
    list_words = _pr_list("camera_list_list_words", _PROMPT_RULES_DEFAULT["camera_list_list_words"])
    action_words = _pr_list("camera_list_action_words", _PROMPT_RULES_DEFAULT["camera_list_action_words"])
    has_action = any(re.search(rf"\b{w}\w*\b", cmd) for w in action_words)
    return _has_any(camera_words) and _has_any(list_words) and not has_action


def _bulk_confirmation_text(total: int, *, action_type: str = "download_process") -> str:
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
    lang = normalize_text(st.session_state.get("lang", "it")).lower()
    return {
        "en": "Operation canceled.",
        "fr": "Operation annulee.",
        "es": "Operacion cancelada.",
        "de": "Vorgang abgebrochen.",
    }.get(lang, "Operazione annullata.")


def _no_pending_bulk_text() -> str:
    lang = normalize_text(st.session_state.get("lang", "it")).lower()
    return {
        "en": "No pending operation.",
        "fr": "Aucune operation en attente.",
        "es": "No hay ninguna operacion pendiente.",
        "de": "Kein ausstehender Vorgang.",
    }.get(lang, "Nessuna operazione in attesa.")


def _bulk_cancel_words() -> list[str]:
    return _pr_list("bulk_cancel_words", _PROMPT_RULES_DEFAULT["bulk_cancel_words"])


def _bulk_proceed_words() -> list[str]:
    return _pr_list("bulk_proceed_words", _PROMPT_RULES_DEFAULT["bulk_proceed_words"])


def _humanize_parser_response(user_command: str, parser_text: str) -> str:
    _ = user_command
    return normalize_text(parser_text)


def _extract_parser_plan_map(parser_text: str) -> dict[str, Any]:
    raw = normalize_text(parser_text)
    m = re.search(r"(?im)^\[parser-plan\]\s*(.+)$", raw)
    if not m:
        return {}
    body = normalize_text(m.group(1))
    out: dict[str, Any] = {}
    if not body:
        return out
    parts = [p.strip() for p in body.split(";") if p.strip()]
    for part in parts:
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        key = normalize_text(k)
        val = normalize_text(v)
        if not key:
            continue
        if val.startswith("{") and val.endswith("}"):
            try:
                out[key] = json.loads(val)
                continue
            except Exception:
                pass
        out[key] = val
    return out


def _parser_validation_note(user_command: str, parser_text: str) -> str:
    raw = normalize_text(parser_text)
    if not raw:
        return ""

    cmd = _normalize_command_for_parser(user_command)
    plan = _extract_parser_plan_map(raw)
    issues: list[str] = []

    requested_each = _parse_each_camera_count(cmd)
    wants_all = _wants_all_cameras(cmd)
    requested_total = _parse_requested_image_count(cmd)

    if requested_each and requested_each > 0 and wants_all:
        per_cam = plan.get("per_camera")
        per_cam_missing = (
            per_cam is None
            or normalize_text(per_cam) in {"", "-", "{}", "null", "none"}
            or (isinstance(per_cam, dict) and len(per_cam) == 0)
        )
        if per_cam_missing:
            issues.append("Hai richiesto una quota per ogni camera, ma il piano non mostra quote per-camera.")

    if requested_each and requested_each > 0 and requested_total and requested_total <= requested_each and wants_all:
        issues.append("Il totale richiesto sembra incompatibile con una quota per ogni camera.")

    cams_requested_all = wants_all
    if cams_requested_all and re.search(r"(?im)^cameras:\s*navcam:", raw):
        issues.append("Hai chiesto tutte le camere, ma il risultato sembra limitato solo a Navcam.")

    dedup: list[str] = []
    seen: set[str] = set()
    for it in issues:
        key = _norm_ascii(it)
        if not key or key in seen:
            continue
        seen.add(key)
        dedup.append(it)
    if not dedup:
        return ""
    return "Controllo coerenza: " + " | ".join(dedup[:3])
