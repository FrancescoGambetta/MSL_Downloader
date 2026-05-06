from Styles.themes import get_theme


def build_app_css(mode_name, theme_name):
    th = get_theme(mode_name, theme_name)
    tone_blend = th["bg"]
    button_bg = f'color-mix(in srgb, {th["surface"]} 72%, {tone_blend} 28%)'
    button_bg_hover = f'color-mix(in srgb, {th["surface"]} 58%, {tone_blend} 42%)'
    select_bg = f'color-mix(in srgb, {th["surface"]} 82%, {tone_blend} 18%)'
    listbox_bg = f'color-mix(in srgb, {th["surface"]} 88%, {tone_blend} 12%)'
    live_log_bg = f'color-mix(in srgb, {th["surface"]} 92%, {tone_blend} 8%)'
    msg_card_bg = f'color-mix(in srgb, {th["surface"]} 94%, {tone_blend} 6%)'
    dialog_bg = f'color-mix(in srgb, {th["panel"]} 90%, {th["surface"]} 10%)'
    dialog_surface = f'color-mix(in srgb, {th["surface"]} 84%, {th["panel"]} 16%)'
    dialog_backdrop = f'color-mix(in srgb, {th["bg"]} 58%, transparent)'
    dialog_title = th["text"]
    dialog_muted = f'color-mix(in srgb, {th["text"]} 76%, {th["surface"]} 24%)'
    dialog_border = f'color-mix(in srgb, {th["accent"]} 34%, transparent)'
    dialog_accent_btn = f'color-mix(in srgb, {th["accent"]} 72%, {th["surface"]} 28%)'
    dialog_accent_btn_hover = f'color-mix(in srgb, {dialog_accent_btn} 82%, {th["panel"]} 18%)'
    dialog_accent_text = th["text"]
    dialog_shadow = f'color-mix(in srgb, {th["bg"]} 72%, transparent)'
    input_bg = f'color-mix(in srgb, {th["surface"]} 82%, {tone_blend} 18%)'
    input_border = f'color-mix(in srgb, {th["accent"]} 42%, transparent)'
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Lato:wght@300;400;700;900&family=Source+Code+Pro:wght@400;600&display=swap');

html, body, [class*="css"] {{
    font-family: 'Lato', sans-serif;
}}

html {{
    zoom: 0.88;
}}

body, p, div, label, span {{
    color: {th["text"]};
}}

h1, .hero-title {{
    font-weight: 900;
    letter-spacing: 0.01em;
}}
h2, .pane-title {{
    font-weight: 800;
}}
div[data-testid="stCaptionContainer"] p {{
    font-size: 0.78rem !important;
    opacity: 0.76;
}}

/* Streamlit progress bar: theme-adaptive colors */
div[data-testid="stProgress"] > div {{
    background: color-mix(in srgb, {th["surface"]} 80%, {tone_blend} 20%) !important;
    border-radius: 999px !important;
}}
/* Streamlit has changed markup across versions; style both BaseWeb and ARIA variants. */
div[data-testid="stProgress"] [data-baseweb="progress-bar"] > div {{
    background: color-mix(in srgb, {th["surface"]} 80%, {tone_blend} 20%) !important;
    border-radius: 999px !important;
}}
div[data-testid="stProgress"] [data-baseweb="progress-bar"] > div > div {{
    background-color: color-mix(in srgb, {th["accent"]} 92%, {th["surface"]} 8%) !important;
    border-radius: 999px !important;
}}
div[data-testid="stProgress"] div[role="progressbar"] {{
    background: color-mix(in srgb, {th["surface"]} 80%, {tone_blend} 20%) !important;
    border-radius: 999px !important;
}}
div[data-testid="stProgress"] div[role="progressbar"] > div {{
    background-color: color-mix(in srgb, {th["accent"]} 92%, {th["surface"]} 8%) !important;
    border-radius: 999px !important;
}}
div[data-testid="stProgress"] div[role="progressbar"] > div > div {{
    background-color: color-mix(in srgb, {th["accent"]} 92%, {th["surface"]} 8%) !important;
    border-radius: 999px !important;
}}

/* Streamlit buttons: force readable contrast across OS/browser rendering differences */
.stButton > button {{
    background: {button_bg} !important;
    color: {th["text"]} !important;
    border: 1px solid color-mix(in srgb, {th["accent"]} 35%, transparent) !important;
    border-radius: 8px !important;
}}
.stButton > button p,
.stButton > button span {{
    color: {th["text"]} !important;
}}
.stButton > button:hover {{
    background: {button_bg_hover} !important;
    border-color: color-mix(in srgb, {th["accent"]} 55%, transparent) !important;
}}
.stButton > button:active {{
    background: {button_bg_hover} !important;
    color: {th["text"]} !important;
    border-color: color-mix(in srgb, {th["accent"]} 62%, transparent) !important;
}}
.stButton > button:focus {{
    box-shadow: 0 0 0 2px color-mix(in srgb, {th["accent"]} 25%, transparent) !important;
    border-color: color-mix(in srgb, {th["accent"]} 65%, transparent) !important;
}}
.stButton > button:disabled {{
    opacity: 0.72 !important;
    color: color-mix(in srgb, {th["text"]} 80%, #000000 20%) !important;
}}
.stButton > button:disabled p,
.stButton > button:disabled span {{
    color: color-mix(in srgb, {th["text"]} 80%, #000000 20%) !important;
}}

/* "Choose folder" button in Configurations: keep consistent across hover/focus states */
[class*="st-key-cfg_choose_folder_btn"] button {{
    background: {button_bg} !important;
    color: {th["text"]} !important;
    border: 1px solid color-mix(in srgb, {th["accent"]} 35%, transparent) !important;
    border-radius: 8px !important;
}}
[class*="st-key-cfg_choose_folder_btn"] button:hover,
[class*="st-key-cfg_choose_folder_btn"] button:active,
[class*="st-key-cfg_choose_folder_btn"] button[aria-pressed="true"] {{
    background: {button_bg_hover} !important;
    border-color: color-mix(in srgb, {th["accent"]} 55%, transparent) !important;
    box-shadow: none !important;
    filter: none !important;
}}
[class*="st-key-cfg_choose_folder_btn"] button:focus {{
    box-shadow: 0 0 0 2px color-mix(in srgb, {th["accent"]} 25%, transparent) !important;
    border-color: color-mix(in srgb, {th["accent"]} 65%, transparent) !important;
    outline: none !important;
    filter: none !important;
}}
[class*="st-key-cfg_choose_folder_btn"] button:focus-visible {{
    box-shadow: 0 0 0 2px color-mix(in srgb, {th["accent"]} 25%, transparent) !important;
    outline: none !important;
}}
[class*="st-key-cfg_choose_folder_btn"] button p,
[class*="st-key-cfg_choose_folder_btn"] button span {{
    color: {th["text"]} !important;
}}

/* Form submit buttons must match normal button styling */
.stFormSubmitButton > button {{
    background: {button_bg} !important;
    color: {th["text"]} !important;
    border: 1px solid color-mix(in srgb, {th["accent"]} 35%, transparent) !important;
    border-radius: 8px !important;
}}
.stFormSubmitButton > button p,
.stFormSubmitButton > button span {{
    color: {th["text"]} !important;
}}
.stFormSubmitButton > button:hover {{
    background: {button_bg_hover} !important;
    border-color: color-mix(in srgb, {th["accent"]} 55%, transparent) !important;
}}
.stFormSubmitButton > button:active {{
    background: {button_bg_hover} !important;
    color: {th["text"]} !important;
    border-color: color-mix(in srgb, {th["accent"]} 62%, transparent) !important;
}}
.stFormSubmitButton > button:focus {{
    box-shadow: 0 0 0 2px color-mix(in srgb, {th["accent"]} 25%, transparent) !important;
    border-color: color-mix(in srgb, {th["accent"]} 65%, transparent) !important;
}}
.stFormSubmitButton > button:disabled {{
    opacity: 0.72 !important;
    color: color-mix(in srgb, {th["text"]} 80%, #000000 20%) !important;
}}
.stFormSubmitButton > button:disabled p,
.stFormSubmitButton > button:disabled span {{
    color: color-mix(in srgb, {th["text"]} 80%, #000000 20%) !important;
}}

/* Streamlit dialog (bulk confirmation): adaptive contrast across themes */
div[data-testid="stDialog"],
div[role="dialog"][aria-modal="true"] {{
    z-index: 1200 !important;
}}
div[data-testid="stDialog"] > div,
div[role="dialog"][aria-modal="true"] {{
    background: {dialog_bg} !important;
    border: 1px solid color-mix(in srgb, {th["accent"]} 34%, transparent) !important;
    border-radius: 14px !important;
    box-shadow: 0 24px 80px {dialog_shadow} !important;
}}
div[data-testid="stDialog"] *,
div[role="dialog"][aria-modal="true"] * {{
    color: {th["text"]} !important;
    -webkit-text-fill-color: {th["text"]} !important;
}}
div[data-testid="stDialog"] [data-testid="stNumberInputContainer"],
div[role="dialog"][aria-modal="true"] [data-testid="stNumberInputContainer"] {{
    background: {dialog_surface} !important;
    border: 1px solid {input_border} !important;
    border-radius: 10px !important;
}}
div[data-testid="stDialog"] [data-testid="stNumberInputContainer"] input,
div[role="dialog"][aria-modal="true"] [data-testid="stNumberInputContainer"] input {{
    background: {input_bg} !important;
    color: {th["text"]} !important;
    -webkit-text-fill-color: {th["text"]} !important;
    border: none !important;
}}
div[data-testid="stDialog"] [data-testid="stNumberInputContainer"] button,
div[role="dialog"][aria-modal="true"] [data-testid="stNumberInputContainer"] button {{
    background: color-mix(in srgb, {th["surface"]} 72%, {tone_blend} 28%) !important;
    color: {th["text"]} !important;
    -webkit-text-fill-color: {th["text"]} !important;
    border: 1px solid color-mix(in srgb, {th["accent"]} 32%, transparent) !important;
}}
div[data-testid="stDialog"] [aria-label="Close"],
div[role="dialog"][aria-modal="true"] [aria-label="Close"] {{
    color: {th["text"]} !important;
    -webkit-text-fill-color: {th["text"]} !important;
    opacity: 0.9 !important;
}}
div[data-testid="stDialog"] [aria-label="Close"]:hover,
div[role="dialog"][aria-modal="true"] [aria-label="Close"]:hover {{
    opacity: 1 !important;
}}
div[role="presentation"][data-testid="stDialogOverlay"] {{
    background: {dialog_backdrop} !important;
    backdrop-filter: blur(2px) !important;
}}

/* Custom bulk overlay panel (Streamlit container-key based, dialog-free) */
[class*="st-key-bulk_overlay_panel"] {{
    position: fixed !important;
    inset: 0 !important;
    z-index: 1300 !important;
    display: flex !important;
    align-items: flex-start !important;
    justify-content: center !important;
    padding-top: clamp(3.8rem, 9vh, 7rem) !important;
    pointer-events: none !important;
    overflow: visible !important;
}}
[class*="st-key-bulk_overlay_panel"]::before {{
    content: "" !important;
    position: fixed !important;
    inset: 0 !important;
    background: {dialog_backdrop} !important;
    backdrop-filter: blur(2px) !important;
    pointer-events: auto !important;
}}
[class*="st-key-bulk_overlay_panel"] > div {{
    width: 100% !important;
    max-width: none !important;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    padding: 0 !important;
    pointer-events: auto !important;
}}
[class*="st-key-bulk_overlay_card"] {{
    width: min(560px, 92vw) !important;
    margin: 0 auto !important;
    background: {dialog_bg} !important;
    border: 1px solid {dialog_border} !important;
    border-radius: 14px !important;
    box-shadow: 0 24px 80px {dialog_shadow} !important;
    padding: 0.55rem 0.65rem 0.8rem 0.65rem !important;
    pointer-events: auto !important;
}}
[class*="st-key-bulk_overlay_card"] p,
[class*="st-key-bulk_overlay_card"] label,
[class*="st-key-bulk_overlay_card"] small,
[class*="st-key-bulk_overlay_card"] div[data-testid="stCaptionContainer"] {{
    color: {dialog_muted} !important;
    -webkit-text-fill-color: {dialog_muted} !important;
}}
[class*="st-key-bulk_overlay_card"] h1,
[class*="st-key-bulk_overlay_card"] h2,
[class*="st-key-bulk_overlay_card"] h3,
[class*="st-key-bulk_overlay_card"] h4 {{
    color: {dialog_title} !important;
    -webkit-text-fill-color: {dialog_title} !important;
    font-weight: 800 !important;
}}
[class*="st-key-bulk_overlay_card"] [class*="st-key-bulk_overlay_limit_input"] [data-testid="stNumberInputContainer"] {{
    background: {dialog_surface} !important;
    border: 1px solid {dialog_border} !important;
    border-radius: 10px !important;
}}
[class*="st-key-bulk_overlay_card"] [data-testid="stWidgetLabel"] button {{
    display: none !important;
}}
[class*="st-key-bulk_overlay_card"] [class*="st-key-bulk_overlay_limit_input"] input {{
    background: {input_bg} !important;
    color: {dialog_title} !important;
    -webkit-text-fill-color: {dialog_title} !important;
    border: none !important;
}}
[class*="st-key-bulk_overlay_card"] [class*="st-key-bulk_overlay_limit_input"] button {{
    background: color-mix(in srgb, {th["surface"]} 72%, {tone_blend} 28%) !important;
    color: {dialog_title} !important;
    border: 1px solid {dialog_border} !important;
}}
[class*="st-key-bulk_overlay_close_btn"] button {{
    min-height: 2.1rem !important;
    border-radius: 10px !important;
    background: {dialog_surface} !important;
    color: {dialog_title} !important;
    border: 1px solid {dialog_border} !important;
    font-size: 1.05rem !important;
    font-weight: 700 !important;
    padding: 0 !important;
}}
[class*="st-key-bulk_overlay_cancel_btn"] button,
[class*="st-key-bulk_overlay_continue_btn"] button {{
    min-height: 2.5rem !important;
    border-radius: 10px !important;
    background: {dialog_surface} !important;
    color: {dialog_title} !important;
    border: 1px solid {dialog_border} !important;
    font-weight: 700 !important;
}}
[class*="st-key-bulk_overlay_cancel_btn"] button span,
[class*="st-key-bulk_overlay_cancel_btn"] button p {{
    color: {dialog_title} !important;
    -webkit-text-fill-color: {dialog_title} !important;
}}
[class*="st-key-bulk_overlay_continue_btn"] button {{
    background: {dialog_accent_btn} !important;
    color: {dialog_accent_text} !important;
    -webkit-text-fill-color: {dialog_accent_text} !important;
    border-color: color-mix(in srgb, {dialog_accent_btn} 70%, {th["panel"]} 30%) !important;
}}
[class*="st-key-bulk_overlay_close_btn"] button:hover,
[class*="st-key-bulk_overlay_cancel_btn"] button:hover {{
    background: color-mix(in srgb, {dialog_surface} 80%, {th["accent"]} 20%) !important;
    border-color: color-mix(in srgb, {th["accent"]} 55%, transparent) !important;
}}
[class*="st-key-bulk_overlay_continue_btn"] button:hover {{
    background: {dialog_accent_btn_hover} !important;
    border-color: color-mix(in srgb, {dialog_accent_btn} 68%, {th["panel"]} 32%) !important;
}}
[class*="st-key-bulk_overlay_continue_btn"] button span,
[class*="st-key-bulk_overlay_continue_btn"] button p {{
    color: {dialog_accent_text} !important;
    -webkit-text-fill-color: {dialog_accent_text} !important;
}}

/* Selectbox + dropdown menu readability across platforms */
.stSelectbox [data-baseweb="select"] > div,
.stMultiSelect [data-baseweb="select"] > div {{
    background: {select_bg} !important;
    color: {th["text"]} !important;
    border: 1px solid color-mix(in srgb, {th["accent"]} 35%, transparent) !important;
}}
.stSelectbox [data-baseweb="select"] span,
.stSelectbox [data-baseweb="select"] div,
.stMultiSelect [data-baseweb="select"] span,
.stMultiSelect [data-baseweb="select"] div {{
    color: {th["text"]} !important;
}}
div[role="listbox"] {{
    background: {listbox_bg} !important;
    border: 1px solid color-mix(in srgb, {th["accent"]} 35%, transparent) !important;
}}
div[data-baseweb="popover"],
div[data-baseweb="menu"] {{
    background: {listbox_bg} !important;
    border: 1px solid color-mix(in srgb, {th["accent"]} 35%, transparent) !important;
}}
div[data-baseweb="popover"] ul,
div[data-baseweb="menu"] ul {{
    background: {listbox_bg} !important;
}}
div[role="option"] {{
    color: {th["text"]} !important;
}}
div[data-baseweb="popover"] li,
div[data-baseweb="menu"] li {{
    color: {th["text"]} !important;
    background: transparent !important;
}}
div[role="option"]:hover {{
    background: color-mix(in srgb, {th["accent"]} 22%, {th["surface"]} 78%) !important;
    color: {th["text"]} !important;
}}
div[data-baseweb="popover"] li:hover,
div[data-baseweb="menu"] li:hover {{
    background: color-mix(in srgb, {th["accent"]} 22%, {th["surface"]} 78%) !important;
    color: {th["text"]} !important;
}}
div[role="option"][aria-selected="true"] {{
    background: color-mix(in srgb, {th["accent"]} 30%, {th["surface"]} 70%) !important;
    color: {th["text"]} !important;
}}
div[data-baseweb="popover"] li[aria-selected="true"],
div[data-baseweb="menu"] li[aria-selected="true"] {{
    background: color-mix(in srgb, {th["accent"]} 30%, {th["surface"]} 70%) !important;
    color: {th["text"]} !important;
}}

.stApp {{
    background-color: {th["bg"]} !important;
    background-image:
        radial-gradient(ellipse at 10% 30%, {th["bg1"]} 0%, transparent 55%),
        radial-gradient(ellipse at 90% 80%, {th["bg2"]} 0%, transparent 45%) !important;
}}

header[data-testid="stHeader"] {{ background: transparent; }}
div[data-testid="stExpander"] {{
    background: {th["panel"]} !important;
    border: none !important;
    box-shadow: none !important;
    border-radius: 6px !important;
    opacity: 1 !important;
}}
section[data-testid="stSidebar"] div[data-testid="stExpander"] {{
    opacity: 1 !important;
}}
div[data-testid="stExpander"] summary {{
    background: {th["panel"]} !important;
    border: none !important;
    box-shadow: none !important;
    color: {th["accent_soft"]} !important;
    font-weight: 800 !important;
    letter-spacing: 0.05em !important;
}}
div[data-testid="stExpander"] summary:hover {{
    background: color-mix(in srgb, {th["panel"]} 88%, {th["surface"]} 12%) !important;
}}
div[data-testid="stExpander"] summary div {{
    background: transparent !important;
}}
div[data-testid="stExpander"] div[data-testid="stExpanderDetails"] {{
    background: {th["surface"]} !important;
    border: none !important;
    box-shadow: none !important;
}}
div[data-testid="stExpander"] > div {{
    border: none !important;
    box-shadow: none !important;
}}
[class*="st-key-help_trigger_btn"] {{
    position: fixed !important;
    top: 13.75rem !important;
    right: 1.4rem !important;
    z-index: 60 !important;
    display: flex !important;
    justify-content: flex-end !important;
    align-items: center !important;
    margin: 0 !important;
    width: auto !important;
    max-width: 220px !important;
    overflow: hidden !important;
    animation: help-trigger-life 35s linear forwards !important;
}}
[class*="st-key-help_trigger_btn"] button {{
    width: auto !important;
    min-width: 160px !important;
    padding: 0.6rem 1rem !important;
    border-radius: 999px !important;
    font-size: 0.84rem !important;
    font-weight: 800 !important;
    letter-spacing: 0.04em !important;
    background: color-mix(in srgb, {th["accent"]} 22%, {th["panel"]} 78%) !important;
    border-color: color-mix(in srgb, {th["accent"]} 40%, transparent) !important;
}}
[class*="st-key-help_trigger_btn"] button:hover {{
    background: color-mix(in srgb, {th["accent"]} 30%, {th["panel"]} 70%) !important;
    border-color: color-mix(in srgb, {th["accent"]} 58%, transparent) !important;
}}
@keyframes help-trigger-life {{
    0%, 7.5% {{
        opacity: 0;
        transform: translateX(130%);
        pointer-events: none;
    }}
    9%, 97% {{
        opacity: 1;
        transform: translateX(0);
        pointer-events: auto;
    }}
    100% {{
        opacity: 0;
        transform: translateX(130%);
        pointer-events: none;
    }}
}}
.help-dialog-copy {{
    color: {th["text"]};
    font-size: 0.98rem;
    line-height: 1.55;
}}
.help-dialog-copy p {{
    margin: 0 0 0.75rem 0;
}}
.help-dialog-list {{
    margin: 0;
    padding-left: 1.25rem;
}}
.help-dialog-list li {{
    margin-bottom: 0.55rem;
}}
.help-overlay-root {{
    position: fixed !important;
    inset: 0 !important;
    z-index: 9998 !important;
    display: flex !important;
    align-items: flex-start !important;
    justify-content: center !important;
    pointer-events: auto !important;
}}
.help-overlay-backdrop {{
    position: absolute !important;
    inset: 0 !important;
    background: rgba(4, 8, 14, 0.74) !important;
    backdrop-filter: blur(4px);
}}
.help-overlay-card {{
    position: relative !important;
    width: min(92vw, 860px) !important;
    max-height: calc(100vh - 5.5rem) !important;
    margin-top: 2.25rem !important;
    padding: 1.35rem 1.4rem 1.2rem 1.4rem !important;
    border-radius: 18px !important;
    background: color-mix(in srgb, {th["panel"]} 92%, {th["surface"]} 8%) !important;
    border: 1px solid color-mix(in srgb, {th["accent"]} 18%, transparent) !important;
    box-shadow: 0 24px 80px rgba(0, 0, 0, 0.55) !important;
    overflow: hidden !important;
    animation: help-overlay-drop 240ms ease-out both !important;
}}
.help-overlay-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.9rem;
}}
.help-overlay-title {{
    font-family: 'Source Code Pro', monospace;
    font-size: 0.9rem;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: color-mix(in srgb, {th["accent"]} 78%, {th["text"]} 22%);
    font-weight: 800;
}}
.help-overlay-body {{
    max-height: calc(100vh - 12rem);
    overflow-y: auto;
    padding-right: 0.25rem;
    color: {th["text"]};
    font-size: 1.02rem;
    line-height: 1.65;
}}
.help-overlay-body h1 {{
    font-size: 1.65rem;
    margin: 0.9rem 0 0.65rem 0;
    line-height: 1.15;
}}
.help-overlay-body h2 {{
    font-size: 1.22rem;
    margin: 0.85rem 0 0.45rem 0;
    line-height: 1.2;
}}
.help-overlay-body p,
.help-overlay-body li {{
    font-size: 1rem;
}}
.help-overlay-body ul,
.help-overlay-body ol {{
    padding-left: 1.25rem;
    margin: 0.4rem 0 0.75rem 0;
}}
.help-overlay-body li {{
    margin-bottom: 0.34rem;
}}
.help-overlay-close {{
    position: absolute !important;
    top: 0.9rem !important;
    right: 0.95rem !important;
    width: 1.85rem !important;
    min-width: 1.85rem !important;
    height: 1.85rem !important;
    border: 1px solid color-mix(in srgb, {th["accent"]} 26%, transparent) !important;
    border-radius: 999px !important;
    background: color-mix(in srgb, {th["surface"]} 72%, transparent) !important;
    color: {th["text"]} !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    font-size: 1.1rem !important;
    line-height: 1 !important;
    padding: 0 !important;
    box-shadow: none !important;
    cursor: pointer !important;
}}
.help-overlay-close:hover {{
    background: color-mix(in srgb, {th["accent"]} 16%, {th["surface"]} 84%) !important;
    border-color: color-mix(in srgb, {th["accent"]} 40%, transparent) !important;
}}
[class*="st-key-help_dialog_close_btn"] {{
    position: fixed !important;
    z-index: 10001 !important;
    top: calc(2.25rem + 0.85rem) !important;
    left: calc(50% + min(92vw, 860px) / 2 - 2.75rem) !important;
    width: 1.85rem !important;
    min-width: 1.85rem !important;
}}
[class*="st-key-help_dialog_close_btn"] button {{
    width: 1.85rem !important;
    min-width: 1.85rem !important;
    height: 1.85rem !important;
    border-radius: 999px !important;
    padding: 0 !important;
    font-size: 1.18rem !important;
    line-height: 1 !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
}}
[class*="st-key-help_dialog_close_btn"] button p {{
    margin: 0 !important;
    line-height: 1 !important;
}}
@keyframes help-overlay-drop {{
    from {{
        opacity: 0;
        transform: translateY(-28px);
    }}
    to {{
        opacity: 1;
        transform: translateY(0);
    }}
}}
section[data-testid="stSidebar"] {{
    background: {th["surface"]} !important;
    border-right: 1px solid color-mix(in srgb, {th["text"]} 10%, transparent) !important;
    min-width: 388px !important;
    max-width: 388px !important;
}}

.hero-wrap {{
    padding: 8px 0 6px 0;
    border-bottom: 1px solid color-mix(in srgb, {th["text"]} 10%, transparent);
    margin-bottom: 2rem;
    text-align: center;
}}
.hero-logo {{
    width: min(100%, 470px);
    margin: 0 auto;
    max-height: 146px;
    overflow: hidden;
}}
.hero-logo svg {{
    width: 100%;
    height: auto;
    display: block;
    transform: scaleY(0.96);
    transform-origin: center top;
}}
.hero-title {{
    font-size: clamp(2.1rem, 3vw, 2.8rem);
    font-weight: 900;
    color: {th["text"]};
    line-height: 1.02;
    margin: 0 0 8px 0;
}}

.pane {{
    background: {th["panel"]};
    border: 1px solid rgba(255,255,255,0.07);
    border-top: 3px solid {th["accent"]};
    border-radius: 6px;
    padding: 14px;
}}
.pane-title {{
    font-family: 'Source Code Pro', monospace;
    font-size: 0.94rem;
    text-transform: uppercase;
    letter-spacing: 0.16em;
    color: color-mix(in srgb, {th["accent"]} 68%, {th["text"]} 32%);
    font-weight: 800;
    margin-bottom: 10px;
}}
.agent-response-box {{
    min-height: 24vh;
    max-height: 36vh;
    overflow-y: scroll;
    scrollbar-gutter: stable;
    scrollbar-width: thin;
    scrollbar-color: color-mix(in srgb, {th["accent"]} 70%, #ffffff 30%) color-mix(in srgb, {th["surface"]} 92%, #000000 8%);
    background: {th["surface"]};
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 5px;
    padding: 12px;
    color: {th["text"]};
    font-family: 'Source Code Pro', monospace;
    font-size: 0.88rem;
    line-height: 1.45;
    white-space: pre-wrap;
}}
.agent-response-box::-webkit-scrollbar {{
    width: 10px;
}}
.agent-response-box::-webkit-scrollbar-track {{
    background: color-mix(in srgb, {th["surface"]} 94%, #000000 6%);
    border-left: 1px solid rgba(255,255,255,0.06);
}}
.agent-response-box::-webkit-scrollbar-thumb {{
    background: color-mix(in srgb, {th["accent"]} 72%, #ffffff 28%);
    border-radius: 999px;
}}
.chat-feed {{
    display: flex;
    flex-direction: column;
    gap: 10px;
}}
.msg-card {{
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 8px;
    padding: 10px 12px;
    background: {msg_card_bg};
}}
.msg-card.user {{
    border-left: 4px solid {th["accent"]};
}}
.msg-card.ai {{
    border-left: 4px solid {th["accent_soft"]};
}}
.msg-head {{
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
}}
.msg-role {{
    font-family: 'Source Code Pro', monospace;
    font-size: 0.72rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: {th["accent_soft"]};
    font-weight: 700;
}}
.msg-source {{
    font-family: 'Source Code Pro', monospace;
    font-size: 0.68rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    padding: 2px 6px;
    border-radius: 999px;
    border: 1px solid color-mix(in srgb, {th["accent"]} 45%, transparent);
    color: {th["text"]};
    background: color-mix(in srgb, {th["panel"]} 85%, {th["accent"]} 15%);
}}
.msg-text {{
    color: {th["text"]};
    font-size: 0.9rem;
    line-height: 1.45;
    white-space: pre-wrap;
    word-break: break-word;
}}
.msg-text.is-idle {{
    opacity: 0.62;
    font-style: italic;
}}
.ai-pane.is-processing {{
    border-color: color-mix(in srgb, {th["accent"]} 70%, #ffffff 30%);
    box-shadow: 0 0 0 1px color-mix(in srgb, {th["accent"]} 25%, transparent);
    animation: aiPanePulse 1.6s ease-in-out infinite;
}}
@keyframes aiPanePulse {{
    0% {{ box-shadow: 0 0 0 1px color-mix(in srgb, {th["accent"]} 18%, transparent); }}
    50% {{ box-shadow: 0 0 0 2px color-mix(in srgb, {th["accent"]} 42%, transparent); }}
    100% {{ box-shadow: 0 0 0 1px color-mix(in srgb, {th["accent"]} 18%, transparent); }}
}}
.live-log {{
    border-left: 3px solid {th["accent"]};
    background: {live_log_bg};
    border-radius: 6px;
    padding: 8px 10px;
}}
.live-tag {{
    font-family: 'Source Code Pro', monospace;
    color: {th["accent"]};
    font-size: 0.72rem;
    letter-spacing: 0.12em;
    font-weight: 700;
    margin-bottom: 4px;
}}
.msg-json {{
    margin: 0;
    padding: 10px;
    border-radius: 6px;
    border: 1px solid rgba(255,255,255,0.10);
    background: color-mix(in srgb, {th["surface"]} 88%, #000000 12%);
    color: {th["text"]};
    font-family: 'Source Code Pro', monospace;
    font-size: 0.82rem;
    line-height: 1.4;
    overflow-x: auto;
}}
.main-section-gap {{
    height: 14px;
}}
.pane-header-row {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
}}
.pane-toggle-note {{
    font-family: 'Source Code Pro', monospace;
    font-size: 0.78rem;
    color: #9f9184;
    padding: 8px 2px 2px 2px;
}}
.agent-line {{
    margin: 0 0 8px 0;
}}
.agent-role {{
    color: {th["accent_soft"]};
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-size: 0.68rem;
    margin-right: 8px;
}}
.viewport-box {{
    min-height: 58vh;
    background: {th["surface"]};
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 5px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: {th["text"]};
    font-family: 'Source Code Pro', monospace;
    font-size: 1.15rem;
}}
.viewport-empty {{
    flex-direction: column;
    gap: 8px;
    text-align: center;
    padding: 18px;
}}
.viewport-empty-icon {{
    font-size: 1.4rem;
    opacity: 0.85;
}}
.viewport-empty-title {{
    font-family: 'Source Code Pro', monospace;
    font-size: 1.02rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}}
.viewport-empty-sub {{
    font-family: 'Source Code Pro', monospace;
    font-size: 0.77rem;
    opacity: 0.72;
}}
.meta-box {{
    min-height: 58vh;
    background: {th["surface"]};
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 5px;
    padding: 12px;
    color: {th["text"]};
    font-family: 'Source Code Pro', monospace;
    word-break: break-word;
    overflow-wrap: anywhere;
}}
.meta-json-light {{
    background: color-mix(in srgb, {th["surface"]} 96%, #ffffff 4%);
    border: 1px solid rgba(0,0,0,0.10);
    border-radius: 6px;
    padding: 10px;
    white-space: pre-wrap;
    word-break: break-word;
    overflow-wrap: anywhere;
    color: {th["text"]};
    font-family: 'Source Code Pro', monospace;
    font-size: 0.80rem;
    line-height: 1.4;
}}
.meta-line {{
    margin-bottom: 4px;
}}
.meta-key {{
    color: color-mix(in srgb, {th["accent_soft"]} 76%, {th["text"]} 24%);
    letter-spacing: 0.02em;
}}
.meta-value {{
    color: {th["text"]};
}}
.meta-path {{
    word-break: break-word;
    overflow-wrap: anywhere;
}}
.image-preview-wrap {{
    min-height: 58vh;
    background: {th["surface"]};
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 5px;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 8px;
}}
.image-preview-wrap img {{
    max-width: 100%;
    max-height: 56vh;
    width: auto !important;
    height: auto !important;
    object-fit: contain !important;
}}

.sb-block {{
    background: {th["panel"]};
    border: 1px solid rgba(255,255,255,0.07);
    border-top: 3px solid {th["accent"]};
    border-radius: 6px;
    padding: 12px;
    margin-bottom: 12px;
}}
.sb-title {{
    font-family: 'Source Code Pro', monospace;
    font-size: 1.5rem;
    font-weight: 600;
    color: {th["accent_soft"]};
    letter-spacing: 0.08em;
    padding: 24px 0 14px 0;
    margin-bottom: 18px;
    border-bottom: 3px solid {th["accent"]};
    text-align: center;
    text-transform: uppercase;
}}
.ai-heart {{
    margin: 8px 0 10px 0;
    padding: 2px 2px 10px 2px;
    border-bottom: 1px solid color-mix(in srgb, {th["accent"]} 28%, transparent);
}}
.sb-sep {{
    height: 10px;
    border-bottom: 1px solid color-mix(in srgb, {th["accent"]} 22%, transparent);
    margin: 8px 0 10px 0;
}}
.ai-heart-title {{
    font-family: 'Lato', sans-serif;
    font-size: 1.5rem;
    font-weight: 900;
    letter-spacing: 0.02em;
    text-transform: uppercase;
    color: {th["text"]};
    line-height: 1.05;
}}
.sb-section {{
    font-family: 'Lato', sans-serif;
    font-size: 0.75rem;
    font-weight: 900;
    letter-spacing: 0.25em;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: {th["accent_soft"]};
    margin: 0 0 10px 0;
    padding-bottom: 7px;
    border-bottom: 1px solid rgba(232, 131, 74, 0.25);
}}
section[data-testid="stSidebar"] label {{
    color: {th["text"]} !important;
    font-size: 1rem !important;
    font-family: 'Lato', sans-serif !important;
    font-weight: 400 !important;
}}
section[data-testid="stSidebar"] p {{
    color: {th["text"]} !important;
    font-size: 1rem !important;
}}
section[data-testid="stSidebar"] .stNumberInput label {{
    color: {th["text"]} !important;
    font-size: 0.95rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.05em !important;
}}
.stNumberInput input, .stTextInput input {{
    background: {th["surface"]} !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    border-radius: 4px !important;
    color: {th["text"]} !important;
    font-family: 'Source Code Pro', monospace !important;
    font-size: 0.9rem !important;
}}
.stNumberInput input:focus, .stTextInput input:focus {{
    border-color: color-mix(in srgb, {th["accent"]} 65%, transparent) !important;
    box-shadow: 0 0 0 2px color-mix(in srgb, {th["accent"]} 20%, transparent) !important;
}}
.filter-pills {{
    list-style: none;
    margin: 2px 0 14px 0;
    padding: 0;
}}
.filter-item {{
    display: flex;
    align-items: baseline;
    gap: 8px;
    margin: 0 0 7px 0;
}}
.filter-dot {{
    color: {th["accent_soft"]};
    font-size: 0.95rem;
    line-height: 1;
}}
.pill-label {{
    font-family: 'Lato', sans-serif;
    font-size: 0.67rem;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: #9f9184;
    min-width: 82px;
}}
.pill-value {{
    font-family: 'Source Code Pro', monospace;
    font-size: 0.86rem;
    color: {th["text"]};
    line-height: 1.25;
}}
.img-list {{
    min-height: 42vh;
    max-height: 56vh;
    overflow-y: auto;
    padding: 0;
}}
.img-row {{
    font-family: 'Source Code Pro', monospace;
    font-size: 0.75rem;
    color: #c2b6ab;
    padding: 5px 2px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}
.img-row::before {{
    content: "• ";
    color: {th["accent_soft"]};
}}
.img-row:hover {{
    color: {th["text"]};
}}
.img-list-radio {{
    max-height: 56vh;
    overflow-y: auto;
    padding-right: 4px;
}}
section[data-testid="stSidebar"] div[role="radiogroup"] > label {{
    margin: 0 !important;
    padding: 6px 6px !important;
    line-height: 1.45 !important;
    border-radius: 7px !important;
    border: none !important;
}}
section[data-testid="stSidebar"] div[role="radiogroup"] > label::before {{
    content: "• ";
    color: {th["accent_soft"]};
    font-family: 'Source Code Pro', monospace;
}}
section[data-testid="stSidebar"] div[role="radiogroup"] > label > div:first-child {{
    display: none !important;
}}
section[data-testid="stSidebar"] div[role="radiogroup"] > label p {{
    font-family: 'Source Code Pro', monospace !important;
    font-size: 0.75rem !important;
    color: #c2b6ab !important;
    margin: 0 !important;
}}
section[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) p {{
    color: {th["text"]} !important;
    font-weight: 700 !important;
}}
section[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) {{
    background: color-mix(in srgb, {th["accent"]} 18%, {th["surface"]} 82%) !important;
    border: 1px solid color-mix(in srgb, {th["accent"]} 56%, transparent) !important;
}}

[class*="st-key-send_request_btn"] button {{
    background: color-mix(in srgb, {th["accent"]} 74%, {th["surface"]} 26%) !important;
    border: 1px solid color-mix(in srgb, {th["accent"]} 86%, transparent) !important;
    color: #111 !important;
    font-weight: 800 !important;
}}
[class*="st-key-send_request_btn"] button:hover {{
    background: color-mix(in srgb, {th["accent"]} 84%, {th["surface"]} 16%) !important;
}}
[class*="st-key-stop_request_btn"] button {{
    background: transparent !important;
    border: 1px solid color-mix(in srgb, {th["accent"]} 36%, transparent) !important;
    color: color-mix(in srgb, {th["text"]} 82%, #000000 18%) !important;
    font-weight: 500 !important;
}}
[class*="st-key-stop_request_btn"] button:hover {{
    background: color-mix(in srgb, {th["surface"]} 80%, #000000 20%) !important;
}}
.sidebar-help {{
    margin: 6px 0 12px 0;
    font-size: 0.78rem;
    color: #9f9184;
}}
[class*="st-key-settings_icon_btn"] button,
[class*="st-key-settings-icon-btn"] button {{
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    color: {th["accent_soft"]} !important;
    width: 50px !important;
    height: 50px !important;
    min-height: 50px !important;
    padding: 0 !important;
    line-height: 1 !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
}}
[class*="st-key-settings_icon_btn"] button:hover,
[class*="st-key-settings-icon-btn"] button:hover {{
    color: {th["text"]} !important;
    transform: none !important;
}}
[class*="st-key-settings_icon_btn"] button p,
[class*="st-key-settings-icon-btn"] button p {{
    font-size: 2.3rem !important;
    line-height: 1 !important;
    margin: 0 !important;
}}
[class*="st-key-toggle_preview_btn"] button,
[class*="st-key-toggle_metadata_btn"] button {{
    background: transparent !important;
    border: none !important;
    border-radius: 0 !important;
    box-shadow: none !important;
    color: color-mix(in srgb, {th["accent_soft"]} 88%, #ffffff) !important;
    width: 32px !important;
    height: 28px !important;
    min-height: 28px !important;
    padding: 0 !important;
    line-height: 1 !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
}}
[class*="st-key-toggle_preview_btn"] button:hover,
[class*="st-key-toggle_metadata_btn"] button:hover {{
    color: {th["text"]} !important;
    background: transparent !important;
    transform: none !important;
}}
[class*="st-key-toggle_preview_btn"] button p,
[class*="st-key-toggle_metadata_btn"] button p {{
    font-family: 'Source Code Pro', monospace !important;
    font-weight: 900 !important;
    font-size: 1.3rem !important;
    line-height: 1 !important;
    margin: 0 !important;
}}
.hint {{
    margin-top: 8px;
    color: #9c9188;
    font-size: 0.82rem;
}}

@media (max-width: 980px) {{
    section[data-testid="stSidebar"] {{
        min-width: auto !important;
        max-width: none !important;
    }}
    .viewport-box, .meta-box {{
        min-height: 32vh;
    }}
}}
</style>
"""
