"""Human-readable explanation for one product_composition.py/customization.py
filename-segment code (e.g. what "DRCL" or "RADLD" mean), in a given UI language.

Streamlit-free port of two pieces of the legacy Streamlit dashboard, both
Streamlit-free themselves once their `st.session_state.lang`-reading `tr()`
closures are swapped for an explicit `lang` argument -- so reusing their
tables directly (instead of re-writing the same explanations in JS) means
neither can ever drift out of wording with this bridge:
- `app.py::_segment_explanation()` (the generic "Spiega" dialog, covers
  product_type/product_variant/gop_counter/version/suffix/file_format/sample_type,
  plus whatever's in EXTRA_TRANSLATIONS for camera_prefix/processing_marker).
- `app.py`'s engineering-camera matrix screen, which additionally maps a
  camera_prefix (e.g. "NAB") or a processing_marker's leading 3-letter product
  abbreviation (e.g. "RAD" out of "RADLD") to a specific label/help pair --
  `{code}_help` / `engineering_{code}_help` / `navcam_{code}_help` in
  EXTRA_TRANSLATIONS -- richer than the generic notes the dialog falls back to.
"""

from __future__ import annotations

from catalog_manager.i18n_catalog import EXTRA_TRANSLATIONS

SUPPORTED_LANGS = ("it", "en", "fr", "es", "de")

# The engineering matrix screen's `group_codes` (app.py) -- 3-letter NASA
# product-type abbreviations that prefix a processing_marker code (e.g. the
# "RAD" in "RADLD"). Kept in sync manually since app.py's tuple isn't
# importable standalone without the rest of that Streamlit module.
_ENGINEERING_PREFIX_CODES = frozenset(
    {
        "EDR", "ILT", "RAD", "RAS", "PRC",
        "ERP", "ERS", "ECS", "EHG", "EID",
        "DSP", "DSR", "DFF", "MDS", "RNG", "RNR", "RNE", "XYZ", "XYR", "XYM", "XYE", "MXY",
        "UVW", "UVS", "SLP", "SHD", "SMG", "SNT", "SRD", "RUD", "RUT",
        "ARM", "ARP",
    }
)
# Navcam has its own friendlier wording for its 4 most common product types,
# preferred over the generic engineering_* one when it exists.
_NAVCAM_OVERRIDE_CODES = frozenset({"EDR", "ILT", "RAD", "RAS"})


def _lang_table(lang: str) -> dict[str, str]:
    return EXTRA_TRANSLATIONS.get(lang) or EXTRA_TRANSLATIONS["en"]


def _tr(key: str, lang: str) -> str:
    return _lang_table(lang).get(key) or EXTRA_TRANSLATIONS["en"].get(key, key)


def _processing_marker_explanation(code: str, lang: str, camera: str, table: dict[str, str]) -> str:
    marker_key = f"marker_{code}"
    if marker_key in table:
        return _tr(marker_key, lang)
    prefix = code[:3].upper()
    if camera == "navcam" and prefix in _NAVCAM_OVERRIDE_CODES:
        navcam_key = f"navcam_{prefix.lower()}_help"
        if navcam_key in table:
            return _tr(navcam_key, lang)
    if prefix in _ENGINEERING_PREFIX_CODES:
        engineering_key = f"engineering_{prefix.lower()}_help"
        if engineering_key in table:
            return _tr(engineering_key, lang)
    return _tr("generic_code_note", lang)


def _camera_prefix_explanation(code: str, lang: str, table: dict[str, str]) -> str:
    specific_key = f"{code.lower()}_help"
    return _tr(specific_key, lang) if specific_key in table else _tr("prefix_note", lang)


def explain_segment(dimension: str, code: str, lang: str = "en", camera: str = "") -> dict[str, str]:
    """Return `{"role": <dimension's display name>, "explanation": <what `code` means>}`. `camera` is only used to pick Navcam's friendlier processing_marker wording over the generic engineering one when both exist -- every other dimension ignores it."""
    lang = lang if lang in SUPPORTED_LANGS else "en"
    role = _tr(f"role_{dimension}", lang)
    table = _lang_table(lang)

    if dimension == "product_type":
        explanation = _tr(f"product_type_{code}", lang)
    elif dimension == "product_variant" and len(code) == 3:
        explanation = (
            f"{code[0]} — {_tr(f'product_type_{code[0]}', lang)}\n\n"
            f"{code[1]} — {_tr('gop_note', lang)}\n\n"
            f"{code[2]} — {_tr('version_note', lang)}"
        )
    elif dimension == "product_variant" and len(code) == 2:
        explanation = f"{code[0]} — {_tr(f'product_type_{code[0]}', lang)}\n\n{code[1]} — {_tr('version_note', lang)}"
    elif dimension == "gop_counter":
        explanation = _tr("gop_note", lang)
    elif dimension == "version":
        explanation = _tr("version_note", lang)
    elif dimension == "suffix":
        details = [f"{letter} — {_tr(f'process_{letter}', lang)}" for letter in code if f"process_{letter}" in table]
        explanation = _tr("suffix_note", lang) + "\n\n" + "\n\n".join(details)
    elif dimension == "processing_marker":
        explanation = _processing_marker_explanation(code, lang, camera, table)
    elif dimension == "camera_prefix":
        explanation = _camera_prefix_explanation(code, lang, table)
    elif dimension == "file_format":
        explanation = _tr("file_format_note", lang)
    elif dimension == "sample_type":
        sample_key = f"sample_{code}"
        explanation = _tr(sample_key, lang) if sample_key in table else _tr("generic_code_note", lang)
    else:
        explanation = _tr("generic_code_note", lang)

    return {"role": role, "explanation": explanation}
