"""Real download+process job orchestration -- the live counterpart of the mockup's
fake `setTimeout`-driven `runDownload` loop in `useDownloader.js`.

Mirrors `app/services/download_processing_service.py::run_download_and_process_interleaved`
(the builder's normal "RUN" path) as closely as practical for a stateless HTTP job:

- PDS products (always carry a `.LBL`): `core/portable_engine_adapter.process_records_with_engine`
  -> `core/engine_pipeline.py` (IMG decode, rover-CSV GPS match, EXIF-tagged JPEG,
  `.meta.json`), then optional Navcam/Hazcam alpha-pair RGBA compositing
  (`actions._apply_optional_alpha_pair_processing`), then raw `.IMG`/`.LBL` cleanup.
- ChemCam products: `actions._convert_chemcam_to_jpg` (its own TIFF/PNG-to-JPEG path,
  no PDS IMG decode involved).
- RAW Archive products (no `.LBL`): `download_records` (already JPEGs, just fetched
  as-is), then Mastcam Bayer demosaic where applicable
  (`actions._apply_mastcam_bayer_raw_processing`); after the batch, hardcoded EXIF +
  `.meta.json` are applied/written for every RAW product that downloaded successfully
  (`actions._apply_raw_archive_hardcoded_exif` / `actions._write_raw_archive_meta`) --
  same two-phase order the real pipeline uses, not per-record.
- After every record: MARDI geometric correction where applicable
  (`actions._maybe_correct_mardi_products`, batched per source at the end, like the
  real pipeline), then the user's chosen folder layout
  (`OutputOrganizerService.organize_simple_layout`).

Reuses `app/actions.py`'s already-wired, session_state-free module-level helper
functions directly (`actions._apply_mastcam_bayer_raw_processing`, etc.) rather than
re-deriving each service's dependency injection by hand -- these are the exact same
functions the Streamlit builder calls, confirmed free of `st.session_state` reads
(the one that isn't, `_attach_optional_alpha_pairs`, is called here with an explicit
`reference_df` instead of relying on its `state["df"]` fallback).

Jobs run in a background thread (I/O-bound work; the engine functions above already
parallelize internally) and are tracked in an in-memory `_JOBS` dict, polled via
`get_job`. No persistence across API restarts -- fine for local single-user use.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import runtime as app_runtime
import actions as app_actions
from core.portable_engine_adapter import download_records, process_records_with_engine

from webapi import catalog_service, i18n_state
from webapi.i18n_state import t

MAX_LOG_ENTRIES = 200

_lock = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}
# job_id -> {product_id: absolute_jpg_path}, the only files /api/files/{job_id}/{id}
# is ever allowed to serve (populated once a job finishes, see _run_job's end).
_SERVABLE_FILES: dict[str, dict[str, str]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_source(value: Any) -> str:
    return "raw" if str(value or "").strip().lower() == "raw" else "pds"


def _output_dir_for_source(base: Path, source: str) -> Path:
    """`PDS/` or `RAW_PHOTOS/` subfolder of `base`, matching `RecordOutputUtilsService.output_dir_for_source`."""
    bucket = "RAW_PHOTOS" if _normalize_source(source) == "raw" else "PDS"
    out = base if base.name.upper() == bucket else base / bucket
    out.mkdir(parents=True, exist_ok=True)
    return out


def _rover_csv_config() -> tuple[str, Path]:
    project_root = app_runtime.PROJECT_ROOT
    cfg = app_runtime.load_json(app_runtime._resolve_msl_config())
    rover_csv_url = app_runtime.normalize_text(cfg.get("coord_url"))
    rel = app_runtime.normalize_text(cfg.get("coord_local_path")) or "data/reference/geo/localized_interp_demv2.csv"
    rover_csv_local = (project_root / rel).resolve()
    return rover_csv_url, rover_csv_local


def _append_log(job: dict[str, Any], kind: str, message: str) -> None:
    # `seq` is a monotonically increasing id, never reused or reset -- unlike
    # the entry's position in `job["log"]`, which shifts every time the list
    # below is trimmed. A client tracking "last seq seen" (see
    # useDownloader.js) can always tell exactly which entries are new, even
    # once old ones have aged out of this list; a client tracking "how many
    # entries have I consumed" against a *trimmed* list would eventually see
    # log.length stop growing past what it already consumed and conclude
    # (wrongly) that nothing new ever arrives again.
    job["_log_seq"] = int(job.get("_log_seq", 0)) + 1
    job["log"].append({"seq": job["_log_seq"], "ts": _now(), "type": kind, "message": message})
    if len(job["log"]) > MAX_LOG_ENTRIES:
        job["log"] = job["log"][-MAX_LOG_ENTRIES:]


def _cleanup_raw_source_files(rec: dict[str, Any], out_dir: Path) -> None:
    """Delete the raw downloaded `.IMG`/`.LBL` once a PDS product has been converted -- canonical output is the JPG (+ optional mask/RGBA PNGs)."""
    for url_key in ("img_url", "lbl_url"):
        url = app_runtime.normalize_text(rec.get(url_key))
        if not url:
            continue
        raw_path = out_dir / Path(url).name
        if raw_path.exists() and raw_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            raw_path.unlink(missing_ok=True)


def _run_job(job_id: str, records: list[dict[str, Any]], output_folder: str, organize: dict[str, bool], lang: str = "it") -> None:
    # Sets this THREAD's current language (i18n_state.py) for the whole job --
    # every t() call below, and every app_actions.* call that uses the
    # translator wired in main.py, reads it from here rather than needing
    # `lang` threaded through each individual function call.
    i18n_state.set_current_lang(lang)
    job = _JOBS[job_id]
    base = Path(output_folder).expanduser()
    base.mkdir(parents=True, exist_ok=True)
    rover_csv_url, rover_csv_local = _rover_csv_config()
    dwn_dir = app_runtime.PROJECT_ROOT.parent / "DWN"
    engine_version = "webapi-0.1.0"

    # Alpha-pair candidates (Navcam/Hazcam ILTLF/ILT_F/RADLF <-> MXYLF mask) need to be
    # attached before processing -- reuses the real catalog already cached by the
    # search endpoint as the mask lookup source, so this needs no Streamlit session.
    try:
        df_pds, df_raw = catalog_service._load_combined()
        reference_df = df_pds
    except Exception:  # noqa: BLE001
        reference_df = None
    records, paired_candidates = app_actions._attach_optional_alpha_pairs(records, reference_df=reference_df)
    if paired_candidates:
        _append_log(job, "info", t("webapi_alpha_candidates", count=paired_candidates))

    total = len(records)
    job["progress"] = {"done": 0, "total": total}
    _append_log(job, "info", t("webapi_starting", total=total))

    # Parallel pre-download, mirroring app/services/download_processing_service.py::
    # run_download_and_process_interleaved (the real Streamlit "RUN" path). Fetching
    # every record's raw IMG/LBL (or RAW jpg) up front with workers=16, before the
    # per-record loop below, is what makes that pipeline fast -- the loop's own
    # download_records()/process_records_with_engine() calls already skip_existing,
    # so once this phase has landed the files they become cheap local reads instead
    # of one network round-trip per record. Without this phase, a job downloading
    # N records pays N sequential round-trips instead of ~N/16.
    pds_to_prefetch = [rec for rec in records if _normalize_source(rec.get("source")) == "pds"]
    raw_to_prefetch = [rec for rec in records if _normalize_source(rec.get("source")) == "raw"]
    predownload_downloaded = predownload_errors = 0
    for source_name, source_records in (("pds", pds_to_prefetch), ("raw", raw_to_prefetch)):
        if not source_records or job["cancel_requested"]:
            continue
        _append_log(job, "info", t("webapi_prefetch_start", source=source_name.upper(), count=len(source_records)))

        # Throttled progress during the (potentially several-second) parallel
        # fetch -- without this the log line above just sits there unchanged
        # until the whole batch finishes, which reads as "stuck".
        last_emit = {"t": 0.0}

        def on_prefetch_event(ev: dict[str, Any], *, source: str = source_name, count: int = len(source_records)) -> None:
            stage = str(ev.get("stage") or "")
            if stage not in {"download_progress", "download_done"}:
                return
            try:
                current = int(ev.get("current") or 0)
                total_n = int(ev.get("total") or count)
            except (TypeError, ValueError):
                return
            now = time.monotonic()
            force = stage == "download_done" or current >= total_n
            if not force and (now - last_emit["t"]) < 0.4:
                return
            last_emit["t"] = now
            _append_log(job, "info", t("webapi_prefetch_progress", source=source.upper(), current=current, total=total_n))

        dl_stats = download_records(
            source_records,
            output_dir=str(_output_dir_for_source(base, source_name)),
            timeout=120,
            skip_existing=True,
            workers=16,
            progress_callback=on_prefetch_event,
        )
        predownload_downloaded += int(dl_stats.get("downloaded", 0))
        predownload_errors += int(dl_stats.get("errors", 0))
    if pds_to_prefetch or raw_to_prefetch:
        _append_log(
            job, "info",
            t("webapi_prefetch_done", downloaded=predownload_downloaded, errors=predownload_errors),
        )

    ok = 0
    errors = 0
    succeeded_ids: list[str] = []
    pds_done: list[dict[str, Any]] = []
    raw_done: list[dict[str, Any]] = []

    for idx, rec in enumerate(records, start=1):
        if job["cancel_requested"]:
            _append_log(job, "info", t("webapi_stopped"))
            break

        source = _normalize_source(rec.get("source"))
        product_id = rec.get("product_id") or Path(str(rec.get("img_url") or "")).stem
        out_dir = _output_dir_for_source(base, source)
        camera = app_runtime.normalize_text(rec.get("camera")).strip().lower()
        is_chemcam = camera == "chemcam"

        # No separate "download/convert in progress" line here: the parallel
        # pre-download phase above already fetched the raw files, so by the
        # time a record reaches this loop it's just a fast local read/convert
        # -- logging both a "starting" and a "done" line per record produced
        # 2-3x more log volume than there was anything to say, which is what
        # made the live log feel like it was dumping in noisy bursts.
        item_ok = False
        try:
            if is_chemcam:
                # convert_chemcam_to_jpg expects the raw TIFF (+ optional LBL) already
                # on disk -- normally already true from the pre-download phase above;
                # this call is a fast skip_existing no-op unless that phase missed it.
                dl_stats = download_records([rec], output_dir=str(out_dir), timeout=120, skip_existing=True, workers=4)
                if int(dl_stats.get("errors", 0)) > 0:
                    item_ok, reason = False, "chemcam_raw_download_failed"
                else:
                    item_ok, reason = app_actions._convert_chemcam_to_jpg(
                        rec, out_dir,
                        rover_csv_url=rover_csv_url,
                        rover_csv_local_path=rover_csv_local,
                        engine_version=engine_version,
                    )
                if not item_ok:
                    _append_log(job, "error", t("webapi_chemcam_failed", product=product_id, reason=reason))
                else:
                    _cleanup_raw_source_files(rec, out_dir)
            elif source == "pds" and rec.get("lbl_url"):
                stats = process_records_with_engine(
                    [rec], output_dir=str(out_dir),
                    rover_csv_url=rover_csv_url, rover_csv_local_path=rover_csv_local,
                    dwn_dir=dwn_dir, engine_version=engine_version,
                )
                item_ok = int(stats.get("ok", 0)) > 0
                if item_ok:
                    a_ok, _a_skip = app_actions._apply_optional_alpha_pair_processing([rec], output_dir=out_dir)
                    if a_ok:
                        _append_log(job, "info", t("webapi_alpha_generated", product=product_id))
                _cleanup_raw_source_files(rec, out_dir)
                pds_done.append(rec)
            else:
                dl_stats = download_records([rec], output_dir=str(out_dir), timeout=120, skip_existing=True, workers=4)
                item_ok = int(dl_stats.get("errors", 0)) == 0 and int(dl_stats.get("total", 0)) > 0
                if item_ok and app_actions._is_raw_archive_mastcam_record(rec):
                    applied, reason = app_actions._apply_mastcam_bayer_raw_processing(rec, out_dir)
                    if applied:
                        _append_log(job, "info", t("webapi_bayer_applied", product=product_id))
                    elif reason:
                        _append_log(job, "info", t("webapi_bayer_skipped", product=product_id, reason=reason))
                if item_ok:
                    raw_done.append(rec)
        except Exception as exc:  # noqa: BLE001
            item_ok = False
            _append_log(job, "error", t("webapi_item_error", product=product_id, error=f"{type(exc).__name__}: {exc}"))

        if item_ok:
            ok += 1
            succeeded_ids.append(str(product_id))
            app_actions._finalize_product_jpg_only(out_dir, str(product_id))
            _append_log(job, "success", t("webapi_item_done", product=product_id))
        else:
            errors += 1
            _append_log(job, "error", t("webapi_item_failed", product=product_id))

        job["progress"] = {"done": idx, "total": total}

    # Post-batch steps the real pipeline also runs once per source, not per record.
    if not job["cancel_requested"]:
        if pds_done:
            corrected, _extra = app_actions._maybe_correct_mardi_products(pds_done, _output_dir_for_source(base, "pds"))
            if corrected:
                _append_log(job, "info", t("webapi_mardi_applied", count=corrected))
        if raw_done:
            corrected, _extra = app_actions._maybe_correct_mardi_products(raw_done, _output_dir_for_source(base, "raw"))
            if corrected:
                _append_log(job, "info", t("webapi_mardi_applied_raw", count=corrected))
            raw_out_dir = _output_dir_for_source(base, "raw")
            exif_applied, _exif_skipped = app_actions._apply_raw_archive_hardcoded_exif(raw_done, output_dir=raw_out_dir)
            meta_written, _meta_skipped = app_actions._write_raw_archive_meta(
                raw_done, output_dir=raw_out_dir,
                rover_csv_url=rover_csv_url, rover_csv_local_path=str(rover_csv_local),
                engine_version=engine_version,
            )
            _append_log(job, "info", t("webapi_raw_exif_meta", exif=exif_applied, meta=meta_written))

        if organize.get("by_camera") or organize.get("by_sol"):
            try:
                organizer = app_actions._get_output_organizer()
                result = organizer.organize_simple_layout(
                    str(base),
                    divide_by_sol=bool(organize.get("by_sol")),
                    divide_by_camera=bool(organize.get("by_camera")),
                )
                # result.message already comes back translated: organize_simple_layout
                # uses the same injected translator (i18n_state.t) as everything else here.
                _append_log(job, "info", result.message)
            except Exception as exc:  # noqa: BLE001
                _append_log(job, "error", t("webapi_organize_failed", error=f"{type(exc).__name__}: {exc}"))

    # Resolve each succeeded product's final JPG path (post-organize, wherever it
    # actually ended up) and register it as servable -- /api/files/{job_id}/{product_id}
    # only ever serves files a job itself just wrote, never an arbitrary path.
    output_files: dict[str, str] = {}
    for product_id in succeeded_ids:
        found = _find_file_any_case(base, f"{product_id}.jpg")
        if found is not None:
            output_files[product_id] = str(found)
    with _lock:
        _SERVABLE_FILES[job_id] = output_files

    job["result"] = {
        "ok": ok,
        "errors": errors,
        "total": total,
        "cancelled": job["cancel_requested"],
        "succeeded_product_ids": succeeded_ids,
        "output_files": output_files,
    }
    job["status"] = "cancelled" if job["cancel_requested"] else "completed"
    job["completed_at_utc"] = _now()
    _append_log(job, "success", t("webapi_process_complete", ok=ok, errors=errors))


def start_job(records: list[dict[str, Any]], output_folder: str, organize: dict[str, bool] | None = None, lang: str = "it") -> str:
    """Launch a download+process job in a background thread; returns its `job_id`. `lang` is the frontend's currently selected UI language -- every log line this job produces (see i18n_state.py) comes back translated into it."""
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        _JOBS[job_id] = {
            "job_id": job_id,
            "status": "running",
            "created_at_utc": _now(),
            "completed_at_utc": None,
            "log": [],
            "progress": {"done": 0, "total": len(records)},
            "result": None,
            "cancel_requested": False,
        }
    thread = threading.Thread(target=_run_job, args=(job_id, records, output_folder, organize or {}, lang), daemon=True)
    thread.start()
    return job_id


def get_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _JOBS.get(job_id)
        return dict(job) if job is not None else None


def request_cancel(job_id: str) -> bool:
    with _lock:
        job = _JOBS.get(job_id)
        if job is None:
            return False
        job["cancel_requested"] = True
        return True


def _find_file_any_case(base: Path, filename: str) -> Path | None:
    """`app_runtime._find_file_by_exact_name`, tried against `filename` as given and
    lowercased.

    That function's own name-matching is a plain `==` on the on-disk entry
    name (see `RuntimeOutputIndexService.find_file_by_exact_name`) -- exact,
    not case-insensitive, even though Windows' filesystem itself doesn't care.
    ChemCam products keep an uppercase `product_id` in the catalog (matching
    every other camera's convention) but the actual TIFF/JPG/meta.json PDS
    writes to disk keep PDS-geosciences' own lowercase filenames -- so an
    exact-case search for a ChemCam product would silently never find a file
    that is genuinely sitting right there. Every other camera's on-disk name
    already matches its product_id's case, so this is a no-op fallback for them.
    """
    found = app_runtime._find_file_by_exact_name(base, filename)
    if found is not None:
        return found
    lowered = filename.lower()
    if lowered != filename:
        found = app_runtime._find_file_by_exact_name(base, lowered)
    return found


def get_servable_file(job_id: str, product_id: str, root_hint: str | None = None) -> Path | None:
    """Return the absolute path a finished job wrote for `product_id`, or `None` if it can't be found either way.

    `_SERVABLE_FILES` is an in-memory dict, wiped on every webapi restart --
    a product a job wrote yesterday is still on disk today, but its job_id is
    gone from memory. When the in-memory lookup misses, fall back to a real
    filesystem search (the same `_find_file_by_exact_name` the job itself
    uses to register files in the first place) so a previously-downloaded
    image saved in the frontend's localStorage doesn't go permanently
    unpreviewable after a restart.

    `root_hint` is the output folder the frontend recorded for that specific
    product at save time (see `mslApi.js::fileUrl`) -- far more likely to be
    right than the server's own generic default, since users routinely pick a
    custom download folder the backend has no other memory of. Falls back to
    `_default_download_path()` if no hint was given or nothing was found there.
    """
    with _lock:
        files = _SERVABLE_FILES.get(job_id)
    if files:
        path_text = files.get(product_id)
        if path_text:
            path = Path(path_text)
            if path.is_file():
                return path

    candidates: list[Path] = []
    if root_hint:
        try:
            candidates.append(Path(root_hint))
        except Exception:  # noqa: BLE001
            pass
    try:
        candidates.append(Path(app_runtime._default_download_path()))
    except Exception:  # noqa: BLE001
        pass

    for base in candidates:
        try:
            found = _find_file_any_case(base, f"{product_id}.jpg")
        except Exception:  # noqa: BLE001
            continue
        if found is not None and found.is_file():
            return found
    return None


def get_meta_json(job_id: str, product_id: str, root_hint: str | None = None) -> dict[str, Any] | None:
    """Return `product_id`'s real `.meta.json` (written by the engine after processing),
    curated to the same field set the Streamlit app's metadata panel shows
    (`app/ui_panels/metadata_panel.py::render_metadata_panel`'s `quick` dict) -- the
    frontend's own React panel previously showed catalog-search-time values instead of
    ever reading this file, which is the gap this closes.

    Same job-registry-miss fallback as `get_servable_file`: searches by exact
    filename under `root_hint` (the record's saved output folder) or the
    default download path if the in-memory job registry doesn't have it.
    """
    path = None
    with _lock:
        files = _SERVABLE_FILES.get(job_id)
    if files:
        jpg_text = files.get(product_id)
        if jpg_text:
            candidate = Path(jpg_text).with_name(f"{product_id}.meta.json")
            if candidate.is_file():
                path = candidate
    if path is None:
        candidates: list[Path] = []
        if root_hint:
            try:
                candidates.append(Path(root_hint))
            except Exception:  # noqa: BLE001
                pass
        try:
            candidates.append(Path(app_runtime._default_download_path()))
        except Exception:  # noqa: BLE001
            pass
        for base in candidates:
            try:
                found = _find_file_any_case(base, f"{product_id}.meta.json")
            except Exception:  # noqa: BLE001
                continue
            if found is not None and found.is_file():
                path = found
                break
    if path is None:
        return None

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    product = raw.get("product") or {}
    sources = raw.get("sources") or {}
    outputs = raw.get("outputs") or {}
    result: dict[str, Any] = {
        "product_id": product.get("product_id"),
        "instrument_id": product.get("instrument_id"),
        "instrument_name": product.get("instrument_name"),
        "sol": product.get("sol"),
        "site": product.get("site"),
        "drive": product.get("drive"),
        "pose": product.get("pose"),
        "img_url": sources.get("img_url"),
        "jpg_path": outputs.get("jpg_path"),
        "meta_json_path": outputs.get("meta_json_path"),
        "warnings": raw.get("warnings") or [],
        "errors": raw.get("errors") or [],
    }

    # Beyond the Streamlit panel's own "quick" set: the real .meta.json also
    # carries rover GPS/orientation (from the geo CSV match), the EXIF values
    # actually burned into the JPG, and per-camera post-processing details
    # (Mastcam Bayer, Navcam/Hazcam alpha-pair, ChemCam conversion) that
    # neither app has ever surfaced. Curated into one "advanced" block so the
    # frontend can show it as an optional expandable section; omitted
    # entirely when a section has nothing in it (e.g. no alpha-pair applied).
    csv_row = raw.get("csv_row") or {}
    exif_written = raw.get("exif_written") or {}
    post_processing = raw.get("post_processing") or {}
    alpha_pair = raw.get("alpha_pair") or {}
    advanced: dict[str, Any] = {}
    if csv_row:
        advanced["gps"] = {
            "latitude": csv_row.get("planetodetic_latitude"),
            "longitude": csv_row.get("longitude"),
            "elevation": csv_row.get("elevation"),
        }
        advanced["orientation"] = {
            "roll": csv_row.get("roll"),
            "pitch": csv_row.get("pitch"),
            "yaw": csv_row.get("yaw"),
        }
    if exif_written:
        advanced["exif"] = exif_written
    if post_processing:
        advanced["post_processing"] = post_processing
    if alpha_pair:
        advanced["alpha_pair"] = {
            "pair_product_id": alpha_pair.get("pair_product_id"),
            "mask_coverage": alpha_pair.get("mask_coverage"),
        }
    if advanced:
        result["advanced"] = advanced
    return result
