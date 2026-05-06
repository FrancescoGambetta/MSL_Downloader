from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path
from typing import Any, Callable

import streamlit as st
from streamlit.components.v1 import html as components_html

from runtime import normalize_text

try:  # pragma: no cover
    import markdown as markdown_lib
except Exception:  # pragma: no cover
    markdown_lib = None

_T: Callable[..., str] = lambda key, **kwargs: key.format(**kwargs) if kwargs else key


def set_translator(fn: Callable[..., str]) -> None:
    global _T
    _T = fn


def t(key: str, **kwargs: Any) -> str:
    try:
        return _T(key, **kwargs)
    except Exception:
        return key.format(**kwargs) if kwargs else key


APP_DIR = Path(__file__).resolve().parent


def _load_help_guide_markdown(lang: str) -> str:
    guide_path = APP_DIR / "Guida.md"
    if not guide_path.exists():
        return ""
    try:
        raw = guide_path.read_text(encoding="utf-8")
    except Exception:
        return ""
    blocks = re.findall(r"<!--\s*lang:([a-z]{2})\s*-->\s*(.*?)(?=\n<!--\s*lang:[a-z]{2}\s*-->|$)", raw, flags=re.S | re.I)
    if not blocks:
        return raw.strip()
    by_lang = {normalize_text(code).lower(): content.strip() for code, content in blocks}
    lang_norm = normalize_text(lang).lower()
    return by_lang.get(lang_norm) or by_lang.get("it") or by_lang.get("en") or next(iter(by_lang.values()), "")


def _help_markdown_to_html(md_text: str) -> str:
    raw = normalize_text(md_text)
    if not raw:
        return ""
    if markdown_lib is not None:
        try:
            return markdown_lib.markdown(raw, extensions=["extra"])
        except Exception:
            pass

    lines = raw.splitlines()
    out: list[str] = []
    in_ul = False
    in_ol = False

    def close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    def inline_fmt(text: str) -> str:
        esc = escape(text)
        esc = re.sub(r"`([^`]+)`", r"<code>\1</code>", esc)
        return esc

    for line in lines:
        stripped = line.strip()
        if not stripped:
            close_lists()
            continue
        if stripped.startswith("# "):
            close_lists()
            out.append(f"<h1>{inline_fmt(stripped[2:].strip())}</h1>")
            continue
        if stripped.startswith("## "):
            close_lists()
            out.append(f"<h2>{inline_fmt(stripped[3:].strip())}</h2>")
            continue
        m_ul = re.match(r"^[-*]\s+(.+)$", stripped)
        if m_ul:
            if not in_ul:
                close_lists()
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{inline_fmt(m_ul.group(1).strip())}</li>")
            continue
        m_ol = re.match(r"^\d+\.\s+(.+)$", stripped)
        if m_ol:
            if not in_ol:
                close_lists()
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{inline_fmt(m_ol.group(1).strip())}</li>")
            continue
        close_lists()
        out.append(f"<p>{inline_fmt(stripped)}</p>")

    close_lists()
    return "\n".join(out)


def _render_help_overlay() -> None:
    guide_md = _load_help_guide_markdown(st.session_state.lang)
    guide_html = _help_markdown_to_html(guide_md) if guide_md else f"<p>{escape(t('help_dialog_intro'))}</p>"
    overlay_title = escape(t("help_dialog_title"))
    session_key = f"help_overlay_closed::{normalize_text(st.session_state.get('current_user_norm'))}::{normalize_text(st.session_state.get('current_session_id'))}"
    overlay_markup = f"""
<div class="help-overlay-root" aria-hidden="false">
  <div class="help-overlay-backdrop"></div>
  <div class="help-overlay-card" role="dialog" aria-modal="true" aria-label="{overlay_title}">
    <button type="button" class="help-overlay-close" data-help-close aria-label="{escape(t('help_dialog_close'))}">×</button>
    <div class="help-overlay-header">
      <div class="help-overlay-title">{overlay_title}</div>
    </div>
    <div class="help-overlay-body">
      {guide_html}
    </div>
  </div>
</div>
"""
    overlay_script = f"""
<script>
(function() {{
  const rootId = "help-overlay-root";
  const sessionKey = {json.dumps(session_key)};
  let parentDoc = document;
  try {{
    if (window.parent && window.parent.document && window.parent.document.body) {{
      parentDoc = window.parent.document;
    }}
  }} catch (err) {{
    parentDoc = document;
  }}

  try {{
    if (window.parent.localStorage.getItem(sessionKey) === "1") {{
      return;
    }}
  }} catch (err) {{}}

  const existing = parentDoc.getElementById(rootId);
  if (existing) {{
    existing.remove();
  }}

  const root = parentDoc.createElement("div");
  root.id = rootId;
  root.innerHTML = {json.dumps(overlay_markup)};
  parentDoc.body.appendChild(root);

  const closeBtn = root.querySelector("[data-help-close]");
  if (closeBtn) {{
    closeBtn.addEventListener("click", function() {{
      try {{
        window.parent.localStorage.setItem(sessionKey, "1");
      }} catch (err) {{}}
      try {{
        const trigger = parentDoc.querySelector('[class*="st-key-help_trigger_btn"]');
        if (trigger) {{
          trigger.remove();
        }}
      }} catch (err) {{}}
      root.remove();
    }});
  }}
}})();
</script>
"""
    components_html(overlay_script, height=0, width=0)
