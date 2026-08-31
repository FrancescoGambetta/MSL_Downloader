"""Catalog Manager: the Streamlit dashboard for maintaining the two local catalogs
(`Catalog_PDS.parquet`/`.json` and `Catalog_RawArch.parquet`/`.json`) that MSL Downloader
(`app/`) reads from. Run standalone on its own port (see `Run_CatalogManager.bat` /
`catalog-manager` in `.claude/launch.json`), separate from MSL Downloader's own app.

What it lets a user do, roughly top-to-bottom: first-run setup (download the official
PDS/RAW releases, optionally generate their local JSON views -- see `render_initial_setup`,
`distribution.py`, `bootstrap.py`); per-catalog dashboard cards showing local vs. remote
freshness (`render_catalog`, backed by `services.py`); run/monitor/cancel integrity checks,
updates, repairs, and customizations, each as a detached subprocess job tracked via
`catalog_manager/jobs.py`'s job-state files (`render_integrity_panel`,
`render_catalog_update_progress`, `render_repair_progress`,
`render_customization_progress`); browse what's actually in a catalog by filename-segment
breakdown (`render_product_composition`, backed by `product_composition.py`); and apply a
per-camera product-type/processing-level selection (`render_*_customization`, one per camera
shape, backed by `customization.py`).

`jobs.py` and `customization.py` are loaded here via `importlib.util.spec_from_file_location`
(by file path) rather than a normal `from catalog_manager.jobs import ...` package import --
an existing pattern in this file, left as-is rather than changed in this documentation pass.
Reuses `app/`'s own `Styles/` (CSS, theming) and `runtime.py` (UI config load/save) via a
`sys.path` insert, so both dashboards share one visual style -- but i18n is this module's
own: `tr()` looks up UI strings from this file's own `TEXT` dict, extended at import time
with `i18n_catalog.py`'s `EXTRA_TRANSLATIONS` (translations added after the first UI pass).
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import zlib
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import pyarrow.parquet as pq
import streamlit as st
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
CATALOG_MANAGER_DIR = Path(__file__).resolve().parent
PREVIEW_PLACEHOLDER = CATALOG_MANAGER_DIR / "assets" / "preview_placeholder.jpg"
PREVIEW_ASSET_DIR = CATALOG_MANAGER_DIR / "assets" / "pds_product_examples"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from Styles.css import build_app_css  # noqa: E402
from Styles.themes import (  # noqa: E402
    DEFAULT_MODE,
    DEFAULT_THEME_BY_MODE,
    MODE_THEMES,
    get_theme,
    normalize_mode,
    theme_names,
)
from runtime import load_app_ui_config, save_app_ui_config  # noqa: E402
from catalog_manager.bootstrap import load_bootstrap_state, save_bootstrap_choice  # noqa: E402
from catalog_manager.i18n_catalog import EXTRA_TRANSLATIONS  # noqa: E402
from catalog_manager.product_composition import build_inventory  # noqa: E402
from catalog_manager.services import (  # noqa: E402
    CatalogStatus,
    attach_remote_status,
    fetch_raw_remote_status,
    fetch_pds_remote_status,
    format_bytes,
    inspect_catalog,
    save_status_report,
)
from catalog_manager.distribution import (  # noqa: E402
    fetch_remote_pds_manifest,
    fetch_remote_raw_manifest,
    install_remote_pds_release,
    install_remote_raw_release,
    local_pds_release,
    local_raw_release,
)
_jobs_spec = importlib.util.spec_from_file_location("msl_catalog_manager_jobs", CATALOG_MANAGER_DIR / "jobs.py")
if _jobs_spec is None or _jobs_spec.loader is None:
    raise ImportError("Unable to load catalog_manager/jobs.py")
_jobs_module = importlib.util.module_from_spec(_jobs_spec)
_jobs_spec.loader.exec_module(_jobs_module)
_customization_spec = importlib.util.spec_from_file_location(
    "msl_catalog_manager_customization", CATALOG_MANAGER_DIR / "customization.py"
)
if _customization_spec is None or _customization_spec.loader is None:
    raise ImportError("Unable to load catalog_manager/customization.py")
_customization_module = importlib.util.module_from_spec(_customization_spec)
_customization_spec.loader.exec_module(_customization_module)
CAMERA_OPTIONS = _customization_module.CAMERA_OPTIONS
CUSTOMIZABLE_CAMERAS = _customization_module.CUSTOMIZABLE_CAMERAS
current_camera_options = _customization_module.current_camera_options
NAVCAM_COMPATIBILITY = _customization_module.NAVCAM_COMPATIBILITY
PDS_CAMERA_COMPATIBILITY = _customization_module.PDS_CAMERA_COMPATIBILITY
active_job_for_catalog = _jobs_module.active_job_for_catalog
estimate_integrity_seconds = _jobs_module.estimate_integrity_seconds
last_integrity_sol = _jobs_module.last_integrity_sol
latest_job = _jobs_module.latest_job
load_job = _jobs_module.load_job
request_cancel = _jobs_module.request_cancel
recent_jobs = _jobs_module.recent_jobs
resumable_job = _jobs_module.resumable_job
start_pds_integrity_job = _jobs_module.start_pds_integrity_job
start_raw_integrity_job = _jobs_module.start_raw_integrity_job
start_pds_repair_job = _jobs_module.start_pds_repair_job
start_raw_repair_job = _jobs_module.start_raw_repair_job
start_pds_update_job = _jobs_module.start_pds_update_job
start_raw_update_job = _jobs_module.start_raw_update_job
start_pds_customization_job = _jobs_module.start_pds_customization_job
customization_resumable = _jobs_module.customization_resumable
start_pds_customization_resume_job = _jobs_module.start_pds_customization_resume_job
start_pds_failed_retry = _jobs_module.start_pds_failed_retry
start_pds_resume_job = _jobs_module.start_pds_resume_job
start_raw_failed_retry = _jobs_module.start_raw_failed_retry
start_raw_resume_job = _jobs_module.start_raw_resume_job
start_pds_json_rebuild_job = _jobs_module.start_pds_json_rebuild_job
start_raw_json_rebuild_job = _jobs_module.start_raw_json_rebuild_job
start_bootstrap_json_job = _jobs_module.start_bootstrap_json_job


st.set_page_config(page_title="MSL Catalog Manager", page_icon="🗂️", layout="wide", initial_sidebar_state="collapsed")


def _preview_manifest_path() -> Path | None:
    """Locate the product-preview-image manifest (bundled assets first, falling back to the analysis-output copy), or `None` if neither exists."""
    candidates = (
        PREVIEW_ASSET_DIR / "manifest.json",
        PROJECT_ROOT / "analysis_output" / "pds_product_examples" / "manifest.json",
    )
    return next((path for path in candidates if path.is_file()), None)


@st.cache_resource(show_spinner=False)
def _load_preview_examples(manifest_name: str, modified_ns: int) -> tuple[Path, list[dict]]:
    """Load and cache the preview manifest's `"ok"` examples (`modified_ns` is a cache-busting key, unused otherwise -- the standard `st.cache_data`/`st.cache_resource` mtime-keying pattern)."""
    del modified_ns
    manifest_path = Path(manifest_name)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    examples = [item for item in payload.get("examples", []) if item.get("status") == "ok"]
    return manifest_path.parent, examples


@st.cache_data(show_spinner=False)
def _preview_pixel_area(filename: str, modified_ns: int) -> int:
    """Return the real preview area so thumbnails never win a generic match."""
    del modified_ns
    path = Path(filename)
    try:
        with Image.open(path) as image:
            return int(image.width) * int(image.height)
    except Exception:
        return 0


def _preview_example(camera: str, product: str, combination: str) -> tuple[Path | None, dict | None]:
    """Pick the manifest example that best matches `camera`+`product`+`combination`: rank by matching technical-code tokens, prefer the highest-resolution image among ties, and (for Navcam's generic family buttons) prefer visually distinct scenes; the final tie-break among equally good candidates is a stable hash of the request so the same input always picks the same example. Returns `(image_path, manifest_entry)`, `(None, None)` if nothing matches."""
    manifest_path = _preview_manifest_path()
    if manifest_path is None:
        return None, None
    base_dir, examples = _load_preview_examples(str(manifest_path), manifest_path.stat().st_mtime_ns)
    camera_key = camera.strip().lower().replace(" ", "")
    aliases = {"chemcam": "chemcam", "mastcam": "mastcam", "mahli": "mahli", "mardi": "mardi",
               "navcam": "navcam", "hazcam": "hazcam"}
    camera_key = aliases.get(camera_key, camera_key)
    candidates = [item for item in examples if str(item.get("camera", "")).lower() == camera_key]
    if not candidates:
        return None, None

    # Codes passed by the UI (C00, DRCL, ILT/LF, MXY...) are more reliable than
    # translated display labels. Rank exact tuple fields first, then product IDs.
    requested = [value.strip().upper() for value in (product, combination) if value.strip()]
    code_tokens: list[str] = []
    for value in requested:
        code_tokens.extend(token for token in re.findall(r"[A-Z0-9_]+", value) if any(ch.isdigit() for ch in token) or len(token) <= 6)
    joined_request = "".join(code_tokens)

    # An empty display product means that ``combination`` is an explicit
    # technical key supplied by the UI.  Never substitute a merely similar
    # product in that case: a missing preview is preferable to a wrong one.
    if not product and code_tokens:
        exact_candidates = []
        for item in candidates:
            fields = [str(value).upper() for value in item.get("combination", [])]
            product_id = str(item.get("product_id", "")).upper()
            haystack = "|".join(fields) + "|" + product_id
            if all(token in haystack for token in code_tokens):
                exact_candidates.append(item)
        if not exact_candidates:
            return None, None
        candidates = exact_candidates

    def match_score(item: dict) -> int:
        fields = [str(value).upper() for value in item.get("combination", [])]
        product_id = str(item.get("product_id", "")).upper()
        haystack = "|".join(fields) + "|" + product_id
        score = 0
        for token in code_tokens:
            if token in fields:
                score += 30
            elif token in haystack:
                score += 12
        if joined_request and joined_request in haystack.replace("_", ""):
            score += 25
        return score

    # First preserve technical correctness, then prefer the largest real
    # image.  Previously the filename broke ties and could select a 64x64
    # thumbnail even when a full-resolution example was available.
    best_score = max(match_score(item) for item in candidates)
    candidates = [item for item in candidates if match_score(item) == best_score]
    areas = {
        str(item.get("preview", "")): _preview_pixel_area(
            str(base_dir / str(item.get("preview", ""))),
            (base_dir / str(item.get("preview", ""))).stat().st_mtime_ns
            if (base_dir / str(item.get("preview", ""))).is_file() else 0,
        )
        for item in candidates
    }
    best_area = max(areas.values(), default=0)
    if best_area:
        candidates = [item for item in candidates if areas[str(item.get("preview", ""))] == best_area]

    # The generic Navcam family buttons need genuinely useful examples, not
    # three processing products derived from the very same exposure. Keep the
    # best resolution, but deliberately choose different observed scenes.
    if camera_key == "navcam":
        family = next((code for code in ("EDR", "ILT", "RAD") if code in code_tokens), "")
        if family and combination.strip().upper() == family and candidates:
            sols = [int(item.get("sol", 0) or 0) for item in candidates]
            target_sol = min(sols) if family == "EDR" else max(sols)
            at_sol = [item for item in candidates if int(item.get("sol", 0) or 0) == target_sol]
            if at_sol:
                candidates = at_sol
            preferred_prefix = {"EDR": "NLB", "ILT": "NLB", "RAD": "NAB"}[family]
            at_camera = [
                item for item in candidates
                if str(item.get("product_id", "")).upper().startswith(preferred_prefix + "_")
            ]
            if at_camera:
                candidates = at_camera

    # When several equally good full-size examples exist, use a stable but
    # product-specific choice. EDR, ILT and RAD therefore do not all show the
    # same scene merely because their filenames sort similarly.
    candidates = sorted(candidates, key=lambda item: str(item.get("preview", "")))
    seed = "|".join((camera_key, product.upper(), combination.upper(), joined_request))
    chosen = candidates[zlib.crc32(seed.encode("utf-8")) % len(candidates)]
    preview_path = base_dir / str(chosen.get("preview", ""))
    return (preview_path if preview_path.is_file() else None), chosen


@st.dialog("Preview", width="large")
def show_product_preview(
    camera: str, product: str, combination: str = "", match_key: str = ""
) -> None:
    """Show the NASA example that best matches the selected product combination."""
    title = f"{camera.upper()} · {product}"
    if combination:
        title += f" · {combination}"
    st.markdown(f"### {title}")
    preview_path, example = _preview_example(
        camera, "" if match_key else product, match_key or combination
    )
    if preview_path is not None:
        st.image(str(preview_path), width="stretch")
    elif PREVIEW_PLACEHOLDER.exists():
        st.image(str(PREVIEW_PLACEHOLDER), width="stretch")
    else:
        st.warning("Preview placeholder missing")
    notes = {
        "it": "Esempio reale proveniente dall’archivio NASA PDS.",
        "en": "Real example from the NASA PDS archive.",
        "fr": "Exemple réel provenant de l’archive NASA PDS.",
        "es": "Ejemplo real procedente del archivo NASA PDS.",
        "de": "Reales Beispiel aus dem NASA-PDS-Archiv.",
    }
    if example is not None:
        st.caption(f"{notes.get(st.session_state.get('lang', 'en'), notes['en'])} · Sol {example.get('sol', '—')} · {example.get('product_id', '')}")
    else:
        fallback = {
            "it": "Esempio NASA non disponibile per questa selezione.", "en": "NASA example unavailable for this selection.",
            "fr": "Exemple NASA indisponible pour cette sélection.", "es": "Ejemplo NASA no disponible para esta selección.",
            "de": "NASA-Beispiel für diese Auswahl nicht verfügbar.",
        }
        st.caption(fallback.get(st.session_state.get("lang", "en"), fallback["en"]))


def preview_button(
    container: object, camera: str, product: str, combination: str, key: str,
    match_key: str = "",
) -> None:
    """Render a small "Preview" button in `container` that opens `show_product_preview`'s dialog for this camera/product/combination when clicked."""
    labels = {"it": "Anteprima", "en": "Preview", "fr": "Aperçu", "es": "Vista previa", "de": "Vorschau"}
    label = labels.get(st.session_state.get("lang", "en"), "Preview")
    if container.button(label, key=f"preview_{key}", icon="🖼️"):
        show_product_preview(camera, product, combination, match_key)

SUPPORTED_LANGS = ["it", "en", "fr", "es", "de"]

# UI translation strings for this dashboard's own controls (a separate table from
# app/i18n_app.json -- Catalog Manager owns its own i18n). Extended below with
# i18n_catalog.py's EXTRA_TRANSLATIONS (strings added after the first UI pass);
# looked up by tr(key), which defaults to "it" then falls back to "en" for any
# key missing in the current language.
TEXT = {
    "it": {
        "app_name": "CATALOG MANAGER", "subtitle": "Controlla e aggiorna i cataloghi utilizzati da MSL Downloader.",
        "config": "Configurazioni", "appearance": "Aspetto e lingua", "appearance_hint": "Le impostazioni grafiche sono condivise con l’app principale.",
        "mode": "Modalità", "dark": "Scura", "light": "Chiara", "language": "Lingua", "dark_theme": "Tema modalità scura",
        "light_theme": "Tema modalità chiara", "save": "Salva configurazione", "saved": "Configurazione salvata.",
        "overview": "Controllo cataloghi", "overview_hint": "Interroga separatamente il server PDS e il manifest RAW NASA, senza modificare i cataloghi.",
        "check": "Controlla cataloghi e sito NASA", "checking": "Controllo in corso…", "last_nasa": "Ultimo Sol NASA",
        "healthy": "Cataloghi locali validi", "updates": "Cataloghi da aggiornare", "total": "Prodotti complessivi",
        "valid": "Catalogo locale valido", "invalid": "Catalogo locale non valido", "available": "Aggiornamento disponibile",
        "aligned": "Coperto fino all’ultimo Sol NASA", "remote_error": "Sito NASA non raggiungibile", "not_checked": "Sito NASA non ancora controllato",
        "products": "Prodotti", "range": "Sol dei prodotti", "scanned": "Ultimo Sol controllato", "remote": "Ultimo Sol sul server", "size": "Dimensione",
        "local_section": "Integrità locale", "duplicates": "URL duplicati", "null_urls": "URL mancanti", "null_ids": "Product ID mancanti",
        "modified": "Ultima modifica", "camera_table": "Distribuzione per camera", "camera": "Camera", "count": "Prodotti",
        "update": "Aggiorna questo catalogo", "update_pending": "Il motore di aggiornamento sicuro è la prossima fase e non è ancora attivo.",
        "meaning": "Cosa significa?", "product_sol_note": "“Sol dei prodotti” indica dove esistono immagini. “Ultimo Sol controllato” indica fin dove il builder ha verificato il server. Lo stato di aggiornamento confronta quest’ultimo valore con la sorgente NASA corretta.",
        "remote_camera": "Ultimo Sol sul server per camera",
        "local_checked": "Controllato localmente", "camera_status": "Stato", "ok_short": "Aggiornato", "new_short": "Nuovi Sol",
        "local_coverage": "Catalogo locale", "server_coverage": "Server NASA", "check_one": "Controlla aggiornamenti",
        "catalog_details": "Dettagli del catalogo", "new_cameras": "Nuovi Sol rilevati per", "no_new": "Nessun nuovo Sol rilevato.",
        "partial": "Controllo parziale", "partial_hint": "Alcune camere non sono state verificate perché il server NASA è temporaneamente occupato. Riprova tra poco.",
        "technical_details": "Dettagli tecnici dell’errore",
        "integrity": "Controllo integrità", "integrity_camera": "Camera", "sol_from": "Dal Sol", "sol_to": "Al Sol",
        "integrity_start": "Avvia controllo", "integrity_confirm": "Conferma controllo integrità",
        "integrity_question": "Questo processo impiegherà circa {estimate}. Vuoi procedere comunque?",
        "read_only_note": "Il controllo è in sola lettura e non modificherà il catalogo.", "cancel": "Annulla", "proceed": "Procedi",
        "job_running": "Controllo in corso", "job_completed": "Controllo completato", "job_partial": "Controllo parziale",
        "job_failed": "Controllo fallito", "refresh": "Aggiorna stato", "stop_job": "Interrompi dopo il Sol corrente",
        "locations": "Gruppi di prodotti NASA controllati", "missing_found": "Prodotti mancanti", "failed_locations": "Controlli NASA non completati",
        "estimated_remaining": "Tempo rimanente", "integrity_aligned": "Il catalogo è allineato per il range controllato.",
        "retrying_failed": "Secondo tentativo sui controlli NASA non completati",
        "completed_in": "Durata totale", "retry_failed": "Riprova i {count} controlli NASA non completati",
        "partial_integrity_note": "Il controllo è parziale: NASA non ha risposto per {count} gruppi di prodotti. Non significa che manchino dal catalogo; occorre soltanto riprovare questi controlli.",
        "integrity_missing_note": "Il catalogo non ha {count} prodotti che risultano presenti su NASA.",
        "repair_start": "Ripara {count} prodotti mancanti", "repair_busy_hint": "Un altro processo PDS è già in corso; attendi che finisca.",
        "repair_running": "Riparazione in corso",
        "repair_phase_loading_integrity_result": "Lettura dei prodotti mancanti dal controllo integrità",
        "repair_phase_scanning_nasa": "Riscansione delle sole cartelle NASA interessate",
        "repair_phase_enriching_metadata": "Arricchimento metadati e geolocalizzazione",
        "repair_phase_validating_working_copy": "Validazione della copia riparata",
        "repair_phase_installing_catalog": "Installazione del catalogo riparato",
        "repair_cancelled": "Riparazione interrotta.", "repair_failed": "Riparazione fallita",
        "repair_complete": "Riparazione completata: {count} prodotti aggiunti.",
        "repair_still_missing": "Attenzione: {count} prodotti risultano ancora mancanti (potrebbero non essere più disponibili su NASA).",
        "initial_check_time": "Controllo iniziale", "recovery_time": "Recupero controlli rimasti", "combined_time": "Tempo complessivo",
        "final_comparison": "Confronto finale", "history": "Cronologia controlli", "history_type": "Tipo",
        "history_result": "Risultato", "history_range": "Intervallo", "history_duration": "Durata",
        "full_check": "Controllo completo", "targeted_retry": "Recupero mirato", "resumed_check": "Controllo ripreso",
        "resume_check": "Riprendi dall’ultimo checkpoint", "checkpoint_note": "I progressi vengono salvati ogni 20 gruppi di prodotti NASA.",
        "official_release": "Catalogo ufficiale PDS", "drive_source": "Release pubblica su Google Drive",
        "local_release": "Release installata", "remote_release": "Release disponibile", "not_registered": "Catalogo locale non ancora registrato",
        "sync_official": "Sincronizza catalogo ufficiale", "syncing_official": "Download e verifica del catalogo PDS…",
        "official_ready": "Il catalogo PDS ufficiale è installato e verificato.", "official_installed": "Catalogo PDS installato e verificato.",
        "official_installed_raw": "Catalogo RAW Archive installato e verificato.",
        "official_registered": "Il Parquet locale coincideva già con la release Drive: è stato verificato e registrato senza riscaricarlo.",
        "official_current": "Il catalogo locale coincide già con la release Drive.", "download_progress": "Download catalogo PDS",
        "source_unavailable": "Release Drive non raggiungibile",
        "official_release_raw": "Catalogo ufficiale RAW Archive", "official_ready_raw": "Il catalogo RAW ufficiale è installato e verificato.",
        "syncing_official_raw": "Download e verifica del catalogo RAW…", "download_progress_raw": "Download catalogo RAW",
        "json_local_title": "JSON locale modificabile", "json_local_missing": "Il Parquet è già utilizzabile. Genera il JSON solo se vuoi aggiornare o modificare il catalogo localmente.",
        "json_generate": "Genera JSON locale", "json_confirm_title": "Generare il JSON PDS?",
        "json_confirm_text": "La ricostruzione richiede indicativamente 1–3 minuti, circa 600 MB di spazio libero e può utilizzare molta memoria. Il processo continuerà in background.",
        "json_confirm_text_raw": "La ricostruzione richiede indicativamente 4–7 minuti e circa 1,6 GB di spazio libero. Il processo streaming continuerà in background.",
        "json_start": "Avvia ricostruzione", "json_running": "Ricostruzione JSON in corso", "json_ready": "Il JSON locale è pronto.",
        "json_failed": "Ricostruzione JSON fallita", "json_rows": "Prodotti scritti", "json_camera": "Camera corrente",
        "first_start": "Configurazione iniziale", "first_start_hint": "Installa i cataloghi ufficiali necessari a MSL Downloader.",
        "catalog_required": "Cataloghi obbligatori", "installed_short": "Installato", "missing_short": "Da installare",
        "install_pds": "Installa catalogo PDS", "install_raw": "Installa catalogo RAW Archive",
        "json_choice_title": "Vuoi generare anche i JSON locali?",
        "json_choice_text": "Senza JSON puoi già cercare e scaricare le immagini presenti nei cataloghi. I JSON sono necessari soltanto per aggiornare o modificare i cataloghi localmente.",
        "generate_both_json": "Sì, genera i JSON", "download_only": "No, userò solo il download",
        "bootstrap_generating": "Preparazione dei JSON locali", "bootstrap_complete": "Configurazione iniziale completata.",
    },
    "en": {
        "app_name": "CATALOG MANAGER", "subtitle": "Check and update the catalogs used by MSL Downloader.", "config": "Configurations",
        "appearance": "Appearance and language", "appearance_hint": "Visual settings are shared with the main application.", "mode": "Mode",
        "dark": "Dark", "light": "Light", "language": "Language", "dark_theme": "Dark-mode theme", "light_theme": "Light-mode theme",
        "save": "Save configuration", "saved": "Configuration saved.", "overview": "Overall status",
        "overview_hint": "Local checks never modify files. The NASA check requires internet access.", "check": "Check catalogs and NASA website",
        "checking": "Checking…", "last_nasa": "Latest NASA Sol", "healthy": "Valid local catalogs", "updates": "Catalogs requiring update",
        "total": "Total products", "valid": "Local catalog valid", "invalid": "Local catalog invalid", "available": "Update available",
        "aligned": "Covered through latest NASA Sol", "remote_error": "NASA website unavailable", "not_checked": "NASA website not checked yet",
        "products": "Products", "range": "Product Sol range", "scanned": "Last checked Sol", "remote": "Latest server Sol", "size": "Size",
        "local_section": "Local integrity", "duplicates": "Duplicate URLs", "null_urls": "Missing URLs", "null_ids": "Missing product IDs",
        "modified": "Last modified", "camera_table": "Camera distribution", "camera": "Camera", "count": "Products",
        "update": "Update this catalog", "update_pending": "The safe update engine is the next phase and is not active yet.",
        "meaning": "What does this mean?", "product_sol_note": "Product Sols show where images exist. Last checked Sol shows how far the builder inspected the server. Update status compares that value with the correct NASA source.", "remote_camera": "Latest server Sol by camera", "local_checked": "Checked locally", "camera_status": "Status", "ok_short": "Up to date", "new_short": "New Sols",
        "local_coverage": "Local catalog", "server_coverage": "NASA server", "check_one": "Check for updates",
        "catalog_details": "Catalog details", "new_cameras": "New Sols detected for", "no_new": "No new Sols detected.",
        "partial": "Partial check", "partial_hint": "Some cameras could not be checked because the NASA server is temporarily busy. Please try again shortly.",
        "technical_details": "Technical error details",
        "integrity": "Integrity check", "integrity_camera": "Camera", "sol_from": "From Sol", "sol_to": "To Sol",
        "integrity_start": "Start check", "integrity_confirm": "Confirm integrity check",
        "integrity_question": "This process will take approximately {estimate}. Do you want to proceed?",
        "read_only_note": "The check is read-only and will not modify the catalog.", "cancel": "Cancel", "proceed": "Proceed",
        "job_running": "Check in progress", "job_completed": "Check completed", "job_partial": "Partial check",
        "job_failed": "Check failed", "refresh": "Refresh status", "stop_job": "Stop after current Sol",
        "locations": "NASA product groups checked", "missing_found": "Missing products", "failed_locations": "Incomplete NASA checks",
        "estimated_remaining": "Time remaining", "integrity_aligned": "The catalog is aligned for the checked range.",
        "retrying_failed": "Second attempt on incomplete NASA checks",
        "completed_in": "Total duration", "retry_failed": "Retry the {count} incomplete NASA checks",
        "partial_integrity_note": "The check is partial: NASA did not respond for {count} product groups. This does not mean they are missing from the catalog; these checks only need to be retried.",
        "integrity_missing_note": "The catalog is missing {count} products that exist on NASA's servers.",
        "repair_start": "Repair {count} missing products", "repair_busy_hint": "Another PDS job is already running; wait for it to finish.",
        "repair_running": "Repair in progress",
        "repair_phase_loading_integrity_result": "Reading missing products from the integrity check",
        "repair_phase_scanning_nasa": "Rescanning just the affected NASA folders",
        "repair_phase_enriching_metadata": "Enriching metadata and geolocation",
        "repair_phase_validating_working_copy": "Validating the repaired copy",
        "repair_phase_installing_catalog": "Installing the repaired catalog",
        "repair_cancelled": "Repair stopped.", "repair_failed": "Repair failed",
        "repair_complete": "Repair complete: {count} products added.",
        "repair_still_missing": "Note: {count} products are still missing (they may no longer be available on NASA's servers).",
        "initial_check_time": "Initial check", "recovery_time": "Remaining-check recovery", "combined_time": "Combined time",
        "final_comparison": "Final comparison", "history": "Check history", "history_type": "Type",
        "history_result": "Result", "history_range": "Range", "history_duration": "Duration",
        "full_check": "Full check", "targeted_retry": "Targeted recovery", "resumed_check": "Resumed check",
        "resume_check": "Resume from latest checkpoint", "checkpoint_note": "Progress is saved every 20 NASA product groups.",
        "official_release": "Official PDS catalog", "drive_source": "Public Google Drive release",
        "local_release": "Installed release", "remote_release": "Available release", "not_registered": "Local catalog not registered yet",
        "sync_official": "Synchronize official catalog", "syncing_official": "Downloading and validating the PDS catalog…",
        "official_ready": "The official PDS catalog is installed and verified.", "official_installed": "PDS catalog installed and verified.",
        "official_installed_raw": "RAW Archive catalog installed and verified.",
        "official_registered": "The local Parquet already matched the Drive release. It was verified and registered without downloading it again.",
        "official_current": "The local catalog already matches the Drive release.", "download_progress": "PDS catalog download",
        "source_unavailable": "Drive release unavailable",
        "official_release_raw": "Official RAW Archive catalog", "official_ready_raw": "The official RAW catalog is installed and verified.",
        "syncing_official_raw": "Downloading and verifying the RAW catalog…", "download_progress_raw": "RAW catalog download",
        "json_local_title": "Editable local JSON", "json_local_missing": "The Parquet is ready to use. Generate JSON only if you want to update or customize the catalog locally.",
        "json_generate": "Generate local JSON", "json_confirm_title": "Generate the PDS JSON?",
        "json_confirm_text": "Reconstruction usually takes 1–3 minutes, needs about 600 MB of free space, and may use significant memory. It will continue in the background.",
        "json_confirm_text_raw": "Reconstruction usually takes 4–7 minutes and needs about 1.6 GB of free space. The streaming process will continue in the background.",
        "json_start": "Start reconstruction", "json_running": "JSON reconstruction in progress", "json_ready": "The local JSON is ready.",
        "json_failed": "JSON reconstruction failed", "json_rows": "Products written", "json_camera": "Current camera",
        "first_start": "Initial setup", "first_start_hint": "Install the official catalogs required by MSL Downloader.",
        "catalog_required": "Required catalogs", "installed_short": "Installed", "missing_short": "Install required",
        "install_pds": "Install PDS catalog", "install_raw": "Install RAW Archive catalog",
        "json_choice_title": "Do you also want to generate the local JSON files?",
        "json_choice_text": "Without JSON files you can already search and download images in the catalogs. JSON files are required only to update or modify catalogs locally.",
        "generate_both_json": "Yes, generate JSON files", "download_only": "No, download only",
        "bootstrap_generating": "Preparing local JSON files", "bootstrap_complete": "Initial setup completed.",
    },
    "fr": {"app_name": "CATALOG MANAGER", "subtitle": "Contrôlez et mettez à jour les catalogues utilisés par MSL Downloader.", "config": "Configurations", "appearance": "Apparence et langue", "appearance_hint": "Les réglages visuels sont partagés avec l’application principale.", "mode": "Mode", "dark": "Sombre", "light": "Clair", "language": "Langue", "dark_theme": "Thème sombre", "light_theme": "Thème clair", "save": "Enregistrer", "saved": "Configuration enregistrée.", "overview": "État général", "overview_hint": "Le contrôle local ne modifie aucun fichier.", "check": "Contrôler les catalogues et le site NASA", "checking": "Contrôle…", "last_nasa": "Dernier Sol NASA", "healthy": "Catalogues locaux valides", "updates": "Catalogues à mettre à jour", "total": "Produits totaux", "valid": "Catalogue local valide", "invalid": "Catalogue local invalide", "available": "Mise à jour disponible", "aligned": "Couvert jusqu’au dernier Sol NASA", "remote_error": "Site NASA inaccessible", "not_checked": "Site NASA non contrôlé", "products": "Produits", "range": "Plage de Sol", "scanned": "Sols avec produits", "remote": "Dernier Sol NASA", "size": "Taille", "local_section": "Intégrité locale", "duplicates": "URL dupliquées", "null_urls": "URL manquantes", "null_ids": "Product ID manquants", "modified": "Dernière modification", "camera_table": "Répartition par caméra", "camera": "Caméra", "count": "Produits", "update": "Mettre à jour ce catalogue", "update_pending": "Le moteur de mise à jour sécurisée sera ajouté à l’étape suivante.", "meaning": "Que signifie ceci ?", "product_sol_note": "Le Sol maximal des produits peut être inférieur au dernier Sol contrôlé."},
    "es": {"app_name": "CATALOG MANAGER", "subtitle": "Comprueba y actualiza los catálogos utilizados por MSL Downloader.", "config": "Configuraciones", "appearance": "Apariencia e idioma", "appearance_hint": "Los ajustes visuales se comparten con la aplicación principal.", "mode": "Modo", "dark": "Oscuro", "light": "Claro", "language": "Idioma", "dark_theme": "Tema oscuro", "light_theme": "Tema claro", "save": "Guardar", "saved": "Configuración guardada.", "overview": "Estado general", "overview_hint": "La comprobación local no modifica archivos.", "check": "Comprobar catálogos y sitio NASA", "checking": "Comprobando…", "last_nasa": "Último Sol NASA", "healthy": "Catálogos locales válidos", "updates": "Catálogos por actualizar", "total": "Productos totales", "valid": "Catálogo local válido", "invalid": "Catálogo local no válido", "available": "Actualización disponible", "aligned": "Cubierto hasta el último Sol NASA", "remote_error": "Sitio NASA no disponible", "not_checked": "Sitio NASA aún no comprobado", "products": "Productos", "range": "Rango de Sol", "scanned": "Soles con productos", "remote": "Último Sol NASA", "size": "Tamaño", "local_section": "Integridad local", "duplicates": "URL duplicadas", "null_urls": "URL ausentes", "null_ids": "Product ID ausentes", "modified": "Última modificación", "camera_table": "Distribución por cámara", "camera": "Cámara", "count": "Productos", "update": "Actualizar este catálogo", "update_pending": "El motor de actualización segura se añadirá en la siguiente fase.", "meaning": "¿Qué significa?", "product_sol_note": "El Sol máximo de los productos puede ser inferior al último Sol comprobado."},
    "de": {"app_name": "CATALOG MANAGER", "subtitle": "Prüft und aktualisiert die von MSL Downloader verwendeten Kataloge.", "config": "Konfigurationen", "appearance": "Darstellung und Sprache", "appearance_hint": "Die Darstellungseinstellungen werden mit der Haupt-App geteilt.", "mode": "Modus", "dark": "Dunkel", "light": "Hell", "language": "Sprache", "dark_theme": "Dunkles Theme", "light_theme": "Helles Theme", "save": "Speichern", "saved": "Konfiguration gespeichert.", "overview": "Gesamtstatus", "overview_hint": "Die lokale Prüfung verändert keine Dateien.", "check": "Kataloge und NASA-Webseite prüfen", "checking": "Prüfung…", "last_nasa": "Letzter NASA-Sol", "healthy": "Gültige lokale Kataloge", "updates": "Zu aktualisierende Kataloge", "total": "Produkte insgesamt", "valid": "Lokaler Katalog gültig", "invalid": "Lokaler Katalog ungültig", "available": "Update verfügbar", "aligned": "Bis zum letzten NASA-Sol abgedeckt", "remote_error": "NASA-Webseite nicht erreichbar", "not_checked": "NASA-Webseite noch nicht geprüft", "products": "Produkte", "range": "Sol-Bereich", "scanned": "Sols mit Produkten", "remote": "Letzter NASA-Sol", "size": "Größe", "local_section": "Lokale Integrität", "duplicates": "Doppelte URLs", "null_urls": "Fehlende URLs", "null_ids": "Fehlende Product IDs", "modified": "Letzte Änderung", "camera_table": "Verteilung nach Kamera", "camera": "Kamera", "count": "Produkte", "update": "Diesen Katalog aktualisieren", "update_pending": "Die sichere Update-Engine folgt im nächsten Schritt.", "meaning": "Was bedeutet das?", "product_sol_note": "Der maximale Produkt-Sol kann unter dem zuletzt geprüften Sol liegen."},
}

for _language, _translations in EXTRA_TRANSLATIONS.items():
    TEXT[_language].update(_translations)


def tr(key: str) -> str:
    """Translate `key` into the current session's UI language (`st.session_state["lang"]`, defaulting to `"it"`), falling back to English and finally to `key` itself if untranslated anywhere."""
    lang = st.session_state.get("lang", "it")
    return TEXT.get(lang, TEXT["en"]).get(key, TEXT["en"].get(key, key))


def format_duration(seconds: int | float | None) -> str:
    """Format a duration estimate coarsely (e.g. `"2 h 15 min"`, `"5 min"`) -- used for the "this will take about..." confirmation text, not for precise elapsed-time display (see `format_elapsed`)."""
    if seconds is None:
        return "—"
    value = max(0, int(seconds))
    hours, remainder = divmod(value, 3600)
    minutes = max(1, remainder // 60) if value else 0
    if hours:
        return f"{hours} h {minutes} min"
    return f"{minutes} min"


def format_elapsed(seconds: int | float | None) -> str:
    """Format an elapsed duration precisely (e.g. `"1 h 2 min 3 s"`), for a running/finished job's live timer."""
    if seconds is None:
        return "—"
    value = max(0, int(round(float(seconds))))
    hours, remainder = divmod(value, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours} h")
    if minutes:
        parts.append(f"{minutes} min")
    if secs or not parts:
        parts.append(f"{secs} s")
    return " ".join(parts)


def _live_job_elapsed(job: dict) -> float:
    """Return a live duration even when the worker has not rewritten its state yet."""
    stored = float(job.get("elapsed_seconds") or 0)
    if str(job.get("status") or "") not in {"queued", "running", "cancelling"}:
        return stored
    started_text = str(job.get("started_at_utc") or job.get("created_at_utc") or "").strip()
    if not started_text:
        return stored
    try:
        started = datetime.fromisoformat(started_text.replace("Z", "+00:00"))
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        return max(stored, (datetime.now(timezone.utc) - started).total_seconds())
    except ValueError:
        return stored


def _job_log_snapshot(job_id: str, max_bytes: int = 96_000) -> tuple[str, int | None, str | None]:
    """Read only the end of a job log and infer its latest Sol/camera."""
    path = PROJECT_ROOT / "data" / "catalog" / "jobs" / "logs" / f"{job_id}.log"
    if not path.is_file():
        return "", None, None
    with path.open("rb") as stream:
        size = stream.seek(0, 2)
        stream.seek(max(0, size - max_bytes))
        text = stream.read().decode("utf-8", errors="replace")
    sols = re.findall(r"(?:SOL|sol)[_\-/]?(\d{1,5})", text)
    camera = None
    upper = text.upper()
    for marker, name in (
        ("MSLHAZ", "HAZCAM"), ("RHAZ", "HAZCAM"), ("FHAZ", "HAZCAM"),
        ("MSLNAV", "NAVCAM"), ("NAV_", "NAVCAM"),
        ("CHEMCAM", "CHEMCAM"), ("MSLCCAM", "CHEMCAM"),
        ("MASTCAM", "MASTCAM"), ("MSLMST", "MASTCAM"),
        ("MAHLI", "MAHLI"), ("MARDI", "MARDI"),
    ):
        if marker in upper:
            camera = name
    return text, (int(sols[-1]) if sols else None), camera


def job_lineage(job: dict) -> list[dict]:
    """Walk `job`'s `retry_of`/`resume_of` chain back to the original attempt, returning the full lineage oldest-first (for the dashboard's job-history display)."""
    chain = [job]
    seen = {str(job.get("job_id", ""))}
    current = job
    while current.get("retry_of") or current.get("resume_of"):
        parent_id = str(current.get("retry_of") or current.get("resume_of"))
        if not parent_id or parent_id in seen:
            break
        parent = load_job(parent_id)
        if not parent:
            break
        chain.append(parent)
        seen.add(parent_id)
        current = parent
    return list(reversed(chain))


@st.dialog("MSL", width="small")
def confirm_integrity_job(catalog: str, camera: str, sol_start: int, sol_end: int, estimate: str) -> None:
    """Modal: confirm and launch an integrity-check job for `catalog`/`camera`/Sol range, showing the time `estimate` first (via `estimate_integrity_seconds`)."""
    catalog_label = "PDS" if catalog == "pds" else "RAW Archive"
    st.markdown(f"### {tr('integrity_confirm')}")
    st.write(tr("integrity_question").format(estimate=estimate))
    st.caption(f"{catalog_label} · {camera.upper()} · Sol {sol_start}–{sol_end}")
    st.info(tr("read_only_note"))
    cancel_col, proceed_col = st.columns(2)
    if cancel_col.button(tr("cancel"), key=f"integrity_cancel_{catalog}", width="stretch"):
        st.rerun()
    if proceed_col.button(tr("proceed"), key=f"integrity_proceed_{catalog}", type="primary", width="stretch"):
        try:
            job = start_pds_integrity_job(camera, sol_start, sol_end) if catalog == "pds" else start_raw_integrity_job(camera, sol_start, sol_end)
            st.session_state[f"integrity_job_id_{catalog}"] = job["job_id"]
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))


@st.dialog("MSL", width="small")
def confirm_catalog_update(catalog: str, sol_start: int, sol_end: int, cameras: list[str], estimate: str) -> None:
    """Modal: confirm and launch a catalog-update job (PDS: exactly one camera; RAW: one or more) over the given Sol range."""
    catalog_label = "PDS" if catalog == "pds" else "RAW Archive"
    st.markdown(f"### {tr('update_confirm_title').replace('PDS', catalog_label)}")
    st.write(tr("update_confirm_text").format(estimate=estimate))
    st.caption(f"{catalog_label} · Sol {sol_start}–{sol_end} · {', '.join(camera.upper() for camera in cameras)}")
    st.info(tr("update_staging_note"))
    cancel_col, proceed_col = st.columns(2)
    if cancel_col.button(tr("cancel"), key=f"{catalog}_update_cancel", width="stretch"):
        st.rerun()
    if proceed_col.button(tr("proceed"), key=f"{catalog}_update_proceed", type="primary", width="stretch"):
        try:
            job = start_pds_update_job(sol_start, sol_end, cameras[0]) if catalog == "pds" else start_raw_update_job(sol_start, sol_end, cameras)
            st.session_state[f"{catalog}_update_job_id"] = job["job_id"]
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))


@st.fragment(run_every="2s")
def render_catalog_update_progress(catalog: str) -> None:
    """Self-refreshing (every 2s) progress panel for `catalog`'s most recent update job: live progress bar (Sol-based during scanning, product-count-based during metadata enrichment), live log tail, a Stop button, and a final success/failure/cancelled summary once done."""
    job_id = st.session_state.get(f"{catalog}_update_job_id")
    job = load_job(job_id) if job_id else latest_job(catalog, operation="catalog_update")
    if not job:
        return
    status = str(job.get("status") or "")

    # The Aggiorna buttons live in render_catalog(), outside this
    # self-refreshing fragment, so their disabled= state (based on whether a
    # job is still active) only gets recomputed on a full app rerun. Force
    # exactly one full rerun the first time this fragment observes the job
    # leave queued/running, so the buttons unlock without the user having to
    # click something unrelated (e.g. "Controlla aggiornamenti") first.
    actual_job_id = str(job.get("job_id") or "")
    if actual_job_id and status not in {"queued", "running", "cancelling"}:
        rerun_flag = f"_update_job_rerun_done::{catalog}::{actual_job_id}"
        if not st.session_state.get(rerun_flag):
            st.session_state[rerun_flag] = True
            st.rerun()

    if status in {"queued", "running"}:
        label = tr("update_running").replace("PDS", "PDS" if catalog == "pds" else "RAW Archive")
        st.markdown(f"**{label}**")
        phase = str(job.get("phase") or "")
        phase_text = tr(f"update_phase_{phase}") if phase else tr("update_running")
        log_text, current_sol, current_camera = _job_log_snapshot(str(job.get("job_id") or ""))
        sol_start = int(job.get("sol_start") or 0)
        sol_end = int(job.get("sol_end") or sol_start)
        detail = phase_text
        if phase == "enriching_metadata":
            # The Sol/discovery scan for this camera is already finished at
            # this point, so a Sol-based bar would stay pinned near 100% for
            # the whole (much slower) metadata/geo enrichment phase. Use the
            # real per-product counter reported by the job instead.
            lbl_done = job.get("lbl_candidates_done")
            lbl_total = job.get("lbl_candidates_total")
            progress = 0.0
            if isinstance(lbl_done, (int, float)) and isinstance(lbl_total, (int, float)) and lbl_total > 0:
                progress = max(0.0, min(1.0, lbl_done / lbl_total))
                detail += f" · {int(lbl_done):,}/{int(lbl_total):,}".replace(",", ".")
            if job.get("current_camera"):
                detail += f" · {job.get('current_camera')}"
        else:
            progress = 0.0
            if current_sol is not None and sol_end > sol_start:
                progress = max(0.0, min(1.0, (current_sol - sol_start + 1) / (sol_end - sol_start + 1)))
            if current_camera:
                detail += f" · {current_camera}"
            if current_sol is not None:
                detail += f" · Sol {current_sol}/{sol_end}"
        st.progress(progress, text=detail)
        st.caption(f"{tr('elapsed_live')}: {format_elapsed(_live_job_elapsed(job))}")
        with st.expander(tr("live_log_title"), expanded=False):
            st.caption(tr("live_log_hint"))
            if log_text.strip():
                visible_lines = log_text.strip().splitlines()[-80:]
                st.code("\n".join(visible_lines), language=None)
            else:
                st.caption(tr("live_log_waiting"))
        if st.button(tr("stop_update_job"), key=f"{catalog}_update_stop", disabled=status == "cancelling"):
            request_cancel(str(job["job_id"]))
            st.rerun()
        return
    if status == "cancelled":
        st.warning(tr("update_cancelled"))
        return
    if status == "failed":
        st.error(f"{tr('update_failed')}: {job.get('error', '—')}")
        return
    if status == "completed":
        additions = job.get("additions_by_camera") or {}
        total = int(job.get("new_products") or 0)
        st.success(tr("update_scan_complete").format(count=f"{total:,}".replace(",", ".")))
        if additions:
            summary = " · ".join(f"{camera.upper()}: +{int(count):,}".replace(",", ".") for camera, count in additions.items())
            st.caption(summary)
        st.info(tr("update_installed"))


def render_repair_progress(catalog: str = "pds") -> None:
    """Progress panel for `catalog`'s most recent repair job: current phase, a Stop button while running, and a final added/still-missing summary once done."""
    job_id = st.session_state.get(f"repair_job_id_{catalog}")
    job = load_job(job_id) if job_id else latest_job(catalog, operation="repair")
    if not job:
        return
    status = str(job.get("status") or "")
    camera = str(job.get("camera") or "").upper()

    if status in {"queued", "running", "cancelling"}:
        st.markdown(f"**{tr('repair_running')}**")
        phase = str(job.get("phase") or "")
        phase_key = f"repair_phase_{phase}"
        phase_text = tr(phase_key) if phase else tr("repair_running")
        detail = f"{phase_text} · {camera}" if camera else phase_text
        st.caption(detail)
        st.caption(f"{tr('elapsed_live')}: {format_elapsed(_live_job_elapsed(job))}")
        if st.button(tr("stop_update_job"), key=f"repair_stop_{job.get('job_id')}", disabled=status == "cancelling"):
            request_cancel(str(job["job_id"]))
            st.rerun()
        return
    if status == "cancelled":
        st.warning(tr("repair_cancelled"))
        return
    if status == "failed":
        st.error(f"{tr('repair_failed')}: {job.get('error', '—')}")
        return
    if status == "completed":
        added = int(job.get("new_products") or 0)
        still_missing = int(job.get("still_missing") or 0)
        st.success(tr("repair_complete").format(count=added))
        if still_missing:
            st.warning(tr("repair_still_missing").format(count=still_missing))


@st.fragment(run_every="2s")
def render_integrity_panel(status: CatalogStatus) -> None:
    """The full integrity-check UI for one catalog: camera/Sol-range picker defaulting to "pick up where the last check left off" (via `last_integrity_sol`), a Start button, live progress for a running check, and on completion a missing/local-only summary with Retry-failed / Resume / Repair actions as applicable."""
    catalog = status.key
    session_key = f"integrity_job_id_{catalog}"
    cameras = [camera for camera in ("mastcam", "mahli", "navcam", "hazcam", "mardi", "chemcam") if camera in (status.cameras or {})]
    camera = st.selectbox(tr("integrity_camera"), cameras, format_func=str.upper, key=f"integrity_camera_{catalog}")
    default_end = int((status.camera_last_checked or {}).get(camera, status.last_checked_sol or 0))
    # Default "Dal Sol" to right after the last finished integrity check for
    # this camera, so a repeat check picks up where the previous one left
    # off instead of re-scanning the whole mission by default every time.
    last_checked = last_integrity_sol(catalog, camera)
    default_start = min(last_checked + 1, default_end) if last_checked is not None else 0
    start_col, end_col = st.columns(2)
    sol_start = int(start_col.number_input(tr("sol_from"), min_value=0, value=default_start, step=1, key=f"integrity_sol_start_{catalog}"))
    sol_end = int(end_col.number_input(tr("sol_to"), min_value=0, value=default_end, step=1, key=f"integrity_sol_end_{catalog}"))
    low, high = estimate_integrity_seconds(catalog, camera, sol_start, sol_end)
    estimate = f"{format_duration(low)}–{format_duration(high)}"
    if st.button(tr("integrity_start"), key=f"integrity_start_{catalog}", width="stretch"):
        confirm_integrity_job(catalog, camera, min(sol_start, sol_end), max(sol_start, sol_end), estimate)

    job = active_job_for_catalog(catalog)
    if job is not None and job.get("operation") != "integrity_check":
        # An update or repair job can also be "the" active job for this
        # catalog; this panel only ever tracks an integrity_check here
        # (repair has its own progress block below).
        job = None
    if job is None and st.session_state.get(session_key):
        job = load_job(st.session_state[session_key])
    if job is None:
        job = latest_job(catalog)
    if not job:
        return

    current_status = str(job.get("status", ""))
    phase = str(job.get("phase", ""))
    is_retry_phase = phase == "retrying_failed_locations" or bool(job.get("targeted_retry"))
    titles = {
        "queued": tr("job_running"), "running": tr("job_running"), "cancelling": tr("job_running"),
        "completed": tr("job_completed"), "partial": tr("job_partial"), "failed": tr("job_failed"),
        "cancelled": tr("cancel"),
    }
    title = tr("retrying_failed") if current_status in {"queued", "running", "cancelling"} and is_retry_phase else titles.get(current_status, current_status)
    st.markdown(f"<div class='job-title'>{escape(title)}</div>", unsafe_allow_html=True)
    if phase == "retrying_failed_locations":
        total = int(job.get("retry_locations_total") or 0)
        done = int(job.get("retry_locations_done") or 0)
    else:
        total = int(job.get("locations_total") or 0)
        done = int(job.get("locations_done") or 0)
    if not total:
        total = int(job.get("collections_total") or 0)
        done = int(job.get("collections_done") or 0)
    if total:
        st.progress(min(1.0, done / total), text=f"{tr('locations')}: {done}/{total}")
    metric_left, metric_right = st.columns(2)
    metric_left.metric(tr("missing_found"), int(job.get("missing_products") or 0))
    metric_right.metric(tr("failed_locations"), int(job.get("failed_locations") or 0))
    if current_status in {"queued", "running", "cancelling"}:
        st.caption(f"{tr('estimated_remaining')}: {format_duration(job.get('estimated_remaining_seconds'))}")
        if job.get("checkpoint_interval"):
            st.caption(tr("checkpoint_note"))
        refresh_col, stop_col = st.columns(2)
        if refresh_col.button(tr("refresh"), key=f"integrity_refresh_{catalog}", width="stretch"):
            st.rerun()
        if stop_col.button(tr("stop_job"), key=f"integrity_stop_{catalog}", width="stretch", disabled=current_status == "cancelling"):
            request_cancel(str(job["job_id"]))
            st.rerun()
    elif current_status in {"completed", "partial", "failed", "cancelled"}:
        st.caption(f"{tr('completed_in')}: {format_elapsed(job.get('elapsed_seconds'))}")
        lineage = job_lineage(job)
        if len(lineage) > 1:
            initial_seconds = float(lineage[0].get("elapsed_seconds") or 0)
            recovery_seconds = sum(float(item.get("elapsed_seconds") or 0) for item in lineage[1:])
            summary_left, summary_middle, summary_right = st.columns(3)
            summary_left.metric(tr("initial_check_time"), format_elapsed(initial_seconds))
            summary_middle.metric(tr("recovery_time"), format_elapsed(recovery_seconds))
            summary_right.metric(tr("combined_time"), format_elapsed(initial_seconds + recovery_seconds))
        if current_status in {"completed", "partial"}:
            local_count = int(job.get("local_products") or 0)
            remote_count = int(job.get("remote_products") or 0)
            st.caption(f"{tr('final_comparison')}: {remote_count:,}/{local_count:,}".replace(",", "."))
        missing_count = int(job.get("missing_products") or 0)
        if current_status == "completed" and missing_count == 0:
            st.success(tr("integrity_aligned"))
        if current_status == "partial":
            failed_count = int(job.get("failed_locations") or 0)
            st.warning(tr("partial_integrity_note").format(count=failed_count))
            retry_label = tr("retry_failed").format(count=failed_count)
            if failed_count and st.button(retry_label, key=f"integrity_retry_{job.get('job_id')}", width="stretch"):
                try:
                    retry_job = start_pds_failed_retry(str(job["job_id"])) if catalog == "pds" else start_raw_failed_retry(str(job["job_id"]))
                    st.session_state[session_key] = retry_job["job_id"]
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))
        elif current_status == "failed" and job.get("error"):
            st.error(str(job["error"]))
        if current_status in {"cancelled", "failed"} and resumable_job(str(job.get("job_id", ""))):
            if st.button(tr("resume_check"), key=f"integrity_resume_{job.get('job_id')}", width="stretch"):
                try:
                    resumed = start_pds_resume_job(str(job["job_id"])) if catalog == "pds" else start_raw_resume_job(str(job["job_id"]))
                    st.session_state[session_key] = resumed["job_id"]
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))
        if current_status in {"completed", "partial"} and missing_count > 0:
            st.warning(tr("integrity_missing_note").format(count=missing_count))
            other_job = active_job_for_catalog(catalog)
            repair_busy = other_job is not None
            if st.button(
                tr("repair_start").format(count=missing_count), key=f"integrity_repair_{job.get('job_id')}",
                width="stretch", disabled=repair_busy,
                help=tr("repair_busy_hint") if repair_busy else None,
            ):
                try:
                    repair_job = start_pds_repair_job(str(job["job_id"])) if catalog == "pds" else start_raw_repair_job(str(job["job_id"]))
                    st.session_state[f"repair_job_id_{catalog}"] = repair_job["job_id"]
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))

    render_repair_progress(catalog)

    with st.expander(tr("history"), expanded=False):
        history_rows = []
        status_names = {
            "completed": tr("job_completed"), "partial": tr("job_partial"),
            "failed": tr("job_failed"), "cancelled": tr("cancel"),
            "running": tr("job_running"), "queued": tr("job_running"),
        }
        for item in recent_jobs(catalog, limit=8):
            kind = tr("targeted_retry") if item.get("retry_of") else tr("resumed_check") if item.get("resume_of") else tr("full_check")
            created = str(item.get("created_at_utc") or "").replace("T", " ")[:19]
            history_rows.append(
                {
                    tr("history_type"): kind,
                    tr("camera"): str(item.get("camera") or "").upper(),
                    tr("history_range"): f"{item.get('sol_start', '—')}–{item.get('sol_end', '—')}",
                    tr("history_result"): status_names.get(str(item.get("status")), str(item.get("status") or "—")),
                    tr("history_duration"): format_elapsed(item.get("elapsed_seconds")),
                    tr("modified"): created,
                }
            )
        st.dataframe(history_rows, hide_index=True, width="stretch")


def hero_logo_html(mode: str, theme_name: str) -> str:
    """Render the shared Title.svg without importing the main app runtime."""
    title_path = PROJECT_ROOT / "Title.svg"
    if not title_path.exists():
        return ""
    try:
        svg = title_path.read_text(encoding="utf-8")
    except Exception:
        return ""
    theme = get_theme(mode, theme_name)
    accent = theme.get("accent", "#c77d2b")
    text = theme.get("text", "#f5efe4")
    svg = svg.replace("</svg>", f"<style>.cls-1{{fill:{accent};}}.cls-2{{fill:{text};}}</style></svg>", 1)
    return f'<div class="hero-logo">{svg}</div>'


@st.cache_data(show_spinner=False)
def _inspect_cached(path_text: str, key: str, modified_ns: int) -> CatalogStatus:
    """Cached wrapper around `inspect_catalog`, keyed by the file's own mtime."""
    # modified_ns is intentionally part of the cache key: a replaced catalog
    # is re-read automatically, while ordinary UI interactions stay instant.
    del modified_ns
    return inspect_catalog(Path(path_text), key)


def load_local() -> list[CatalogStatus]:
    """Inspect both local catalogs (PDS, RAW), returning `[pds_status, raw_status]`."""
    pds_path = PROJECT_ROOT / "data/catalog/Catalog_PDS.parquet"
    raw_path = PROJECT_ROOT / "data/catalog/Catalog_RawArch.parquet"
    return [
        _inspect_cached(str(pds_path), "pds", pds_path.stat().st_mtime_ns if pds_path.exists() else -1),
        _inspect_cached(str(raw_path), "raw", raw_path.stat().st_mtime_ns if raw_path.exists() else -1),
    ]


@st.cache_data(show_spinner=False, ttl=300)
def _remote_pds_release_cached() -> dict:
    """Fetch the remote PDS release manifest, cached for 5 minutes."""
    return fetch_remote_pds_manifest(PROJECT_ROOT)


@st.cache_data(show_spinner=False, ttl=300)
def _remote_raw_release_cached() -> dict:
    """Fetch the remote RAW release manifest, cached for 5 minutes."""
    return fetch_remote_raw_manifest(PROJECT_ROOT)


@st.dialog("MSL", width="small")
def confirm_json_rebuild(catalog: str) -> None:
    """Modal: confirm and launch a JSON-rebuild job for `catalog`."""
    label = "PDS" if catalog == "pds" else "RAW Archive"
    st.markdown(f"### {tr('json_confirm_title').replace('PDS', label)}")
    st.write(tr("json_confirm_text_raw") if catalog == "raw" else tr("json_confirm_text"))
    cancel_col, proceed_col = st.columns(2)
    if cancel_col.button(tr("cancel"), key=f"json_rebuild_cancel_{catalog}", width="stretch"):
        st.rerun()
    if proceed_col.button(tr("json_start"), key=f"json_rebuild_confirm_{catalog}", type="primary", width="stretch"):
        try:
            job = start_pds_json_rebuild_job() if catalog == "pds" else start_raw_json_rebuild_job()
            st.session_state[f"{catalog}_json_rebuild_job_id"] = job["job_id"]
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))


@st.fragment(run_every="2s")
def render_json_panel(catalog: str) -> None:
    """Self-refreshing panel for `catalog`'s editable local JSON: a ready/missing summary, a Generate button when missing, and live rows-written progress while a rebuild job runs."""
    json_name = "Catalog_PDS.json" if catalog == "pds" else "Catalog_RawArch.json"
    json_path = PROJECT_ROOT / "data" / "catalog" / json_name
    job = None
    job_id = st.session_state.get(f"{catalog}_json_rebuild_job_id")
    if job_id:
        job = load_job(str(job_id))
    if not job:
        job = latest_job(catalog, operation="json_rebuild")

    st.markdown(f"#### {tr('json_local_title')}")
    if json_path.exists() and (not job or job.get("status") != "running"):
        st.success(f"{tr('json_ready')} ({format_bytes(json_path.stat().st_size)})")
        return
    if job and job.get("status") in {"queued", "running"}:
        done = int(job.get("rows_done") or 0)
        total = int(job.get("rows_total") or 0)
        st.markdown(f"**{tr('json_running')}**")
        if total:
            st.progress(min(1.0, done / total), text=f"{done:,}/{total:,}".replace(",", "."))
        else:
            st.progress(0.0, text=tr("json_running"))
        left, right = st.columns(2)
        left.metric(tr("json_rows"), f"{done:,}".replace(",", "."))
        right.metric(tr("json_camera"), str(job.get("camera") or "—").upper())
        st.caption(f"{tr('estimated_remaining')}: {format_duration(job.get('estimated_remaining_seconds'))}")
        return
    if job and job.get("status") == "failed":
        st.error(f"{tr('json_failed')}: {job.get('error', '')}")
    elif job and job.get("status") == "completed" and not json_path.exists():
        st.error(tr("json_failed"))
    st.info(tr("json_local_missing"))
    active = active_job_for_catalog(catalog)
    if st.button(tr("json_generate"), key=f"generate_{catalog}_json", width="stretch", disabled=bool(active)):
        confirm_json_rebuild(catalog)


def render_pds_json_panel() -> None:
    """`render_json_panel("pds")` -- kept as its own named function since it's used as a callback/render target in a couple of places where a plain partial would be less readable."""
    render_json_panel("pds")


@st.dialog("MSL Catalogs", width="medium")
def show_catalog_guide() -> None:
    """Modal: explain the fast-vs-Parquet-vs-JSON catalog concepts to a first-time user (dismissed once, tracked via `st.session_state.catalog_guide_seen`)."""
    st.markdown(f"## {tr('catalog_guide_title')}")
    st.write(tr("catalog_guide_intro"))
    st.markdown(f"**{tr('catalog_guide_fast')}**")
    st.write(tr("catalog_guide_fast_text"))
    st.markdown(f"**{tr('catalog_guide_parquet')}**")
    st.write(tr("catalog_guide_parquet_text"))
    st.markdown(f"**{tr('catalog_guide_json')}**")
    st.write(tr("catalog_guide_json_text"))
    st.info(tr("catalog_guide_privacy"))
    if st.button(tr("catalog_guide_close"), key="close_catalog_guide", type="primary", width="stretch"):
        st.session_state.catalog_guide_seen = True
        st.rerun()


def render_official_release_panel() -> None:
    """The PDS "official release" card: compare the locally installed release id against the latest one on Drive, and offer a Sync button (streams the download with a progress bar, then re-validates and re-inspects) when they differ."""
    try:
        remote_manifest = _remote_pds_release_cached()
        remote_error = ""
    except Exception as exc:  # noqa: BLE001
        remote_manifest = None
        remote_error = f"{type(exc).__name__}: {exc}"
    local_manifest = local_pds_release(PROJECT_ROOT)
    local_id = str((local_manifest or {}).get("release", {}).get("release_id") or "")
    remote_id = str((remote_manifest or {}).get("release", {}).get("release_id") or "")

    with st.container(border=True):
        st.markdown(f"### {tr('official_release')}")
        st.caption(tr("drive_source"))
        local_col, remote_col = st.columns(2)
        local_col.metric(tr("local_release"), local_id or tr("not_registered"))
        remote_col.metric(tr("remote_release"), remote_id or "—")
        notice = st.session_state.pop("distribution_notice", None)
        if notice:
            st.success(tr(str(notice)))
        if remote_error:
            st.warning(f"{tr('source_unavailable')}: {remote_error}")
            return
        if local_id and local_id == remote_id:
            st.success(tr("official_ready"))
            render_pds_json_panel()
            return
        if st.button(tr("sync_official"), key="sync_official_pds", type="primary", width="stretch"):
            bar = st.progress(0.0, text=tr("syncing_official"))

            def update_progress(downloaded: int, total: int | None) -> None:
                """`distribution._download_file`'s progress callback: update the download progress bar in MB."""
                if total:
                    ratio = min(1.0, downloaded / total)
                    bar.progress(ratio, text=f"{tr('download_progress')}: {downloaded / 1048576:.1f}/{total / 1048576:.1f} MB")
                else:
                    bar.progress(0.0, text=f"{tr('download_progress')}: {downloaded / 1048576:.1f} MB")

            try:
                result = install_remote_pds_release(PROJECT_ROOT, update_progress)
                messages = {
                    "installed": "official_installed",
                    "registered_existing": "official_registered",
                    "already_current": "official_current",
                }
                st.session_state.distribution_notice = messages.get(str(result.get("status")), "official_installed")
                _remote_pds_release_cached.clear()
                _inspect_cached.clear()
                st.session_state.catalog_statuses = load_local()
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))


def render_raw_official_release_panel() -> None:
    """RAW-catalog counterpart of `render_official_release_panel`."""
    try:
        remote_manifest = _remote_raw_release_cached()
        remote_error = ""
    except Exception as exc:  # noqa: BLE001
        remote_manifest = None
        remote_error = f"{type(exc).__name__}: {exc}"
    local_manifest = local_raw_release(PROJECT_ROOT)
    local_id = str((local_manifest or {}).get("release", {}).get("release_id") or "")
    remote_id = str((remote_manifest or {}).get("release", {}).get("release_id") or "")

    with st.container(border=True):
        st.markdown(f"### {tr('official_release_raw')}")
        st.caption(tr("drive_source"))
        local_col, remote_col = st.columns(2)
        local_col.metric(tr("local_release"), local_id or tr("not_registered"))
        remote_col.metric(tr("remote_release"), remote_id or "—")
        notice = st.session_state.pop("raw_distribution_notice", None)
        if notice:
            st.success(tr(str(notice)))
        if remote_error:
            st.warning(f"{tr('source_unavailable')}: {remote_error}")
            return
        if local_id and local_id == remote_id:
            st.success(tr("official_ready_raw"))
            render_json_panel("raw")
            return
        if st.button(tr("sync_official"), key="sync_official_raw", type="primary", width="stretch"):
            bar = st.progress(0.0, text=tr("syncing_official_raw"))

            def update_progress(downloaded: int, total: int | None) -> None:
                if total:
                    ratio = min(1.0, downloaded / total)
                    bar.progress(ratio, text=f"{tr('download_progress_raw')}: {downloaded / 1048576:.1f}/{total / 1048576:.1f} MB")
                else:
                    bar.progress(0.0, text=f"{tr('download_progress_raw')}: {downloaded / 1048576:.1f} MB")

            try:
                result = install_remote_raw_release(PROJECT_ROOT, update_progress)
                messages = {
                    "installed": "official_installed_raw",
                    "registered_existing": "official_registered",
                    "already_current": "official_current",
                }
                st.session_state.raw_distribution_notice = messages.get(str(result.get("status")), "official_installed_raw")
                _remote_raw_release_cached.clear()
                _inspect_cached.clear()
                st.session_state.catalog_statuses = load_local()
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))


@st.cache_data(show_spinner=False)
def _composition_inventory(path_text: str, modified_ns: int, catalog: str = "pds", schema_version: int = 3) -> dict:
    """Cached wrapper around `product_composition.build_inventory`, keyed by the file's mtime (`schema_version` busts the cache when this wrapper's own shape changes)."""
    del modified_ns, schema_version
    return build_inventory(Path(path_text), catalog)


@st.cache_data(show_spinner=False)
def _current_camera_options(
    path_text: str, modified_ns: int, schema_version: int = 2
) -> dict[str, dict[str, set[str]]]:
    """Cached wrapper around `customization.current_camera_options`, keyed by the file's mtime."""
    del schema_version
    return current_camera_options(Path(path_text))


@st.cache_data(show_spinner=False)
def _catalog_sol_range(path_text: str, modified_ns: int) -> tuple[int, int]:
    """Return `(min_sol, max_sol)` across the whole catalog, cached by the file's mtime."""
    # Backs the "Applica modifiche" Sol range default -- must cover the whole
    # mission, since a newly-selected combination can legitimately sit at any
    # Sol, not just a recent one.
    del modified_ns
    table = pq.read_table(path_text, columns=["sol"])
    sols = [int(value) for value in table["sol"].to_pylist() if value is not None]
    return (min(sols), max(sols)) if sols else (0, 0)


def _segment_explanation(dimension: str, code: str) -> str:
    """Look up the human-readable explanation for one filename-segment code (e.g. what `"E01"`'s product type means), per its `dimension` (product_type/suffix/processing_marker/...); falls back to a generic "unrecognised code" note when no specific translation exists."""
    if dimension == "product_type":
        return tr(f"product_type_{code}")
    if dimension == "product_variant" and len(code) == 3:
        return f"{code[0]} — {tr(f'product_type_{code[0]}')}\n\n{code[1]} — {tr('gop_note')}\n\n{code[2]} — {tr('version_note')}"
    if dimension == "product_variant" and len(code) == 2:
        return f"{code[0]} — {tr(f'product_type_{code[0]}')}\n\n{code[1]} — {tr('version_note')}"
    if dimension == "gop_counter":
        return tr("gop_note")
    if dimension == "version":
        return tr("version_note")
    if dimension == "suffix":
        details = [f"{letter} — {tr(f'process_{letter}')}" for letter in code if f"process_{letter}" in TEXT[st.session_state.lang]]
        return f"{tr('suffix_note')}\n\n" + "\n\n".join(details)
    if dimension == "processing_marker":
        marker_key = f"marker_{code}"
        return tr(marker_key) if marker_key in TEXT[st.session_state.lang] else tr("generic_code_note")
    if dimension == "camera_prefix":
        return tr("prefix_note")
    if dimension == "file_format":
        return tr("file_format_note")
    if dimension == "sample_type":
        sample_key = f"sample_{code}"
        return tr(sample_key) if sample_key in TEXT[st.session_state.lang] else tr("generic_code_note")
    return tr("generic_code_note")


@st.dialog("MSL", width="medium")
def show_segment_detail(camera: str, segment: dict) -> None:
    """Modal: show one filename-segment code's full explanation and product count, opened by clicking a segment button/badge."""
    dimension = str(segment["dimension"])
    code = str(segment["code"])
    st.markdown(f"## `{escape(code)}`")
    st.caption(f"{camera.upper()} · {tr(f'role_{dimension}')} · {int(segment['count']):,} {tr('composition_products').lower()}".replace(",", "."))
    st.write(_segment_explanation(dimension, code))


def _render_product_composition_content(catalog: str) -> None:
    """Render the "what's actually in this catalog" tab for one catalog: per-camera filename-segment breakdowns as clickable code buttons/badges (`render_segment_group`), plus for PDS a plain-language summary sentence per camera built from whatever segment codes the catalog currently contains (never a hardcoded list, so it can't describe something no longer there or omit something newly added)."""
    st.caption(tr("composition_hint"))
    parquet = PROJECT_ROOT / "data" / "catalog" / ("Catalog_PDS.parquet" if catalog == "PDS" else "Catalog_RawArch.parquet")
    if not parquet.exists():
        st.warning(tr("catalog_required"))
        return
    inventory_catalog_key = "pds" if catalog == "PDS" else "raw"
    with st.spinner(tr("composition_loading")):
        inventory = _composition_inventory(str(parquet), parquet.stat().st_mtime_ns, inventory_catalog_key)
    camera_order = ["mastcam", "mahli", "navcam", "hazcam", "chemcam", "mardi"]
    cameras = [camera for camera in camera_order if camera in inventory] + sorted(set(inventory) - set(camera_order))
    primary_dimensions = ("file_format", "sample_type", "product_type", "suffix", "processing_marker")
    technical_dimensions = ("product_variant", "camera_prefix", "instrument_product", "gop_counter", "version")

    def render_segment_group(camera: str, dimension: str, segments: list[dict], *, technical: bool) -> None:
        """Render one dimension's segments as a row of code buttons (few segments) or a select+open control (many), each opening `show_segment_detail` on click."""
        if not segments:
            return
        st.markdown(f"**{tr(f'role_{dimension}')}**")
        if len(segments) <= 24:
            columns = st.columns(min(4, len(segments)))
            for index, segment in enumerate(segments):
                code = str(segment["code"])
                description = tr(f"product_type_{code}") if dimension == "product_type" else ""
                label_parts = [code]
                if description:
                    label_parts.append(description)
                label_parts.append(f"{int(segment['count']):,}".replace(",", "."))
                label = " · ".join(label_parts)
                key = f"segment_{catalog}_{camera}_{dimension}_{code}_{'tech' if technical else 'main'}"
                if columns[index % len(columns)].button(label, key=key, width="stretch"):
                    show_segment_detail(camera, segment)
        else:
            options = {f"{item['code']} · {int(item['count']):,}".replace(",", "."): item for item in segments}
            selected = st.selectbox(tr(f"role_{dimension}"), list(options), key=f"segment_select_{catalog}_{camera}_{dimension}", label_visibility="collapsed")
            if st.button(tr("composition_open"), key=f"segment_open_{catalog}_{camera}_{dimension}", width="stretch"):
                show_segment_detail(camera, options[selected])

    st.html(
        """
        <style>
        .composition-summary {position:relative; margin:0 0 .65rem; padding:.8rem 1rem 2.55rem;
            border:1px solid rgba(128,128,128,.18); border-radius:.45rem; font-size:1rem; line-height:1.7;}
        .composition-summary::after {content:attr(data-hint); position:absolute; left:1rem; right:1rem; bottom:.65rem;
            color:rgba(128,128,128,.82); font-size:.78rem; line-height:1.25;}
        .composition-code {display:inline; color:inherit; font-family:monospace; font-weight:700; white-space:nowrap;
            border-bottom:1px dotted #9b6a32; cursor:help;}
        .composition-code::after {content:attr(data-tooltip); visibility:hidden; opacity:0; position:absolute; z-index:2;
            left:1rem; right:1rem; bottom:.55rem; padding:.08rem 0; background:var(--background-color, transparent);
            color:#9b6a32; font-family:sans-serif; font-size:.8rem; font-weight:500; line-height:1.3;
            white-space:normal; transition:opacity .1s ease;}
        .composition-code:hover::after {visibility:visible; opacity:1;}
        .composition-summary:has(.composition-code:hover)::after {opacity:0;}
        .composition-summary.raw-simple {padding-bottom:.8rem;}
        </style>
        """
    )

    def summary_badge(code: str, explanation: str) -> str:
        """Build one inline `<span>` code badge with a hover tooltip, for the plain-language summary sentence."""
        explanation = " ".join(str(explanation).split())
        return (f'<span class="composition-code" data-tooltip="{escape(explanation, quote=True)}">'
                f'{escape(code)}</span>')

    def code_badge(code: str, dimension: str) -> str:
        """`summary_badge` for a real segment code, preferring a curated `help_keys` explanation over the generic `_segment_explanation` lookup where one exists."""
        help_keys = {
            "C": "simple_c_help", "E": "simple_e_help", "I": "simple_i_help",
            "C00": "simple_c_help", "E01": "simple_e_help", "E01/E02": "simple_e_help", "I01": "simple_i_help",
            "NLB": "nlb_help", "NRB": "nrb_help", "NLA": "nla_help", "NRA": "nra_help",
            "FLB": "flb_help", "FRB": "frb_help", "RLB": "rlb_help", "RRB": "rrb_help",
            "FLA": "fla_help", "FRA": "fra_help", "RLA": "rla_help", "RRA": "rra_help",
            "ILTLF": "linearized_help", "ILT_F": "linearized_help",
            "MXYLF": "binary_mask_help", "CR0": "chemcam_cr0_help", "PRC": "chemcam_prc_help",
            "DXXX": "dxxx_help", "DRXX": "drxx_help", "DRCX": "drcx_help", "DRLX": "drlx_help", "DRCL": "drcl_simple_help",
        }
        if code in help_keys:
            explanation = tr(help_keys[code])
        elif dimension == "product_variant":
            explanation = tr(f"product_type_{code[0]}") if code else tr("generic_code_note")
        else:
            explanation = _segment_explanation(dimension, code)
        return summary_badge(code, explanation)

    def joined_badges(items: list[tuple[str, str]]) -> str:
        """Join several `(code, dimension)` pairs into a natural-language `"A, B and C"` list of badges."""
        rendered = [code_badge(code, dimension) for code, dimension in items]
        if len(rendered) < 2:
            return "".join(rendered)
        return ", ".join(rendered[:-1]) + f' {escape(tr("mastcam_summary_and"))} ' + rendered[-1]

    for camera in cameras:
        camera_data = inventory[camera]
        if isinstance(camera_data, list):
            camera_data = {"total_products": max((int(item.get("count") or 0) for item in camera_data), default=0), "segments": camera_data}
        by_dimension: dict[str, list[dict]] = {}
        for segment in camera_data.get("segments") or []:
            by_dimension.setdefault(str(segment["dimension"]), []).append(segment)

        def codes(dimension: str) -> list[str]:
            """List `dimension`'s segment codes for the current camera, most-common first."""
            # Sorted by count (segments already come pre-sorted that way from
            # build_inventory) so the most common code leads the sentence.
            return [str(item["code"]) for item in by_dimension.get(dimension, [])]

        def top_codes_with_overflow(dimension: str, limit: int = 4) -> tuple[list[str], int]:
            """Return `dimension`'s top-`limit` codes plus the combined product count of everything beyond that (so a long tail collapses into one "+N others" figure instead of an unreadable list)."""
            # A dimension can carry a long tail (MAHLI alone has 15 distinct
            # product types, 3 of which cover >99% of its products) -- listing
            # every one would make the sentence unreadable, so anything past
            # `limit` gets folded into a single real, always-current count
            # instead of a fixed number written into the translation.
            segments = sorted(by_dimension.get(dimension, []), key=lambda item: -int(item.get("count") or 0))
            shown = [str(item["code"]) for item in segments[:limit]]
            overflow = sum(int(item.get("count") or 0) for item in segments[limit:])
            return shown, overflow

        def types_phrase(dimension: str, limit: int = 4) -> str:
            """Build the badge-joined phrase for `dimension`, appending an "+overflow" badge when `top_codes_with_overflow` found more codes than `limit`."""
            shown, overflow = top_codes_with_overflow(dimension, limit)
            phrase = joined_badges([(c, dimension) for c in shown])
            if overflow:
                other_label = f'{tr("composition_other")} · {overflow:,}'.replace(",", ".")
                other_help = tr("composition_other_help").format(count=f"{overflow:,}".replace(",", "."))
                other = summary_badge(other_label, other_help)
                phrase = f"{phrase}, {other}" if phrase else other
            return phrase

        if catalog == "PDS":
            # Every code below is read from by_dimension -- i.e. from the
            # Parquet just scanned for this render (see _composition_inventory's
            # mtime-keyed cache) -- instead of a fixed list, so the sentence
            # can never describe something the catalog no longer contains, or
            # stay silent about something it now does (e.g. after a Ripara or
            # a camera_rules.json change).
            sentence = ""
            if camera == "mastcam":
                suffixes = codes("suffix")
                if suffixes and by_dimension.get("product_type"):
                    sentence = (f'{escape(tr("mastcam_summary_start"))} {joined_badges([(c, "suffix") for c in suffixes])} '
                                f'{escape(tr("mastcam_summary_types"))} {types_phrase("product_type")}.')
            elif camera == "mahli":
                suffixes = codes("suffix")
                if suffixes and by_dimension.get("product_type"):
                    sentence = (f'{escape(tr("mahli_summary_start"))} {joined_badges([(c, "suffix") for c in suffixes])} '
                                f'{escape(tr("mahli_summary_types"))} {types_phrase("product_type")}.')
            elif camera == "mardi":
                suffixes = codes("suffix")
                if suffixes and by_dimension.get("product_type"):
                    sentence = (f'{escape(tr("mardi_summary_start"))} {types_phrase("product_type")} '
                                f'{escape(tr("summary_processing_plural"))} {joined_badges([(c, "suffix") for c in suffixes])}.')
            elif camera == "navcam":
                sides, markers = codes("camera_prefix"), codes("processing_marker")
                if sides and markers:
                    sentence = (f'{escape(tr("navcam_summary_start"))} {joined_badges([(c, "camera_prefix") for c in sides])} '
                                f'{escape(tr("summary_markers"))} {joined_badges([(c, "processing_marker") for c in markers])}.')
            elif camera == "hazcam":
                sides, markers = codes("camera_prefix"), codes("processing_marker")
                if sides and markers:
                    sentence = (f'{escape(tr("hazcam_summary_start"))} {joined_badges([(c, "camera_prefix") for c in sides])} '
                                f'{escape(tr("summary_markers"))} {joined_badges([(c, "processing_marker") for c in markers])}.')
            elif camera == "chemcam":
                instruments, markers = codes("instrument_product"), codes("processing_marker")
                if instruments and markers:
                    sentence = (f'{escape(tr("chemcam_summary_start"))} {joined_badges([(c, "instrument_product") for c in instruments])} '
                                f'{escape(tr("chemcam_summary_processed"))} {joined_badges([(c, "processing_marker") for c in markers])}.')
            if sentence:
                st.html(
                    f'<div class="composition-summary" data-hint="{escape(tr("composition_hover_code"), quote=True)}">'
                    f'{sentence}</div>'
                )
                continue
            # No sentence could be built (camera has none of the products this
            # phrasing expects, e.g. right after a scope change) -- fall
            # through to the real per-segment breakdown below instead of
            # showing nothing.
        if catalog == "RAW Archive":
            # Short colour/format context first (this much IS verified --
            # see build_inventory's file-extension check), then fall through
            # to the real per-segment breakdown below instead of `continue`
            # -- RAW has no PDS-style filename codes to show there, but it
            # does have a genuine, NASA-verified dimension: sample_type
            # (see product_composition.build_inventory's catalog="raw" path).
            camera_name = {"mastcam": "Mastcam", "mahli": "MAHLI", "mardi": "MARDI",
                           "navcam": "Navcam", "hazcam": "Hazcam", "chemcam": "ChemCam"}.get(camera, camera.upper())
            if camera in {"mastcam", "mahli", "mardi"}:
                sentence = tr("raw_simple_color").format(camera=camera_name)
            elif camera in {"navcam", "hazcam"}:
                sentence = tr("raw_simple_bw_jpg").format(camera=camera_name)
            elif camera == "chemcam":
                sentence = tr("raw_simple_chemcam")
            else:
                sentence = ""
            if sentence:
                st.html(f'<div class="composition-summary raw-simple">{escape(sentence)}</div>')
        total_products = int(camera_data.get("total_products") or 0)
        with st.container(border=True):
            title_col, count_col = st.columns([3, 1])
            title_col.markdown(f"### {camera.upper()}")
            count_col.metric(tr("composition_products"), f"{total_products:,}".replace(",", "."))
            st.markdown(f"**{tr('composition_included')}**")
            has_primary = False
            for dimension in primary_dimensions:
                segments = by_dimension.get(dimension, [])
                if segments:
                    has_primary = True
                    render_segment_group(camera, dimension, segments, technical=False)
            if not has_primary:
                st.info(tr("composition_no_primary"))
            if any(by_dimension.get(dimension) for dimension in technical_dimensions):
                with st.expander(tr("composition_technical"), expanded=False):
                    st.caption(tr("composition_technical_hint"))
                    for dimension in technical_dimensions:
                        render_segment_group(camera, dimension, by_dimension.get(dimension, []), technical=True)
    if catalog == "PDS":
        render_advanced_customization(parquet)


@st.dialog("MSL", width="small")
def confirm_pds_customization(
    changes: dict[str, dict[str, list[str]]], sol_start: int, sol_end: int, estimate: str
) -> None:
    """Modal: confirm and launch a customization job applying `changes` (per-camera selections) over the given Sol range."""
    st.markdown(f"### {tr('custom_confirm_title')}")
    st.write(tr("custom_confirm_text").format(estimate=estimate))
    st.caption(tr("custom_test_sol_range").format(start=sol_start, end=sol_end))
    for camera, combinations in changes.items():
        details = " · ".join(f"{primary}: {', '.join(values)}" for primary, values in combinations.items())
        st.caption(f"{camera.upper()} → {details}")
    st.info(tr("custom_safe_note"))
    cancel_col, proceed_col = st.columns(2)
    if cancel_col.button(tr("cancel"), key="custom_confirm_cancel", width="stretch"):
        st.rerun()
    if proceed_col.button(tr("proceed"), key="custom_confirm_proceed", type="primary", width="stretch"):
        try:
            job = start_pds_customization_job(changes, sol_start, sol_end)
            st.session_state.pds_customization_job_id = job["job_id"]
            st.session_state.pds_customization_changes = {}
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))


@st.fragment(run_every="2s")
def render_customization_progress() -> None:
    """Self-refreshing progress panel for the most recent customization job: current phase/camera, a Stop button while running, and a final removed/added summary (with a Resume option if cancelled/failed) once done."""
    job_id = st.session_state.get("pds_customization_job_id")
    job = load_job(job_id) if job_id else latest_job("pds", operation="catalog_customization")
    if not job:
        return
    status = str(job.get("status") or "")

    # The selection checkboxes above live in render_advanced_customization(),
    # outside this self-refreshing fragment, so the "current" state they show
    # (read from the Parquet) only gets recomputed on a full app rerun. Force
    # exactly one full rerun the first time this fragment observes the job
    # leave queued/running, so the checkboxes reflect the just-applied change
    # without the user having to click something unrelated first.
    actual_job_id = str(job.get("job_id") or "")
    if actual_job_id and status not in {"queued", "running", "cancelling"}:
        rerun_flag = f"_custom_job_rerun_done::{actual_job_id}"
        if not st.session_state.get(rerun_flag):
            st.session_state[rerun_flag] = True
            st.rerun()

    if status in {"queued", "running"}:
        st.markdown(f"**{tr('custom_running')}**")
        phase = str(job.get("phase") or "queued")
        progress = 0.0
        detail = tr(f"custom_phase_{phase}")
        if phase == "enriching_metadata":
            lbl_done = job.get("lbl_candidates_done")
            lbl_total = job.get("lbl_candidates_total")
            if isinstance(lbl_done, (int, float)) and isinstance(lbl_total, (int, float)) and lbl_total > 0:
                progress = max(0.0, min(1.0, lbl_done / lbl_total))
                detail += f" · {int(lbl_done):,}/{int(lbl_total):,}".replace(",", ".")
        st.progress(progress, text=detail)
        if job.get("current_camera"):
            st.caption(str(job["current_camera"]).upper())
        if st.button(tr("stop_update_job"), key="custom_update_stop", disabled=status == "cancelling"):
            request_cancel(str(job["job_id"]))
            st.rerun()
        return
    if status in {"cancelled", "failed"}:
        if status == "cancelled":
            st.warning(tr("custom_cancelled"))
        else:
            st.error(f"{tr('custom_failed')}: {job.get('error', '—')}")
        if actual_job_id and customization_resumable(actual_job_id):
            if st.button(tr("resume_check"), key=f"custom_resume_{actual_job_id}", width="stretch"):
                try:
                    resumed = start_pds_customization_resume_job(actual_job_id)
                    st.session_state.pds_customization_job_id = resumed["job_id"]
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))
        return
    if status == "completed":
        added = sum(int(value) for value in (job.get("added_by_camera") or {}).values())
        removed = sum(int(value) for value in (job.get("removed_by_camera") or {}).values())
        st.success(tr("custom_complete").format(added=added, removed=removed))


def render_advanced_customization(parquet: Path) -> None:
    """The customization tab: pick a camera, edit its selection via that camera's dedicated `render_*_customization` renderer, review the pending cross-camera diff (add/remove per primary dimension), and hand off to the Sol-range/confirm step below (continues past this function)."""
    st.markdown(f"### {tr('custom_title')}")
    st.caption(tr("custom_hint"))
    options_by_camera = _current_camera_options(str(parquet), parquet.stat().st_mtime_ns)
    changes = st.session_state.setdefault("pds_customization_changes", {})
    if changes and not all(isinstance(value, dict) for value in changes.values()):
        changes = {}
        st.session_state.pds_customization_changes = changes
    camera = st.selectbox(
        tr("custom_camera"), list(CUSTOMIZABLE_CAMERAS), format_func=str.upper,
        key="custom_camera_select",
    )
    current = options_by_camera.get(camera) or {}
    # Every CUSTOMIZABLE_CAMERAS entry has a dedicated renderer below; there
    # is no camera left over for a generic fallback.
    if camera == "chemcam":
        render_chemcam_customization(current, changes)
    elif camera in {"navcam", "hazcam"}:
        render_engineering_customization(camera, current, changes)
    elif camera == "mahli":
        render_mahli_customization(current, changes)
    elif camera == "mardi":
        render_mardi_customization(current, changes)
    elif camera == "mastcam":
        render_mmm_customization(camera, current, changes)

    st.markdown(f"**{tr('custom_changes')}**")
    if not changes:
        st.caption(tr("custom_changes_empty"))
    else:
        for changed_camera, desired_selection in list(changes.items()):
            text_parts = []
            current_selection = options_by_camera.get(changed_camera) or {}
            for primary in CAMERA_OPTIONS[changed_camera]["primary"]:
                desired_values = desired_selection.get(primary, [])
                allowed = CAMERA_OPTIONS[changed_camera]["secondary"]
                before = set(current_selection.get(primary) or set())
                after = set(desired_values)
                add = [value for value in allowed if value in after - before]
                remove = [value for value in allowed if value in before - after]
                if add:
                    text_parts.append(f"{primary} · {tr('custom_add')}: {', '.join(add)}")
                if remove:
                    text_parts.append(f"{primary} · {tr('custom_remove')}: {', '.join(remove)}")
            text = f"{changed_camera.upper()} — " + " | ".join(text_parts)
            label_col, remove_col = st.columns([8, 1], vertical_alignment="center")
            label_col.write(text)
            if remove_col.button("×", key=f"custom_remove_change_{changed_camera}"):
                changes.pop(changed_camera, None)
                st.rerun()
        if st.button(tr("custom_clear_changes"), key="custom_clear_changes", width="stretch"):
            st.session_state.pds_customization_changes = {}
            st.rerun()
        st.markdown(f"**{tr('custom_test_range_title')}**")
        st.caption(tr("custom_test_range_hint"))
        default_sol_start, default_sol_end = _catalog_sol_range(str(parquet), parquet.stat().st_mtime_ns)
        range_col_1, range_col_2 = st.columns(2)
        sol_start = int(range_col_1.number_input(
            tr("sol_from"), min_value=0, value=default_sol_start, step=1,
            key="custom_test_sol_start",
        ))
        sol_end = int(range_col_2.number_input(
            tr("sol_to"), min_value=0, value=default_sol_end, step=1,
            key="custom_test_sol_end",
        ))
        if sol_start > sol_end:
            st.error(tr("custom_test_range_invalid"))
        disabled = bool(active_job_for_catalog("pds"))
        if st.button(
            tr("custom_apply"), key="custom_apply", type="primary", width="stretch",
            disabled=disabled or sol_start > sol_end,
        ):
            remote_cameras = 0
            for changed_camera, desired_selection in changes.items():
                existing = options_by_camera.get(changed_camera) or {}
                if any(set(values) - set(existing.get(primary) or set()) for primary, values in desired_selection.items()):
                    remote_cameras += 1
            sol_count = sol_end - sol_start + 1
            seconds = 90 if not remote_cameras else max(60, sol_count * remote_cameras * 3)
            estimate = f"{format_duration(seconds * 0.75)}–{format_duration(seconds * 1.5)}"
            confirm_pds_customization(dict(changes), sol_start, sol_end, estimate)
    render_customization_progress()


def render_mahli_customization(
    current: dict[str, set[str]], changes: dict[str, dict[str, list[str]]]
) -> None:
    """MAHLI's customization UI: product-type/processing-level checkboxes grouped into human categories (lossless/JPEG/thumbnails/video/derived), diffed against `current` and written into `changes["mahli"]` on change."""
    compatibility: dict[str, list[str]] = PDS_CAMERA_COMPATIBILITY["mmm"]["mahli"]
    st.markdown(f"#### {tr('mahli_products_to_include')}")
    st.caption(tr("mahli_customization_hint"))
    st.html("""
    <style>
    .navcam-info-code {position:relative;display:inline-block;padding:.12rem .38rem;border-radius:.22rem;background:#11141c;color:#77ef91;font-family:monospace;font-size:.78rem;font-weight:700;cursor:help}
    .navcam-info-code::after {content:attr(data-tooltip);position:absolute;z-index:1000;left:calc(100% + .65rem);top:50%;width:max-content;max-width:22rem;padding:.65rem .8rem;border:1px solid rgba(155,106,50,.45);border-radius:.45rem;background:var(--secondary-background-color,#f7f3e8);color:var(--text-color,#191919);font-family:sans-serif;font-size:.82rem;font-weight:500;line-height:1.35;white-space:normal;box-shadow:0 .4rem 1.2rem rgba(0,0,0,.16);opacity:0;visibility:hidden;pointer-events:none;transform:translate(.2rem,-50%);transition:opacity .12s ease,transform .12s ease}
    .navcam-info-code:hover::after,.navcam-info-code:focus::after {opacity:1;visibility:visible;transform:translate(0,-50%)}
    </style>
    """)
    groups = (
        ("mahli_group_lossless", {"C"}),
        ("mahli_group_jpeg", {"E"}),
        ("mahli_group_thumbnails", {"G", "H", "I"}),
        ("mahli_group_other_images", {"A", "B", "D"}),
        ("mahli_group_video", {"J", "K", "M", "N"}),
        ("mahli_group_video_thumbnails", {"O", "P", "Q"}),
        ("mahli_group_derived", {"R", "T"}),
    )
    compatibility_exact = {
        f"{kind}|{level}"
        for kind, levels in compatibility.items()
        for level in levels
    }
    current_exact = {
        f"{kind}|{level}"
        for kind, levels in current.items()
        for level in levels
        if f"{kind}|{level}" in compatibility_exact
    }
    # Keep the widget state tied to this exact UI model.  The previous key could
    # retain selections created by an older MAHLI renderer, making the footer
    # report combinations for which no visible checkbox was selected.
    state_key = "mahli_grouped_exact_selection_v4"
    source_key = "mahli_grouped_exact_selection_source_v4"
    signature = tuple(sorted(current_exact))
    if st.session_state.get(source_key) != signature:
        st.session_state[source_key] = signature
        st.session_state[state_key] = set(current_exact)
    selected = set(st.session_state.get(state_key, set())) & compatibility_exact
    st.session_state[state_key] = selected
    detail_key = "mahli_group_detail_open"

    def level_help(level: str) -> str:
        """Tooltip text for a processing-level code (DXXX/DRXX/DRCX/DRLX/DRCL)."""
        return {
            "DXXX": tr("dxxx_help"), "DRXX": tr("drxx_help"),
            "DRCX": tr("drcx_help"), "DRLX": tr("drlx_help"),
            "DRCL": tr("mastcam_custom_drcl_help"),
        }.get(level, tr("generic_code_note"))

    def kind_help(kind: str) -> str:
        """Tooltip text for a 3-char product-type code, decoding its type/sequence/version characters."""
        description = tr(f"product_type_{kind[0]}")
        if kind[0] in set("JKLMNOPQ"):
            sequence = tr("mahli_video_index_code").format(
                code=kind[1], position=int(kind[1], 16)
            )
        else:
            sequence = tr("mahli_non_video_gop_code").format(code=kind[1])
        version_value = int(kind[2], 36)
        version = (
            tr("mahli_original_version_code").format(code=kind[2])
            if version_value == 0
            else tr("mahli_later_version_code").format(code=kind[2], version=version_value)
        )
        product_type = tr("mahli_type_code").format(code=kind[0], description=description)
        return f"{kind}: {product_type} {sequence} {version}"

    st.markdown(f"##### {tr('mahli_images')}")
    for index, (label_key, prefixes) in enumerate(groups):
        if index == 4:
            st.markdown(f"##### {tr('mahli_video_and_derived')}")
        kinds = [kind for kind in compatibility if kind[0] in prefixes]
        if not kinds:
            continue
        available = {f"{kind}|{level}" for kind in kinds for level in compatibility[kind]}
        chosen = selected & available
        row = st.columns([6, 2, .55, 1.35], vertical_alignment="center")
        enabled = row[0].checkbox(
            tr(label_key), value=bool(chosen),
            key=f"mahli_group_check_{label_key}_{abs(hash(tuple(sorted(chosen))))}",
        )
        if enabled != bool(chosen):
            selected = (selected | available) if enabled else (selected - available)
            st.session_state[state_key] = selected
            st.rerun()
        row[1].caption(tr("custom_combinations_count").format(selected=len(chosen), total=len(available)))
        if row[2].button("?", key=f"mahli_group_help_{label_key}"):
            st.session_state[detail_key] = None if st.session_state.get(detail_key) == label_key else label_key
            st.rerun()
        representative_options = sorted(chosen or available)
        representative = next(
            (
                exact for exact in representative_options
                if _preview_example("MAHLI", "", exact)[0] is not None
            ),
            representative_options[0],
        )
        video_group = label_key in {"mahli_group_video", "mahli_group_video_thumbnails"}
        if not video_group:
            preview_button(
                row[3], "MAHLI", tr(label_key), "", f"mahli_group_{label_key}",
                match_key=representative,
            )
        if st.session_state.get(detail_key) == label_key:
            with st.container(border=True):
                st.markdown(f"**{tr(label_key)}**")
                st.caption(tr("mahli_group_detail_hint"))
                for kind in kinds:
                    code_row = st.columns([2, 7], vertical_alignment="center")
                    code_help = kind_help(kind)
                    code_row[0].html(
                        f'<span class="navcam-info-code" tabindex="0" '
                        f'data-tooltip="{escape(code_help, quote=True)}">{escape(kind)}</span>'
                    )
                    level_columns = code_row[1].columns(max(1, len(compatibility[kind])))
                    for column, level in zip(level_columns, compatibility[kind]):
                        exact = f"{kind}|{level}"
                        checked = exact in selected
                        column.html(
                            f'<span class="navcam-info-code" tabindex="0" '
                            f'data-tooltip="{escape(level_help(level), quote=True)}">{escape(level)}</span>'
                        )
                        value = column.checkbox(
                            level, value=checked, label_visibility="collapsed",
                            key=f"mahli_group_matrix_{kind}_{level}_{int(checked)}",
                        )
                        if kind[:1] not in {"J", "K", "M", "N", "O", "P", "Q"}:
                            preview_button(column, "MAHLI", kind, level, f"mahli_{kind}_{level}")
                        if value != checked:
                            selected.add(exact) if value else selected.discard(exact)
                            st.session_state[state_key] = selected
                            st.rerun()

    st.divider()
    st.write(f"**{tr('custom_selected_combinations').format(count=len(selected))}**")
    if st.button(
        tr("custom_register_camera").format(camera="MAHLI"),
        key="mahli_grouped_register", width="stretch", disabled=not selected,
    ):
        desired = {
            kind: sorted(exact.split("|", 1)[1] for exact in selected if exact.startswith(f"{kind}|"))
            for kind in CAMERA_OPTIONS["mahli"]["primary"]
        }
        desired = {key: values for key, values in desired.items() if values}
        normalized = {key: sorted(values) for key, values in current.items() if values}
        if desired == normalized:
            changes.pop("mahli", None)
            st.info(tr("custom_no_change"))
        else:
            changes["mahli"] = desired
            st.rerun()


def render_mardi_customization(
    current: dict[str, set[str]], changes: dict[str, dict[str, list[str]]]
) -> None:
    """MARDI's customization UI: product-type/processing-level checkboxes grouped into lossless/JPEG/thumbnail categories, diffed against `current` and written into `changes["mardi"]` on change (structurally the same pattern as `render_mahli_customization`, simpler since MARDI has fewer product-type groups)."""
    compatibility: dict[str, list[str]] = PDS_CAMERA_COMPATIBILITY["mmm"]["mardi"]
    compatibility_exact = {
        f"{kind}|{level}"
        for kind, levels in compatibility.items()
        for level in levels
    }
    current_exact = {
        f"{kind}|{level}"
        for kind, levels in current.items()
        for level in levels
        if f"{kind}|{level}" in compatibility_exact
    }
    state_key = "mardi_grouped_exact_selection_v2"
    source_key = "mardi_grouped_exact_selection_source_v2"
    signature = tuple(sorted(current_exact))
    if st.session_state.get(source_key) != signature:
        st.session_state[source_key] = signature
        st.session_state[state_key] = set(current_exact)
    selected = set(st.session_state.get(state_key, set())) & compatibility_exact
    st.session_state[state_key] = selected
    detail_key = "mardi_group_detail_open_v2"

    st.markdown(f"#### {tr('mardi_products_to_include')}")
    st.caption(tr("mardi_customization_hint"))
    st.html("""
    <style>
    .navcam-info-code {position:relative;display:inline-block;padding:.12rem .38rem;border-radius:.22rem;background:#11141c;color:#77ef91;font-family:monospace;font-size:.78rem;font-weight:700;cursor:help}
    .navcam-info-code::after {content:attr(data-tooltip);position:absolute;z-index:1000;left:calc(100% + .65rem);top:50%;width:max-content;max-width:22rem;padding:.65rem .8rem;border:1px solid rgba(155,106,50,.45);border-radius:.45rem;background:var(--secondary-background-color,#f7f3e8);color:var(--text-color,#191919);font-family:sans-serif;font-size:.82rem;font-weight:500;line-height:1.35;white-space:normal;box-shadow:0 .4rem 1.2rem rgba(0,0,0,.16);opacity:0;visibility:hidden;pointer-events:none;transform:translate(.2rem,-50%);transition:opacity .12s ease,transform .12s ease}
    .navcam-info-code:hover::after,.navcam-info-code:focus::after {opacity:1;visibility:visible;transform:translate(0,-50%)}
    </style>
    """)

    groups = (
        ("mardi_lossless_label", ("C00",), "mardi_c00_help"),
        ("mardi_jpeg_label", ("E01", "E02"), "mardi_e_help"),
        ("mardi_thumbnail_label", ("I01",), "mardi_i01_help"),
    )

    def level_help(level: str) -> str:
        """Tooltip text for a processing-level code (DXXX/DRXX/DRCX/DRLX/DRCL)."""
        return {
            "DXXX": tr("dxxx_help"), "DRXX": tr("drxx_help"),
            "DRCX": tr("drcx_help"), "DRLX": tr("drlx_help"),
            "DRCL": tr("mastcam_custom_drcl_help"),
        }.get(level, tr("generic_code_note"))

    for label_key, kinds, help_key in groups:
        available = {
            f"{kind}|{level}"
            for kind in kinds
            for level in compatibility.get(kind, [])
        }
        chosen = selected & available
        row = st.columns([6, 1.6, 2, .55, 1.35], vertical_alignment="center")
        enabled = row[0].checkbox(
            tr(label_key), value=bool(chosen),
            key=f"mardi_group_check_{label_key}_{abs(hash(tuple(sorted(chosen))))}",
        )
        if enabled != bool(chosen):
            selected = (selected | available) if enabled else (selected - available)
            st.session_state[state_key] = selected
            st.rerun()
        row[1].html(
            " ".join(
                f'<span class="navcam-info-code" tabindex="0" '
                f'data-tooltip="{escape(tr(help_key), quote=True)}">{escape(kind)}</span>'
                for kind in kinds
            )
        )
        row[2].caption(
            tr("custom_combinations_count").format(
                selected=len(chosen), total=len(available)
            )
        )
        if row[3].button("?", key=f"mardi_group_help_{label_key}"):
            st.session_state[detail_key] = (
                None if st.session_state.get(detail_key) == label_key else label_key
            )
            st.rerun()
        representative_options = sorted(chosen or available)
        representative = next(
            (
                exact for exact in representative_options
                if _preview_example("MARDI", "", exact)[0] is not None
            ),
            representative_options[0],
        )
        preview_button(
            row[4], "MARDI", tr(label_key), "", f"mardi_group_{label_key}",
            match_key=representative,
        )
        if st.session_state.get(detail_key) == label_key:
            with st.container(border=True):
                st.markdown(f"**{tr(label_key)}**")
                st.caption(tr(help_key))
                for kind in kinds:
                    code_row = st.columns([1.5, 8], vertical_alignment="center")
                    code_row[0].html(
                        f'<span class="navcam-info-code" tabindex="0" '
                        f'data-tooltip="{escape(tr(help_key), quote=True)}">{escape(kind)}</span>'
                    )
                    columns = code_row[1].columns(len(compatibility[kind]))
                    for column, level in zip(columns, compatibility[kind]):
                        exact = f"{kind}|{level}"
                        checked = exact in selected
                        column.html(
                            f'<span class="navcam-info-code" tabindex="0" '
                            f'data-tooltip="{escape(level_help(level), quote=True)}">{escape(level)}</span>'
                        )
                        value = column.checkbox(
                            level, value=checked, label_visibility="collapsed",
                            key=f"mardi_group_matrix_{kind}_{level}_{int(checked)}",
                        )
                        preview_button(column, "MARDI", kind, level, f"mardi_{kind}_{level}")
                        if value != checked:
                            selected.add(exact) if value else selected.discard(exact)
                            st.session_state[state_key] = selected
                            st.rerun()

    st.divider()
    st.write(f"**{tr('custom_selected_combinations').format(count=len(selected))}**")
    if st.button(
        tr("custom_register_camera").format(camera="MARDI"),
        key="mardi_grouped_register", width="stretch", disabled=not selected,
    ):
        desired = {
            kind: sorted(
                exact.split("|", 1)[1]
                for exact in selected
                if exact.startswith(f"{kind}|")
            )
            for kind in compatibility
        }
        desired = {key: values for key, values in desired.items() if values}
        normalized = {key: sorted(values) for key, values in current.items() if values}
        if desired == normalized:
            changes.pop("mardi", None)
            st.info(tr("custom_no_change"))
        else:
            changes["mardi"] = desired
            st.rerun()


def render_mmm_customization(
    camera: str, current: dict[str, set[str]], changes: dict[str, dict[str, list[str]]]
) -> None:
    """Mastcam's customization UI: a flat list of product-type checkboxes (not grouped into categories like MAHLI/MARDI's own renderers, which this one was split from), each expandable to its per-level detail matrix, diffed against `current` and written into `changes[camera]` on change."""
    camera_label = {"mastcam": "Mastcam", "mahli": "MAHLI", "mardi": "MARDI"}[camera]
    compatibility: dict[str, list[str]] = PDS_CAMERA_COMPATIBILITY["mmm"][camera]
    st.markdown(f"#### {tr('mmm_products_to_include').format(camera=camera_label)}")
    st.caption(tr("mmm_customization_hint"))
    st.html("""
    <style>
    .navcam-info-code {position:relative;display:inline-block;padding:.12rem .38rem;border-radius:.22rem;background:#11141c;color:#77ef91;font-family:monospace;font-size:.78rem;font-weight:700;cursor:help}
    .navcam-info-code::after {content:attr(data-tooltip);position:absolute;z-index:1000;left:calc(100% + .65rem);top:50%;width:max-content;max-width:22rem;padding:.65rem .8rem;border:1px solid rgba(155,106,50,.45);border-radius:.45rem;background:var(--secondary-background-color,#f7f3e8);color:var(--text-color,#191919);font-family:sans-serif;font-size:.82rem;font-weight:500;line-height:1.35;white-space:normal;box-shadow:0 .4rem 1.2rem rgba(0,0,0,.16);opacity:0;visibility:hidden;pointer-events:none;transform:translate(.2rem,-50%);transition:opacity .12s ease,transform .12s ease}
    .navcam-info-code:hover::after,.navcam-info-code:focus::after {opacity:1;visibility:visible;transform:translate(0,-50%)}
    </style>
    """)
    compatibility_exact = {
        f"{kind}|{level}"
        for kind, levels in compatibility.items()
        for level in levels
    }
    current_exact = {
        f"{kind}|{level}"
        for kind, levels in current.items()
        for level in levels
        if f"{kind}|{level}" in compatibility_exact
    }
    state_key = f"{camera}_exact_selection"
    source_key = f"{camera}_exact_selection_source"
    signature = tuple(sorted(current_exact))
    if st.session_state.get(source_key) != signature:
        st.session_state[source_key] = signature
        st.session_state[state_key] = set(current_exact)
    # Keep the widget state tied to this exact UI model. A stale key from a
    # config change (a kind/level combo that used to be compatible and no
    # longer is) would otherwise stay invisible -- no checkbox renders for
    # it -- while still inflating the footer count and leaking into the
    # registered selection on save. Same fix as render_mahli_customization /
    # render_mardi_customization, which this function was split from.
    selected = set(st.session_state.get(state_key, set())) & compatibility_exact
    st.session_state[state_key] = selected
    detail_key = f"{camera}_product_detail_open"

    def product_help(kind: str) -> str:
        """Label/tooltip text for a product-type code: Mastcam's friendly name when available and enabled, else the generic product-type description."""
        if camera == "mastcam" and not st.session_state.show_technical_product_names:
            friendly_key = f"mastcam_friendly_{kind}"
            if friendly_key in TEXT[st.session_state.lang]:
                return tr(friendly_key)
        return tr(f"product_type_{kind[0]}")

    def level_help(level: str) -> str:
        """Tooltip text for a processing-level code (DXXX/DRXX/DRCX/DRLX/DRCL)."""
        return {
            "DXXX": tr("dxxx_help"), "DRXX": tr("drxx_help"),
            "DRCX": tr("drcx_help"), "DRLX": tr("drlx_help"),
            "DRCL": tr("mastcam_custom_drcl_help") if camera == "mastcam" else tr("mastcam_drcl_help"),
        }.get(level, tr("generic_code_note"))

    def product_row(kind: str) -> None:
        """Render one product-type's checkbox row: label, code badge, selected/available count, help toggle, and preview button."""
        nonlocal selected
        available = {f"{kind}|{level}" for level in compatibility[kind]}
        chosen = selected & available
        label = product_help(kind)
        row = st.columns([6, 1, 2, .55, 1.35], vertical_alignment="center")
        enabled = row[0].checkbox(
            label, value=bool(chosen),
            key=f"{camera}_type_check_{kind}_{abs(hash(tuple(sorted(chosen))))}",
        )
        if enabled != bool(chosen):
            selected = (selected | available) if enabled else (selected - available)
            st.session_state[state_key] = selected
            st.rerun()
        row[1].html(
            f'<span class="navcam-info-code" tabindex="0" '
            f'data-tooltip="{escape(label, quote=True)}">{escape(kind)}</span>'
        )
        row[2].caption(tr("custom_combinations_count").format(
            selected=len(chosen), total=len(available)
        ))
        if row[3].button("?", key=f"{camera}_help_{kind}"):
            st.session_state[detail_key] = None if st.session_state.get(detail_key) == kind else kind
            st.rerun()
        preview_button(row[4], camera_label, label, kind, f"{camera}_{kind}")
        if st.session_state.get(detail_key) == kind:
            with st.container(border=True):
                st.markdown(f"**{label} · {kind}**")
                columns = st.columns(max(1, len(compatibility[kind])))
                for column, level in zip(columns, compatibility[kind]):
                    exact = f"{kind}|{level}"
                    checked = exact in selected
                    column.html(
                        f'<span class="navcam-info-code" tabindex="0" '
                        f'data-tooltip="{escape(level_help(level), quote=True)}">{escape(level)}</span>'
                    )
                    value = column.checkbox(
                        level, value=checked, label_visibility="collapsed",
                        key=f"{camera}_matrix_{kind}_{level}_{int(checked)}",
                    )
                    preview_button(column, camera_label, kind, level, f"{camera}_{kind}_{level}")
                    if value != checked:
                        selected.add(exact) if value else selected.discard(exact)
                        st.session_state[state_key] = selected
                        st.rerun()

    main_type_prefixes = {"C", "D", "E", "I"} if camera == "mastcam" else {"C", "E", "I"}
    main_types = [code for code in compatibility if code[0] in main_type_prefixes]
    special = [code for code in compatibility if code not in main_types]
    if main_types:
        st.markdown(f"##### {tr('mmm_primary_products')}")
        for code in main_types:
            product_row(code)
    if special:
        st.markdown(f"##### {tr('mmm_special_products')}")
        show_special = st.checkbox(
            tr("mmm_show_special").format(count=len(special)), key=f"{camera}_show_special"
        )
        visible = special if show_special else special[:4]
        for code in visible:
            product_row(code)
        if not show_special and len(special) > len(visible):
            st.caption(tr("mmm_hidden_special").format(count=len(special) - len(visible)))

    st.divider()
    st.write(f"**{tr('custom_selected_combinations').format(count=len(selected))}**")
    if st.button(
        tr("custom_register_camera").format(camera=camera_label), key=f"{camera}_register",
        width="stretch", disabled=not selected,
    ):
        desired = {
            kind: sorted(exact.split("|", 1)[1] for exact in selected if exact.startswith(f"{kind}|"))
            for kind in CAMERA_OPTIONS[camera]["primary"]
        }
        desired = {key: values for key, values in desired.items() if values}
        normalized = {key: sorted(values) for key, values in current.items() if values}
        if desired == normalized:
            changes.pop(camera, None)
            st.info(tr("custom_no_change"))
        else:
            changes[camera] = desired
            st.rerun()


def render_engineering_customization(
    camera: str, current: dict[str, set[str]], changes: dict[str, dict[str, list[str]]]
) -> None:
    """Navcam/Hazcam's customization UI: camera-side (L/R prefix)/processing-marker checkboxes, diffed against `current` and written into `changes[camera]` on change (ChemCam has its own dedicated renderer, `render_chemcam_customization`, despite sharing the "engineering" compatibility shape)."""
    camera_label = {"navcam": "Navcam", "hazcam": "Hazcam", "chemcam": "ChemCam"}[camera]
    st.markdown(f"#### {tr('engineering_products_to_include').format(camera=camera_label)}")
    st.caption(tr("engineering_customization_hint"))
    st.html(
        """
        <style>
        .navcam-variant-code,
        .navcam-info-code {
            position: relative;
            display: inline-block;
            padding: .12rem .38rem;
            border-radius: .22rem;
            background: #11141c;
            color: #77ef91;
            font-family: monospace;
            font-size: .78rem;
            font-weight: 700;
            line-height: 1.2;
            cursor: help;
        }
        .navcam-variant-code::after,
        .navcam-info-code::after {
            content: attr(data-tooltip);
            position: absolute;
            z-index: 1000;
            left: calc(100% + .65rem);
            top: 50%;
            width: max-content;
            max-width: 22rem;
            padding: .65rem .8rem;
            border: 1px solid rgba(155, 106, 50, .45);
            border-radius: .45rem;
            background: var(--secondary-background-color, #f7f3e8);
            color: var(--text-color, #191919);
            font-family: sans-serif;
            font-size: .82rem;
            font-weight: 500;
            line-height: 1.35;
            white-space: normal;
            box-shadow: 0 .4rem 1.2rem rgba(0, 0, 0, .16);
            opacity: 0;
            visibility: hidden;
            pointer-events: none;
            transform: translate(.2rem, -50%);
            transition: opacity .12s ease, transform .12s ease;
        }
        .navcam-variant-code:hover::after,
        .navcam-variant-code:focus::after,
        .navcam-info-code:hover::after,
        .navcam-info-code:focus::after {
            opacity: 1;
            visibility: visible;
            transform: translate(0, -50%);
        }
        </style>
        """
    )

    compatibility_all = (
        NAVCAM_COMPATIBILITY if camera == "navcam"
        else PDS_CAMERA_COMPATIBILITY["engineering"][camera]
    )
    compatibility_exact = {
        f"{prefix}|{family}{variant}"
        for family, prefixes in compatibility_all.items()
        for prefix, variants in prefixes.items()
        for variant in variants
    }
    current_exact = {
        f"{prefix}|{marker}"
        for prefix, markers in current.items()
        for marker in markers
        if f"{prefix}|{marker}" in compatibility_exact
    }
    state_key = f"{camera}_exact_selection_v2"
    source_key = f"{camera}_exact_selection_source_v2"
    source_signature = tuple(sorted(current_exact))
    if st.session_state.get(source_key) != source_signature:
        st.session_state[source_key] = source_signature
        st.session_state[state_key] = set(current_exact)
    selected_exact = set(st.session_state.get(state_key, set())) & compatibility_exact
    st.session_state[state_key] = selected_exact

    # Group headings and per-code labels/help text all come from tr() below
    # (config-driven i18n, not hardcoded here) -- this table only needs to
    # say which codes belong to which group.
    group_keys = (
        "engineering_group_images", "engineering_group_support",
        "engineering_group_stereo", "engineering_group_surface",
        "engineering_group_arm",
    )
    group_codes = (
        ("EDR", "ILT", "RAD", "RAS", "PRC"),
        ("ERP", "ERS", "ECS", "EHG", "EID"),
        ("DSP", "DSR", "DFF", "MDS", "RNG", "RNR", "RNE", "XYZ", "XYR", "XYM", "XYE", "MXY"),
        ("UVW", "UVS", "SLP", "SHD", "SMG", "SNT", "SRD", "RUD", "RUT"),
        ("ARM", "ARP"),
    )
    all_groups = tuple(
        (
            tr(group_key),
            tuple(
                (
                    code,
                    tr(
                        f"navcam_{code.lower()}_label"
                        if camera == "navcam" and code in {"EDR", "ILT", "RAD", "RAS"}
                        else f"engineering_{code.lower()}_label"
                    ),
                    tr(
                        f"navcam_{code.lower()}_help"
                        if camera == "navcam" and code in {"EDR", "ILT", "RAD", "RAS"}
                        else f"engineering_{code.lower()}_help"
                    ),
                )
                for code in codes
            ),
        )
        for group_key, codes in zip(group_keys, group_codes)
    )
    groups = tuple(
        (name, tuple(product for product in products if product[0] in compatibility_all))
        for name, products in all_groups
        if any(product[0] in compatibility_all for product in products)
    )

    def available_for_family(code: str) -> set[str]:
        """All `{prefix}|{code}{variant}` exact combinations for one processing-marker family (`code`), across every camera-side prefix."""
        return {
            f"{prefix}|{code}{variant}"
            for prefix, variants in compatibility_all[code].items()
            for variant in variants
        }

    def product_row(code: str, label: str, description: str) -> None:
        """Render one processing-marker family's checkbox row (label, code badge, count, help toggle, preview), expandable into a per-camera-side/variant detail matrix."""
        nonlocal selected_exact
        available = available_for_family(code)
        family_selected = selected_exact & available
        row = st.columns([6, 1, 2, 0.55, 1.35], vertical_alignment="center")
        enabled = row[0].checkbox(
            label, value=bool(family_selected),
            key=f"{camera}_product_check_{code}_{abs(hash(tuple(sorted(family_selected))))}",
        )
        if enabled != bool(family_selected):
            if enabled:
                selected_exact |= available
            else:
                selected_exact -= available
            st.session_state[state_key] = selected_exact
            st.rerun()
        family_tooltip = f"{label} — {description}"
        row[1].html(
            f'<span class="navcam-info-code" tabindex="0" '
            f'data-tooltip="{escape(family_tooltip, quote=True)}">'
            f'{escape(code)}</span>'
        )
        row[2].caption(tr("custom_combinations_count").format(
            selected=len(family_selected), total=len(available)
        ))
        detail_key = f"{camera}_product_detail_open"
        if row[3].button("?", key=f"{camera}_help_{code}"):
            st.session_state[detail_key] = None if st.session_state.get(detail_key) == code else code
            st.rerun()
        preview_button(row[4], camera_label, label, code, f"{camera}_{code}")
        if st.session_state.get(detail_key) == code:
            with st.container(border=True):
                st.markdown(f"**{label} · {code}**")
                st.write(description)
                st.caption(tr("engineering_matrix_hint").format(camera=camera_label))
                compatibility = compatibility_all[code]
                prefixes = list(compatibility)
                variants = sorted(
                    {variant for values in compatibility.values() for variant in values},
                    key=lambda value: (len(value.removeprefix("_")), value.removeprefix("_")),
                )
                header = st.columns([1.7, *([1] * len(prefixes))], vertical_alignment="center")
                header[0].markdown(f"**{tr('engineering_variant')}**")
                for column, prefix in zip(header[1:], prefixes):
                    camera_help = {
                        "NAA": tr("naa_help"),
                        "NAB": tr("nab_help"),
                        "NLA": tr("nla_help"),
                        "NLB": tr("nlb_help"),
                        "NRA": tr("nra_help"),
                        "NRB": tr("nrb_help"),
                        "FAB": tr("fab_help"),
                        "FLB": tr("flb_help"),
                        "FRB": tr("frb_help"),
                        "RAB": tr("rab_help"),
                        "RLB": tr("rlb_help"),
                        "RRB": tr("rrb_help"),
                        "CR0": tr("cr0_help"),
                    }.get(prefix, tr("navcam_camera_unknown"))
                    column.html(
                        f'<span class="navcam-info-code" tabindex="0" '
                        f'data-tooltip="{escape(camera_help, quote=True)}">'
                        f'{escape(prefix)}</span>'
                    )
                for variant in variants:
                    cells = st.columns([1.7, *([1] * len(prefixes))], vertical_alignment="center")
                    display_variant = variant.removeprefix("_") or "_"
                    form_key = variant[-1:] if variant else ""
                    form_help = {
                        "D": tr("sample_DOWNSAMPLED"),
                        "F": tr("sample_FULL"),
                        "M": tr("sample_MIXED"),
                        "S": tr("sample_SUBFRAME"),
                        "T": tr("sample_THUMBNAIL"),
                    }.get(form_key, tr("navcam_variant_unknown"))
                    if variant.startswith("L"):
                        variant_help = f"{tr('navcam_variant_linearized')} {form_help}"
                    elif variant.startswith("_"):
                        variant_help = f"{tr('navcam_variant_not_linearized')} {form_help}"
                    else:
                        variant_help = form_help
                    cells[0].html(
                        f'<span class="navcam-variant-code" tabindex="0" '
                        f'data-tooltip="{escape(variant_help, quote=True)}">'
                        f'{escape(display_variant)}</span>'
                    )
                    preview_button(
                        cells[0], camera_label, label, f"{code}{variant}",
                        f"{camera}_{code}_{prefixes[0] if prefixes else 'all'}_{display_variant}",
                    )
                    marker = f"{code}{variant}"
                    for cell, prefix in zip(cells[1:], prefixes):
                        if variant not in compatibility[prefix]:
                            cell.caption("—")
                            continue
                        exact_key = f"{prefix}|{marker}"
                        checked = exact_key in selected_exact
                        new_value = cell.checkbox(
                            f"{prefix} {display_variant}", value=checked,
                            key=(
                            f"{camera}_matrix_{code}_{prefix}_{variant}_"
                                f"{int(checked)}"
                            ),
                            label_visibility="collapsed",
                        )
                        if new_value != checked:
                            if new_value:
                                selected_exact.add(exact_key)
                            else:
                                selected_exact.discard(exact_key)
                            st.session_state[state_key] = selected_exact
                            st.rerun()

    for group_index, (group_name, products) in enumerate(groups):
        st.markdown(f"##### {group_name}")
        if group_index > 0:
            st.caption(tr("engineering_approximate_preview"))
        for code, label, description in products:
            product_row(code, label, description)

    technical = [
        code for code in compatibility_all
        if code not in {product[0] for _, products in groups for product in products}
    ]
    if technical:
        st.markdown(f"##### {tr('engineering_unclassified_products')}")
        st.caption(tr("engineering_approximate_preview"))
        for code in technical:
            product_row(
                code, tr("engineering_generic_product").format(code=code),
                tr("engineering_unclassified_help"),
            )

    st.divider()
    if selected_exact:
        st.write(f"**{tr('custom_selected_combinations').format(count=len(selected_exact))}**")
    else:
        st.warning(tr("engineering_none_selected").format(camera=camera_label))
    if st.button(
        tr("custom_register_camera").format(camera=camera_label), key=f"{camera}_register", width="stretch",
        disabled=not selected_exact,
    ):
        desired: dict[str, list[str]] = {prefix: [] for prefix in CAMERA_OPTIONS[camera]["primary"]}
        for item in sorted(selected_exact):
            prefix, marker = item.split("|", 1)
            desired[prefix].append(marker)
        desired = {prefix: markers for prefix, markers in desired.items() if markers}
        current_normalized = {
            prefix: sorted(markers) for prefix, markers in current.items() if markers
        }
        if desired == current_normalized:
            changes.pop(camera, None)
            st.info(tr("custom_no_change"))
        else:
            changes[camera] = desired
            st.success(tr("engineering_change_registered").format(camera=camera_label))
        st.rerun()


def render_chemcam_customization(
    current: dict[str, set[str]], changes: dict[str, dict[str, list[str]]]
) -> None:
    """Render ChemCam using its small, instrument-specific product taxonomy."""
    camera = "chemcam"
    camera_label = "ChemCam"
    st.markdown(f"#### {tr('chemcam_custom_title')}")
    st.caption(tr("chemcam_custom_hint"))
    st.html(
        """
        <style>
        .navcam-info-code { position:relative; display:inline-block; padding:.12rem .38rem;
          border-radius:.22rem; background:#11141c; color:#77ef91; font-family:monospace;
          font-size:.78rem; font-weight:700; line-height:1.2; cursor:help; }
        .navcam-info-code::after { content:attr(data-tooltip); position:absolute; z-index:1000;
          left:calc(100% + .65rem); top:50%; width:max-content; max-width:22rem;
          padding:.65rem .8rem; border:1px solid rgba(155,106,50,.45); border-radius:.45rem;
          background:var(--secondary-background-color,#f7f3e8); color:var(--text-color,#191919);
          font-family:sans-serif; font-size:.82rem; font-weight:500; line-height:1.35;
          white-space:normal; box-shadow:0 .4rem 1.2rem rgba(0,0,0,.16); opacity:0;
          visibility:hidden; pointer-events:none; transform:translate(.2rem,-50%); }
        .navcam-info-code:hover::after, .navcam-info-code:focus::after {
          opacity:1; visibility:visible; transform:translate(0,-50%); }
        </style>
        """
    )

    products = (
        (tr("chemcam_group_original"), (
            ("EDR_F", tr("chemcam_edr_f_label"), tr("chemcam_edr_f_help")),
            ("EDR_T", tr("chemcam_edr_t_label"), tr("chemcam_edr_t_help")),
        )),
        (tr("chemcam_group_processed"), (
            ("PRC_F", tr("chemcam_prc_f_label"), tr("chemcam_prc_f_help")),
            ("PRCLF", tr("chemcam_prclf_label"), tr("chemcam_prclf_help")),
        )),
    )
    available = {
        "EDR_F": "EDR_F", "EDR_T": "EDR_T",
        "PRC_F": "PRC_F", "PRCLF": "PRCLF",
    }
    current_markers = set(current.get("CR0") or set())
    current_exact = {code for code, marker in available.items() if marker in current_markers}
    state_key = "chemcam_exact_selection_v3"
    source_key = "chemcam_exact_selection_source_v3"
    source_signature = tuple(sorted(current_exact))
    if st.session_state.get(source_key) != source_signature:
        st.session_state[source_key] = source_signature
        st.session_state[state_key] = set(current_exact)
    selected = set(st.session_state.get(state_key, set())) & set(available)
    st.session_state[state_key] = selected

    detail_key = "chemcam_product_detail_open"
    for group_name, entries in products:
        st.markdown(f"##### {group_name}")
        for code, label, description in entries:
            checked = code in selected
            row = st.columns([6, 1, 2, 0.55, 1.35], vertical_alignment="center")
            new_value = row[0].checkbox(
                label, value=checked, key=f"chemcam_product_{code}_{int(checked)}"
            )
            if new_value != checked:
                if new_value:
                    selected.add(code)
                else:
                    selected.discard(code)
                st.session_state[state_key] = selected
                st.rerun()
            row[1].html(
                f'<span class="navcam-info-code" tabindex="0" '
                f'data-tooltip="{escape(description, quote=True)}">{escape(code)}</span>'
            )
            row[2].caption(tr("chemcam_present_in_catalog") if code in current_exact else tr("chemcam_not_in_catalog"))
            if row[3].button("?", key=f"chemcam_help_{code}"):
                st.session_state[detail_key] = None if st.session_state.get(detail_key) == code else code
                st.rerun()
            preview_button(
                row[4], camera_label, label, code, f"chemcam_{code}",
                match_key=f"CR0 {code}",
            )
            if st.session_state.get(detail_key) == code:
                with st.container(border=True):
                    st.markdown(f"**{label} · {code}**")
                    st.write(description)
                    st.caption(tr("chemcam_cr0_note"))

    st.divider()
    st.write(f"**{tr('custom_selected_combinations').format(count=len(selected))}**")
    if st.button(
        tr("custom_register_camera").format(camera=camera_label),
        key="chemcam_register", width="stretch", disabled=not selected,
    ):
        desired = {"CR0": [available[code] for code in available if code in selected]}
        normalized = {"CR0": sorted(current_markers)} if current_markers else {}
        if {"CR0": sorted(desired["CR0"])} == normalized:
            changes.pop(camera, None)
            st.info(tr("custom_no_change"))
        else:
            changes[camera] = desired
            st.success(tr("engineering_change_registered").format(camera=camera_label))
        st.rerun()


def render_product_composition(catalog: str) -> None:
    """Collapsible section wrapper around `_render_product_composition_content`, remembering its open/closed state per catalog in `st.session_state`."""
    section_suffix = "pds" if catalog == "PDS" else "raw"
    button_key = f"composition_toggle_{section_suffix}"
    state_key = f"composition_open_{section_suffix}"
    st.html(
        """
        <style>
        .st-key-composition_toggle_pds,
        .st-key-composition_toggle_raw {
            width: fit-content !important;
        }
        .st-key-composition_toggle_pds button,
        .st-key-composition_toggle_raw button {
            min-height: 0 !important;
            width: auto !important;
            padding: .25rem 0 .55rem !important;
            border: 0 !important;
            background: transparent !important;
            box-shadow: none !important;
        }
        .st-key-composition_toggle_pds button:hover,
        .st-key-composition_toggle_raw button:hover,
        .st-key-composition_toggle_pds button:focus,
        .st-key-composition_toggle_raw button:focus {
            border: 0 !important;
            background: transparent !important;
            box-shadow: none !important;
        }
        .st-key-composition_toggle_pds button p,
        .st-key-composition_toggle_raw button p {
            font-size: 1.75rem !important;
            font-weight: 700 !important;
            line-height: 1.25 !important;
            color: inherit !important;
        }
        </style>
        """
    )
    is_open = bool(st.session_state.get(state_key, False))
    if st.button(
        tr("composition"),
        key=button_key,
        type="tertiary",
    ):
        st.session_state[state_key] = not is_open
        st.rerun()
    if st.session_state.get(state_key, False):
        _render_product_composition_content(catalog)


@st.fragment(run_every="2s")
def render_bootstrap_progress(job_id: str) -> None:
    """Self-refreshing progress panel for the first-run "generate local JSON" job: rows-written progress, and on failure a Retry button (relaunches via `start_bootstrap_json_job`)."""
    job = load_job(job_id)
    if not job:
        st.warning(tr("json_failed"))
        return
    status = str(job.get("status") or "")
    done = int(job.get("rows_done") or 0)
    total = int(job.get("rows_total") or 0)
    phase = str(job.get("phase") or "pds").upper()
    if status in {"queued", "running"}:
        st.markdown(f"**{tr('bootstrap_generating')} — {phase}**")
        st.progress(min(1.0, done / total) if total else 0.0, text=f"{done:,}/{total:,}".replace(",", "."))
        st.caption(f"{tr('estimated_remaining')}: {format_duration(job.get('estimated_remaining_seconds'))}")
        return
    if status == "failed":
        st.error(f"{tr('json_failed')}: {job.get('error', '')}")
        if st.button(tr("json_start"), key="bootstrap_retry_json", type="primary", width="stretch"):
            replacement = start_bootstrap_json_job()
            st.session_state.bootstrap_job_id = replacement["job_id"]
            st.rerun()
        return
    if status == "completed":
        st.success(tr("bootstrap_complete"))
        if st.button(tr("proceed"), key="bootstrap_finish", type="primary", width="stretch"):
            st.rerun()


def render_initial_setup() -> bool:
    """First-run onboarding gate: render the catalog-guide/install/generate-JSON flow until both catalogs are installed (and, per the user's bootstrap choice, their JSON generated); returns `True` once setup is complete and the caller should render the normal dashboard instead."""
    pds_ready = bool(local_pds_release(PROJECT_ROOT)) and (PROJECT_ROOT / "data" / "catalog" / "Catalog_PDS.parquet").exists()
    raw_ready = bool(local_raw_release(PROJECT_ROOT)) and (PROJECT_ROOT / "data" / "catalog" / "Catalog_RawArch.parquet").exists()
    pds_json = PROJECT_ROOT / "data" / "catalog" / "Catalog_PDS.json"
    raw_json = PROJECT_ROOT / "data" / "catalog" / "Catalog_RawArch.json"
    state = load_bootstrap_state(PROJECT_ROOT)
    choice = state.get("json_choice")
    if pds_ready and raw_ready and (choice == "download_only" or (pds_json.exists() and raw_json.exists())):
        return True

    with st.container(border=True):
        st.markdown(f"## {tr('first_start')}")
        st.caption(tr("first_start_hint"))
        if st.button(tr("catalog_guide_open"), key="open_catalog_guide", width="stretch"):
            show_catalog_guide()
        if not st.session_state.get("catalog_guide_seen", False):
            st.session_state.catalog_guide_seen = True
            show_catalog_guide()
        if not (pds_ready and raw_ready):
            st.markdown(f"### 1. {tr('catalog_required')}")
            left, right = st.columns(2)
            left.metric("PDS", tr("installed_short") if pds_ready else tr("missing_short"))
            right.metric("RAW Archive", tr("installed_short") if raw_ready else tr("missing_short"))
            if not pds_ready and st.button(tr("install_pds"), key="bootstrap_install_pds", type="primary", width="stretch"):
                bar = st.progress(0.0)
                try:
                    install_remote_pds_release(PROJECT_ROOT, lambda done, total: bar.progress(min(1.0, done / total) if total else 0.0))
                    _remote_pds_release_cached.clear()
                    st.session_state.catalog_statuses = load_local()
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))
            if not raw_ready and st.button(tr("install_raw"), key="bootstrap_install_raw", type="primary", width="stretch"):
                bar = st.progress(0.0)
                try:
                    install_remote_raw_release(PROJECT_ROOT, lambda done, total: bar.progress(min(1.0, done / total) if total else 0.0))
                    _remote_raw_release_cached.clear()
                    st.session_state.catalog_statuses = load_local()
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))
            return False

        st.success(f"PDS · {tr('installed_short')}   |   RAW Archive · {tr('installed_short')}")
        if choice == "generate":
            job = active_job_for_catalog("bootstrap") or latest_job("bootstrap", operation="bootstrap_json")
            if job:
                render_bootstrap_progress(str(job["job_id"]))
            elif pds_json.exists() and raw_json.exists():
                st.success(tr("bootstrap_complete"))
            else:
                st.error(tr("json_failed"))
                if st.button(tr("json_start"), key="bootstrap_restart_missing", type="primary", width="stretch"):
                    replacement = start_bootstrap_json_job()
                    st.session_state.bootstrap_job_id = replacement["job_id"]
                    st.rerun()
            return False

        st.markdown(f"### 2. {tr('json_choice_title')}")
        st.info(tr("json_choice_text"))
        yes_col, no_col = st.columns(2)
        if yes_col.button(tr("generate_both_json"), key="bootstrap_generate_json", type="primary", width="stretch"):
            save_bootstrap_choice(PROJECT_ROOT, "generate")
            job = start_bootstrap_json_job()
            st.session_state.bootstrap_job_id = job["job_id"]
            st.rerun()
        if no_col.button(tr("download_only"), key="bootstrap_download_only", width="stretch"):
            save_bootstrap_choice(PROJECT_ROOT, "download_only")
            st.rerun()
    return False


def render_configurations() -> None:
    """The Configurations expander: mode/language/theme pickers and the technical-product-names toggle, saved to `runtime.save_app_ui_config` (shared with `app/`'s own config)."""
    with st.expander(f"⚙ {tr('config')}", expanded=False):
        st.markdown(f"#### {tr('appearance')}")
        left, right = st.columns(2)
        with left:
            mode = st.selectbox(tr("mode"), ["dark", "light"], format_func=lambda value: tr(value), index=0 if st.session_state.mode == "dark" else 1)
            lang = st.selectbox(tr("language"), SUPPORTED_LANGS, index=SUPPORTED_LANGS.index(st.session_state.lang))
        with right:
            dark_values = theme_names("dark")
            light_values = theme_names("light")
            dark_theme = st.selectbox(tr("dark_theme"), dark_values, index=dark_values.index(st.session_state.theme_dark))
            light_theme = st.selectbox(tr("light_theme"), light_values, index=light_values.index(st.session_state.theme_light))
        technical_names = st.checkbox(
            tr("show_technical_product_names"),
            value=st.session_state.show_technical_product_names,
            help=tr("show_technical_product_names_help"),
        )
        if st.button(tr("save"), key="save_catalog_ui", width="stretch"):
            cfg = load_app_ui_config()
            cfg.update({
                "mode": mode,
                "lang": lang,
                "theme_dark": dark_theme,
                "theme_light": light_theme,
                "show_technical_product_names": technical_names,
            })
            save_app_ui_config(cfg)
            st.session_state.mode = mode
            st.session_state.lang = lang
            st.session_state.theme_dark = dark_theme
            st.session_state.theme_light = light_theme
            st.session_state.show_technical_product_names = technical_names
            st.success(tr("saved"))
            st.rerun()


def status_label(status: CatalogStatus) -> tuple[str, str]:
    """Map a `CatalogStatus` to a `(dot_emoji, text)` badge: red for invalid/unreachable, yellow for partial, white for never-checked, orange for update-available, green for aligned."""
    if not status.valid:
        return "🔴", tr("invalid")
    if status.remote_error:
        if status.remote_latest_sol is not None and status.remote_by_camera:
            return "🟡", tr("partial")
        return "🔴", tr("remote_error")
    if status.remote_latest_sol is None:
        return "⚪", tr("not_checked")
    if status.update_available:
        return "🟠", tr("available")
    return "🟢", tr("aligned")


def check_catalog(key: str) -> None:
    """Run `key`'s remote-status check (PDS or RAW), attach the result to its `CatalogStatus`, and save the combined report -- called by the "Check for updates" button."""
    statuses = load_local()
    index = 0 if key == "pds" else 1
    if key == "pds":
        latest, by_camera, error = fetch_pds_remote_status(
            PROJECT_ROOT, checked_by_camera=statuses[index].camera_last_checked,
        )
    else:
        latest, by_camera, error = fetch_raw_remote_status(statuses[index])
    attach_remote_status(statuses[index], latest, error, by_camera=by_camera)

    # Preserve the other catalog's most recent remote result during a
    # single-catalog check.
    previous = st.session_state.get("catalog_statuses", [])
    other = 1 - index
    if len(previous) == 2:
        statuses[other] = previous[other]
    st.session_state.catalog_statuses = statuses
    save_status_report(PROJECT_ROOT / "data/catalog/catalog_status_report.json", statuses)


def render_catalog(status: CatalogStatus, display_name: str) -> None:
    """The top-level dashboard card for one catalog: status badge, "Check for updates" button, per-camera Update buttons for cameras with new remote Sols (PDS: one button per camera; RAW: one combined button), an expandable details panel (product counts, Sol range, size, per-camera Sol coverage), and the integrity-check section below it."""
    icon, label = status_label(status)
    with st.container(border=True):
        st.markdown(f"## {display_name}")

        checked = status.camera_last_checked or {}
        remote_map = status.remote_by_camera or {}
        new_cameras = [camera.upper() for camera, sol in sorted(remote_map.items()) if int(sol) > int(checked.get(camera, -1))]
        sol_min = status.sol_min if status.sol_min is not None else "—"
        sol_max = status.sol_max if status.sol_max is not None else "—"

        main, details = st.columns([3.25, 1], gap="large")
        with main:
            # Per-Sol figures moved into the "Dettagli del catalogo" panel
            # (one line per camera, next to its product count) -- a single
            # big pair of numbers up here always blended different cameras
            # (their Sol coverage legitimately diverges) and took up space
            # better spent on the actual action: checking/updating. The
            # status badge moved down from the header corner to sit right
            # above that action, so it's the first thing this panel shows.
            st.markdown(f"<div class='catalog-state catalog-state-inline'>{icon}&nbsp; {escape(label)}</div>", unsafe_allow_html=True)
            action_left, action_center, action_right = st.columns([1, 2, 1], vertical_alignment="center")
            if action_center.button(tr("check_one"), key=f"check_{status.key}", type="primary", width="stretch"):
                with st.spinner(tr("checking")):
                    check_catalog(status.key)
                st.rerun()

            if new_cameras:
                st.markdown(
                    f"<div class='catalog-result'><span>✓</span> {escape(tr('new_cameras'))}: "
                    f"<strong>{escape(', '.join(new_cameras))}</strong></div>",
                    unsafe_allow_html=True,
                )
            elif status.remote_latest_sol is not None and not status.remote_error:
                st.success(tr("no_new"))
            if status.error:
                st.error(status.error)
            if status.remote_error:
                st.warning(tr("partial_hint") if status.remote_latest_sol is not None else tr("remote_error"))
            if status.update_available and not status.remote_error:
                if status.key in {"pds", "raw"}:
                    json_name = "Catalog_PDS.json" if status.key == "pds" else "Catalog_RawArch.json"
                    json_ready = (PROJECT_ROOT / "data" / "catalog" / json_name).exists()
                    start_sol = int(status.last_checked_sol or 0) + 1
                    end_sol = int(status.remote_latest_sol or start_sol)
                    job_running = bool(active_job_for_catalog(status.key))
                    if status.key == "pds":
                        # One camera per run, deliberately: each camera needs
                        # its own product-type/marker filter (see
                        # current_include_args in catalog_manager/customization.py),
                        # and a single-camera run is far easier to follow and
                        # interrupt than a multi-camera one that can run for hours.
                        st.caption(tr("update_one_camera_note"))
                        for camera in [c.casefold() for c in new_cameras]:
                            # Per-camera range, not the global min/max: the
                            # global end_sol is dominated by whichever camera
                            # (e.g. ChemCam) happens to be furthest ahead, and
                            # using it for every camera made every button scan
                            # a range mostly irrelevant to that camera.
                            camera_start = int(checked.get(camera, status.last_checked_sol or 0)) + 1
                            camera_end = int((status.remote_by_camera or {}).get(camera, status.remote_latest_sol) or camera_start)
                            seconds = max(60, (camera_end - camera_start + 1) * 3)
                            estimate = f"{format_duration(seconds * 0.75)}–{format_duration(seconds * 1.5)}"
                            if st.button(
                                f"{tr('update')} · {camera.upper()}", key=f"update_{status.key}_{camera}", width="stretch",
                                disabled=not json_ready or job_running,
                                help=None if json_ready else tr("update_json_required"),
                            ):
                                confirm_catalog_update(status.key, camera_start, camera_end, [camera], estimate)
                    else:
                        cameras = [camera.casefold() for camera in new_cameras]
                        seconds = max(60, (end_sol - start_sol + 1) * max(1, len(cameras)) * 3)
                        estimate = f"{format_duration(seconds * 0.75)}–{format_duration(seconds * 1.5)}"
                        if st.button(
                            tr("update"), key=f"update_{status.key}", width="stretch",
                            disabled=not json_ready or job_running,
                            help=None if json_ready else tr("update_json_required"),
                        ):
                            confirm_catalog_update(status.key, start_sol, end_sol, cameras, estimate)
                    render_catalog_update_progress(status.key)

        with details:
            with st.expander(tr("catalog_details"), expanded=False):
                st.markdown(
                    (
                        f"<div class='catalog-detail-summary'>"
                        f"<div><span>{escape(tr('products'))}</span><strong>{status.rows:,}</strong></div>"
                        f"<div><span>{escape(tr('range'))}</span><strong>{sol_min}–{sol_max}</strong></div>"
                        f"<div><span>{escape(tr('size'))}</span><strong>{escape(format_bytes(status.size_bytes))}</strong></div>"
                        f"</div>"
                    ).replace(",", "."),
                    unsafe_allow_html=True,
                )
                def _camera_sol_line(camera: str) -> str:
                    """Format one camera's Sol-coverage line: `"Sol N"`, or `"Sol N → M"` if a newer remote Sol was seen, or `"—"` if never checked."""
                    key = camera.casefold()
                    local_c = checked.get(key)
                    remote_c = remote_map.get(key)
                    if local_c is None:
                        return "—"
                    if remote_c is not None and int(remote_c) > int(local_c):
                        return f"Sol {local_c} → {remote_c}"
                    return f"Sol {local_c}"

                camera_items = "".join(
                    f"<div class='camera-item{' camera-update' if camera.upper() in new_cameras else ''}'>"
                    f"<div class='camera-item-row'><span>{escape(camera.upper())}</span>"
                    f"<strong>{count:,}</strong></div>"
                    f"<div class='camera-item-sol'>{escape(_camera_sol_line(camera))}</div>"
                    f"</div>".replace(",", ".")
                    for camera, count in (status.cameras or {}).items()
                )
                st.markdown(f"<div class='camera-grid camera-grid-side'>{camera_items}</div>", unsafe_allow_html=True)
                if status.remote_error:
                    st.markdown(f"**{tr('technical_details')}**")
                    st.code(status.remote_error, language=None, wrap_lines=True)
    st.markdown(f"<div class='job-title integrity-section-title'>{escape(tr('integrity'))}</div>", unsafe_allow_html=True)
    render_integrity_panel(status)


# ============================================================
# Module-level entrypoint: everything below runs top-to-bottom on every
# Streamlit rerun of this script. Session-state UI-config defaults, theme
# CSS, then the actual page: initial-setup gate, official-release panels,
# and the PDS/RAW tabs (each: dashboard card + integrity panel + product
# composition).
# ============================================================

ui_cfg = load_app_ui_config()
if "mode" not in st.session_state:
    st.session_state.mode = normalize_mode(ui_cfg.get("mode", DEFAULT_MODE))
if "lang" not in st.session_state:
    st.session_state.lang = ui_cfg.get("lang", "it") if ui_cfg.get("lang") in SUPPORTED_LANGS else "it"
if "theme_dark" not in st.session_state:
    st.session_state.theme_dark = ui_cfg.get("theme_dark", DEFAULT_THEME_BY_MODE["dark"])
if "theme_light" not in st.session_state:
    st.session_state.theme_light = ui_cfg.get("theme_light", DEFAULT_THEME_BY_MODE["light"])
if "show_technical_product_names" not in st.session_state:
    st.session_state.show_technical_product_names = bool(ui_cfg.get("show_technical_product_names", False))
if st.session_state.theme_dark not in MODE_THEMES["dark"]:
    st.session_state.theme_dark = DEFAULT_THEME_BY_MODE["dark"]
if st.session_state.theme_light not in MODE_THEMES["light"]:
    st.session_state.theme_light = DEFAULT_THEME_BY_MODE["light"]
if "catalog_statuses" not in st.session_state:
    st.session_state.catalog_statuses = load_local()

active_theme = st.session_state.theme_dark if st.session_state.mode == "dark" else st.session_state.theme_light
st.markdown(build_app_css(st.session_state.mode, active_theme), unsafe_allow_html=True)
active_palette = get_theme(st.session_state.mode, active_theme)
tab_accent = active_palette.get("accent", "#c77d2b")
st.markdown(
    f"""
    <style>
    html {{ zoom: 1 !important; background: {active_palette.get('bg', '#111111')} !important; }}
    body, .stApp {{ min-height: 100vh !important; background-color: {active_palette.get('bg', '#111111')} !important; }}
    section.main .block-container, .stMainBlockContainer {{ padding-bottom: 4rem !important; }}
    .hero-wrap {{ max-width: 310px; margin: -1.25rem auto -1.5rem auto; }}
    .hero-title {{ margin-top: -.4rem !important; }}
    .catalog-state {{ text-align: right; font-size: 1.15rem; font-weight: 650; }}
    .catalog-state.catalog-state-inline {{ text-align: left; margin-bottom: .85rem; }}
    .catalog-arrow {{ text-align: center; font-size: 2.2rem; opacity: .55; padding-top: 1.75rem; }}
    .catalog-facts {{ margin: .35rem 0 1rem; opacity: .78; display: flex; gap: .7rem; align-items: center; flex-wrap: wrap; }}
    .catalog-detail-summary {{ display: grid; gap: .45rem; margin: .1rem 0 .8rem; padding-bottom: .75rem; border-bottom: 1px solid rgba(127,127,127,.18); }}
    .catalog-detail-summary > div {{ display: flex; justify-content: space-between; align-items: baseline; gap: .8rem; }}
    .catalog-detail-summary span {{ font-size: .78rem; opacity: .68; }}
    .catalog-detail-summary strong {{ font-size: .92rem; }}
    .catalog-result {{ margin: .8rem 0; padding: .85rem 1rem; border: 1px solid color-mix(in srgb, #52b978 58%, transparent); border-left: 4px solid #52b978; border-radius: .5rem; background: color-mix(in srgb, #52b978 16%, transparent); color: color-mix(in srgb, #7de39f 72%, currentColor) !important; }}
    .catalog-result span {{ color: #63ce88 !important; font-weight: 800; margin-right: .35rem; }}
    .catalog-result strong {{ color: inherit !important; }}
    .camera-grid {{ display: grid; grid-template-columns: repeat(3, minmax(150px, 1fr)); gap: .6rem; margin: .65rem 0 .35rem; }}
    .camera-grid-side {{ grid-template-columns: 1fr; }}
    .camera-item {{ display: flex; flex-direction: column; gap: .3rem; padding: .7rem .85rem; border: 1px solid rgba(127,127,127,.18); border-radius: .45rem; background: rgba(127,127,127,.035); }}
    .camera-item-row {{ display: flex; justify-content: space-between; align-items: center; gap: 1rem; }}
    .camera-item span {{ font-size: .8rem; opacity: .72; }}
    .camera-item strong {{ font-size: 1rem; }}
    .camera-item-sol {{ font-size: .72rem; opacity: .55; }}
    .camera-item.camera-update {{ border-color: color-mix(in srgb, {tab_accent} 72%, transparent); background: color-mix(in srgb, {tab_accent} 14%, transparent); box-shadow: inset 3px 0 0 {tab_accent}; }}
    .camera-item.camera-update span, .camera-item.camera-update strong {{ color: {tab_accent} !important; opacity: 1; }}
    .camera-item.camera-update .camera-item-sol {{ color: {tab_accent} !important; opacity: .9; }}
    .job-title {{ margin: .8rem 0 .45rem; font-weight: 700; color: {tab_accent} !important; }}
    .camera-subtitle {{ margin: 1.25rem 0 .55rem; font-weight: 650; }}
    .camera-change-grid {{ display: grid; grid-template-columns: repeat(3, minmax(180px, 1fr)); gap: .6rem; }}
    .camera-change {{ display: flex; flex-direction: column; gap: .2rem; padding: .7rem .85rem; border-left: 3px solid {tab_accent}; background: rgba(127,127,127,.035); }}
    .camera-change span {{ font-size: .85rem; opacity: .72; }}
    .st-key-check_pds button, .st-key-check_raw button {{ min-height: 3.15rem; font-size: 1.02rem; font-weight: 650; }}
    div[data-testid="stMetricValue"] {{ font-size: 2rem; }}
    div[data-testid="stVerticalBlockBorderWrapper"] {{ box-shadow: 0 8px 28px rgba(0,0,0,.045); }}
    /* Compact rectangular help buttons used by the Navcam checklist. */
    [class*="st-key-navcam_help_"] button {{
        width: 2rem !important; min-width: 2rem !important; height: 1.8rem !important;
        min-height: 1.8rem !important; padding: 0 !important; border-radius: .3rem !important;
        font-weight: 750 !important; line-height: 1 !important;
    }}
    footer, [data-testid="stFooter"] {{ display: none !important; }}
    div[data-baseweb="tab-list"] {{
        gap: 2.25rem; margin: .65rem 0 1rem;
        border-bottom: 1px solid rgba(127,127,127,.18);
    }}
    button[data-baseweb="tab"] {{
        min-width: auto; min-height: 46px; padding: .65rem .15rem .8rem !important;
        border: 0 !important; border-radius: 0 !important;
        background: transparent !important; font-size: 1.05rem !important;
        font-weight: 600 !important; opacity: .62;
    }}
    button[data-baseweb="tab"][aria-selected="true"] {{
        color: {tab_accent} !important; opacity: 1;
        box-shadow: inset 0 -3px 0 {tab_accent};
    }}
    div[data-baseweb="tab-highlight"] {{ display: none !important; }}
    @media (max-width: 700px) {{
        .catalog-state {{ text-align: left; }}
        .catalog-arrow {{ display: none; }}
        div[data-baseweb="tab-list"] {{ gap: 1.5rem; }}
        .camera-grid, .camera-change-grid {{ grid-template-columns: 1fr; }}
    }}
    </style>
    """,
    unsafe_allow_html=True,
)
hero = hero_logo_html(st.session_state.mode, active_theme)
st.markdown(f'<div class="hero-wrap">{hero}</div>', unsafe_allow_html=True)
st.markdown(f'<div class="hero-title" style="font-size:1.55rem">{escape(tr("app_name"))}</div>', unsafe_allow_html=True)
render_configurations()
if not render_initial_setup():
    st.stop()
render_official_release_panel()

statuses = st.session_state.catalog_statuses
pds_json_ready = (PROJECT_ROOT / "data" / "catalog" / "Catalog_PDS.json").exists()
raw_json_ready = (PROJECT_ROOT / "data" / "catalog" / "Catalog_RawArch.json").exists()
pds_tab, raw_tab = st.tabs(["PDS", "RAW Archive"])
with pds_tab:
    render_catalog(statuses[0], "PDS")
    if pds_json_ready:
        render_product_composition("PDS")
with raw_tab:
    render_raw_official_release_panel()
    render_catalog(statuses[1], "RAW Archive")
    if raw_json_ready:
        render_product_composition("RAW Archive")
