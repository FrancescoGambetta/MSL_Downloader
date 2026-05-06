from __future__ import annotations

import importlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Optional
import sys

import requests


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def records_from_dataframe(df, *, limit: Optional[int] = None, require_lbl: bool = False) -> list[dict[str, Any]]:
    if df is None or len(df) == 0:
        return []

    if "img_url" not in df.columns:
        return []

    rows = df if limit is None else df.head(limit)
    records: list[dict[str, Any]] = []
    for _, row in rows.iterrows():
        img_url = _norm(row.get("img_url"))
        lbl_url = _norm(row.get("lbl_url"))
        base_url = _norm(row.get("base_url")) or _norm(row.get("sol_url"))
        if not img_url:
            continue
        if require_lbl and not lbl_url:
            continue
        records.append(
            {
                "img_url": img_url,
                "lbl_url": lbl_url,
                "base_url": base_url or None,
                "product_id": row.get("product_id"),
                "instrument_id": row.get("instrument_id"),
                "instrument_name": row.get("instrument_name"),
                "_row_id": row.get("_row_id"),
                "sol": row.get("sol"),
                "camera": row.get("camera"),
                "source": row.get("source"),
            }
        )
    return records


def download_records(
    records: list[dict[str, Any]],
    *,
    output_dir: str | Path,
    timeout: int = 120,
    skip_existing: bool = True,
    workers: int = 8,
    retries: int = 2,
    progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
) -> dict[str, Any]:
    out_dir = Path(output_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    downloaded = 0
    skipped = 0
    errors = 0
    images_already_present = 0
    images_with_new_downloads = 0

    def _present(path: Path) -> bool:
        try:
            return path.exists() and path.stat().st_size > 0
        except Exception:
            return False

    # Build per-record requirements and a de-duplicated list of file downloads.
    record_urls: list[dict[str, Any]] = []
    record_targets: list[list[Path]] = []
    target_to_url: dict[Path, str] = {}
    target_to_records: dict[Path, list[int]] = {}
    skipped_targets: set[Path] = set()

    for rec in records:
        img_url = _norm(rec.get("img_url"))
        lbl_url = _norm(rec.get("lbl_url"))
        pair_img_url = _norm(rec.get("pair_img_url"))
        pair_lbl_url = _norm(rec.get("pair_lbl_url"))
        if not img_url:
            continue
        urls = [img_url, lbl_url, pair_img_url, pair_lbl_url]
        idx = len(record_urls)
        record_urls.append({"img_url": img_url, "lbl_url": lbl_url})

        targets: list[Path] = []
        for url in urls:
            if not url:
                continue
            target = out_dir / Path(url).name
            targets.append(target)
            if skip_existing and _present(target):
                skipped_targets.add(target)
                continue
            if target not in target_to_url:
                target_to_url[target] = url
            target_to_records.setdefault(target, []).append(idx)
        record_targets.append(targets)

    total = len(record_urls)
    skipped = len(skipped_targets)

    if progress_callback is not None:
        progress_callback({"stage": "download_start", "current": 0, "total": total, "message": f"Download start: 0/{total}"})

    # Count images already fully present at the start (no missing downloads needed).
    for targets in record_targets:
        if not targets:
            continue
        if all(_present(t) for t in targets):
            images_already_present += 1

    # If everything is already present, short-circuit.
    if not target_to_url:
        if progress_callback is not None:
            progress_callback(
                {
                    "stage": "download_done",
                    "current": total,
                    "total": total,
                    "message": f"Download completed: images={total} downloaded=0 skipped={skipped} errors=0",
                }
            )
        return {
            "total": total,
            "downloaded": 0,
            "skipped": skipped,
            "errors": 0,
            "images_already_present": images_already_present,
            "images_with_new_downloads": 0,
            "output_dir": str(out_dir),
        }

    workers_i = int(workers) if isinstance(workers, int) else 8
    if workers_i <= 0:
        workers_i = 1

    # Thread-local sessions (requests.Session is not thread-safe).
    thread_local = threading.local()
    sessions: list[requests.Session] = []
    sessions_lock = threading.Lock()

    def _get_session() -> requests.Session:
        sess = getattr(thread_local, "session", None)
        if isinstance(sess, requests.Session):
            return sess
        sess = requests.Session()
        thread_local.session = sess
        with sessions_lock:
            sessions.append(sess)
        return sess

    downloaded_targets: set[Path] = set()
    completed_records = 0
    record_pending: list[int] = [0] * total
    for target, rec_ids in target_to_records.items():
        for rid in rec_ids:
            record_pending[rid] += 1

    pending_lock = threading.Lock()

    def _mark_target_done(target: Path) -> None:
        nonlocal completed_records
        rec_ids = target_to_records.get(target) or []
        to_emit: list[tuple[int, dict[str, Any]]] = []
        with pending_lock:
            for rid in rec_ids:
                record_pending[rid] = max(0, int(record_pending[rid]) - 1)
                if record_pending[rid] == 0:
                    completed_records += 1
                    to_emit.append((completed_records, record_urls[rid]))
        if progress_callback is not None:
            for cur, urls in to_emit:
                progress_callback(
                    {
                        "stage": "download_progress",
                        "current": cur,
                        "total": total,
                        "img_url": urls.get("img_url"),
                        "lbl_url": urls.get("lbl_url"),
                        "message": f"Download in progress: {cur}/{total} images",
                    }
                )

    def _download_one(url: str, target: Path) -> tuple[str, Optional[str]]:
        if skip_existing and _present(target):
            return "skipped", None

        tmp = target.with_suffix(target.suffix + ".part")
        last_err: Optional[str] = None
        for attempt in range(max(0, int(retries)) + 1):
            try:
                session = _get_session()
                resp = session.get(url, timeout=timeout, stream=True)
                try:
                    resp.raise_for_status()
                    with open(tmp, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=1024 * 256):
                            if chunk:
                                f.write(chunk)
                    tmp.replace(target)
                    return "downloaded", None
                finally:
                    try:
                        resp.close()
                    except Exception:
                        pass
            except Exception as e:
                last_err = str(e)
                try:
                    if tmp.exists():
                        tmp.unlink(missing_ok=True)
                except Exception:
                    pass
                if attempt < int(retries):
                    time.sleep(min(2.0, 0.25 * (2**attempt)))
        return "error", last_err

    futures = {}
    try:
        with ThreadPoolExecutor(max_workers=workers_i) as ex:
            for target, url in target_to_url.items():
                futures[ex.submit(_download_one, url, target)] = (url, target)

            for fut in as_completed(futures):
                url, target = futures[fut]
                status = "error"
                try:
                    status, _err = fut.result()
                except Exception:
                    status = "error"

                if status == "downloaded" and _present(target):
                    downloaded += 1
                    downloaded_targets.add(target)
                    if progress_callback is not None:
                        progress_callback(
                            {
                                "stage": "download_file_saved",
                                "filename": target.name,
                                "current": completed_records,
                                "total": total,
                                "message": f"Saved file: {target.name}",
                            }
                        )
                elif status == "error":
                    errors += 1
                _mark_target_done(target)
    finally:
        with sessions_lock:
            for sess in sessions:
                try:
                    sess.close()
                except Exception:
                    pass

    # Count images that had at least one new file downloaded.
    for targets in record_targets:
        if any(t in downloaded_targets for t in targets):
            images_with_new_downloads += 1

    if progress_callback is not None:
        progress_callback(
            {
                "stage": "download_done",
                "current": total,
                "total": total,
                "message": f"Download completed: images={total} downloaded={downloaded} skipped={skipped} errors={errors}",
            }
        )

    return {
        "total": total,
        "downloaded": downloaded,
        "skipped": skipped,
        "errors": errors,
        "images_already_present": images_already_present,
        "images_with_new_downloads": images_with_new_downloads,
        "output_dir": str(out_dir),
    }


def process_records_with_engine(
    records: list[dict[str, Any]],
    *,
    output_dir: str | Path,
    rover_csv_url: str,
    rover_csv_local_path: str | Path,
    dwn_dir: str | Path,
    engine_version: str = "agent-0.1.0",
    progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
) -> dict[str, Any]:
    if not records:
        return {"total": 0, "ok": 0, "errors": 0, "output_dir": str(Path(output_dir).expanduser())}

    out_dir = Path(output_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Force local DWNAPP/core engine implementation to avoid collisions
    # with older external copies.
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    module = importlib.import_module("core.engine_pipeline")
    process_products_from_catalog = getattr(module, "process_products_from_catalog")

    minimal_catalog = [
        {"img_url": r.get("img_url"), "lbl_url": r.get("lbl_url"), "base_url": r.get("base_url")}
        for r in records
        if _norm(r.get("img_url")) and _norm(r.get("lbl_url"))
    ]

    results = process_products_from_catalog(
        catalog=minimal_catalog,
        output_dir=out_dir,
        rover_csv_url=rover_csv_url,
        rover_csv_local_path=rover_csv_local_path,
        engine_version=engine_version,
        progress_callback=progress_callback,
    )

    ok = sum(1 for r in results if getattr(r, "status", "") == "ok")
    err = len(results) - ok
    return {
        "total": len(results),
        "ok": ok,
        "errors": err,
        "output_dir": str(out_dir),
    }
