"""The `integrity_check` worker (read-only): re-scans NASA (PDS or RAW, per `--catalog`)
for one camera over a Sol range and compares what's found against the local Parquet
catalog, reporting missing products -- without ever modifying the local catalog itself
(compare the `*_repair_worker.py`/`*_update_worker.py` files, which do write). Its
result feeds `jobs.start_pds_repair_job`/`start_raw_repair_job` (repair the gaps found)
and the dashboard's freshness display. Driven by every one of
`jobs.start_pds_integrity_job`, `start_raw_integrity_job`, `start_pds_failed_retry`,
`start_pds_resume_job`, `start_raw_failed_retry`, `start_raw_resume_job` -- this single
worker handles first runs, retries of just the failed locations, and checkpoint resumes
alike, distinguished by `--retry-of`/`--resume-of`.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urljoin, urlparse

import pandas as pd

from catalog_manager.jobs import JOBS_ROOT, PROJECT_ROOT, job_state_path, load_job
from catalog_manager.services import RAW_MANIFEST_URLS
from core.make_msl_catalog import (
    PDSClient,
    _camera_cfg,
    _extract_links_with_sizes,
    _is_under_base,
    _normalise_url,
    discover_collections_for_camera,
    discover_sol_locations,
)
from core.make_msl_catalog_pre3000 import _record_is_allowed
from core.make_msl_raw_catalog import get_json as raw_get_json, raw_record
from core.make_msl_chemcam_catalog import (
    CHEMCAM_RDR_DATA_URL,
    discover_rmi_products,
    discover_sol_urls,
)


# Local catalog file each --catalog value reads from/compares against.
CATALOG_FILES = {"pds": "Catalog_PDS.parquet", "raw": "Catalog_RawArch.parquet"}


def utc_now() -> str:
    """Current UTC timestamp, ISO-8601 with second precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json_atomic(path: Path, payload: Any) -> None:
    """Write `payload` to `path` as JSON atomically (temp file + replace), retrying briefly on Windows `PermissionError` (a concurrent reader/antivirus holding a transient lock)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            temp.write_text(content, encoding="utf-8")
            temp.replace(path)
            return
        except PermissionError as exc:
            # On Windows a reader or antivirus can hold the destination for a
            # few milliseconds. Retrying preserves atomicity without turning
            # a healthy scan into a failed job.
            last_error = exc
            time.sleep(0.05 * (attempt + 1))
    if last_error is not None:
        raise last_error


def scan_location_pds(
    client: PDSClient,
    location: Any,
    base_url: str,
    camera: str,
    selection_rules: dict[str, Any],
) -> list[dict[str, Any]]:
    """List `location`'s Sol directory and return only the `.IMG` products `_record_is_allowed` (the same rule the builder itself uses) says belong to `camera`."""
    html = client.get_text(location.sol_url)
    products: list[dict[str, Any]] = []
    for entry in _extract_links_with_sizes(html):
        href = str(entry.get("href", "")).strip()
        if not href or href.endswith("/") or not href.upper().endswith(".IMG"):
            continue
        img_url = _normalise_url(urljoin(location.sol_url, href))
        if not _is_under_base(img_url, base_url):
            continue
        stem = Path(href).stem
        product = {
            "product_id": stem,
            "sol": int(location.sol),
            "img_url": img_url,
            "lbl_url": _normalise_url(urljoin(location.sol_url, f"{stem}.LBL")),
            "img_name": Path(href).name,
            "img_size_bytes": entry.get("size_bytes"),
            "collection": location.collection,
            "sol_url": location.sol_url,
        }
        allowed, _reason = _record_is_allowed(camera, product, selection_rules)
        if allowed:
            products.append(product)
    return products


def scan_location_raw(location: Any, camera: str, timeout: int, retries: int) -> tuple[list[dict[str, Any]], set[str]]:
    """RAW has no per-camera directories to filter by suffix/size like PDS:
    each Sol's manifest catalog_url returns every camera's images together,
    and raw_record()/_raw_camera() (the same logic core/make_msl_raw_catalog.py
    uses to build the catalog) is what tells them apart.

    Also returns every product_id seen at this Sol regardless of camera
    classification (thumbnails included). The local RAW catalog has old
    entries whose sample_type was never recorded, so a product that
    _raw_camera() excludes today (e.g. it turns out to be a thumbnail) can't
    be told apart, from local data alone, from one NASA genuinely removed.
    Cross-checking against everything actually present at that Sol -- which
    this scan already downloaded, so it costs nothing extra -- resolves that
    ambiguity without a second request.
    """
    payload, resolved = raw_get_json((location.sol_url,), timeout, retries)
    products: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in payload.get("images", []):
        if not isinstance(item, dict):
            continue
        parsed = raw_record(item, int(location.sol), resolved)
        if parsed is not None:
            seen_ids.add(str(parsed[1]["product_id"]))
            if parsed[0] == camera:
                products.append(parsed[1])
            continue
        img_url = str(item.get("urlList") or item.get("url") or "").strip()
        if img_url:
            seen_ids.add(Path(urlparse(img_url).path).stem)
    return products, seen_ids


def discover_raw_locations(sol_start: int, sol_end: int, timeout: int, retries: int) -> tuple[list[Any], str]:
    """RAW has a single manifest listing every Sol's catalog_url -- no
    per-collection crawl needed, unlike PDS's discover_collections_for_camera.
    A manifest fetch failure is deliberately NOT tolerated here (unlike a
    single PDS collection failing): there is only one manifest, so failing
    it should fail the whole job rather than silently report 0 remote
    products (which would look like everything local is "missing")."""
    manifest, manifest_url = raw_get_json(RAW_MANIFEST_URLS, timeout, retries)
    entries = {
        int(item["sol"]): str(item.get("catalog_url") or "")
        for item in manifest.get("sols", [])
        if isinstance(item, dict) and item.get("sol") is not None
        and sol_start <= int(item["sol"]) <= sol_end and item.get("catalog_url")
    }
    locations = [
        SimpleNamespace(
            sol=sol, sol_url=url, collection="raw-images-web-manifest",
            data_root="image_manifest/catalog_url", sol_dir_name=f"SOL{sol}",
        )
        for sol, url in entries.items()
    ]
    return locations, manifest_url


def acquire_lock(catalog: str, job_id: str) -> Path:
    """Exclusively create `{catalog}.lock` naming `job_id` as owner; raises if another job already holds it. This worker's own extra safety net alongside `jobs.active_job_for_catalog`'s state-file check."""
    path = JOBS_ROOT / "locks" / f"{catalog}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(job_id + "\n")
    except FileExistsError as exc:
        owner = path.read_text(encoding="utf-8", errors="replace").strip()
        raise RuntimeError(f"Catalog {catalog} is locked by {owner or 'another job'}") from exc
    return path


def run(args: argparse.Namespace) -> int:
    """Run one integrity check: load the local catalog slice for `args.camera`+Sol range, discover the matching remote locations (full discovery, or just `--retry-of`'s failed locations, or `--resume-of`'s checkpoint), scan them concurrently, and diff local vs. remote to report missing/local-only products. Returns a process-style exit code (`0` completed, `1` failed, `2` cancelled)."""
    state_path = job_state_path(args.job_id)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    lock_path = acquire_lock(args.catalog, args.job_id)
    cancel_path = JOBS_ROOT / "active" / f"{args.job_id}.cancel"
    started = time.monotonic()

    def update(**values: Any) -> None:
        """Merge `values` into the job state, refresh the heartbeat, and persist."""
        state.update(values)
        state["heartbeat_at_utc"] = utc_now()
        write_json_atomic(state_path, state)

    def move_to_completed() -> None:
        """Move this job's state file out of active/ once it's reached a terminal
        status. The success path already did this; the three cancellation exit
        points below didn't, which left every cancelled integrity check sitting
        in active/ forever (status="cancelled" isn't a live status, so the
        stale-job reaper skips it too -- nothing else was ever going to move it)."""
        completed_path = JOBS_ROOT / "completed" / state_path.name
        completed_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.replace(completed_path)

    try:
        update(status="running", phase="loading_local_catalog", started_at_utc=utc_now(), pid=os.getpid())
        catalog_path = PROJECT_ROOT / "data" / "catalog" / CATALOG_FILES[args.catalog]
        local_columns = ["product_id", "sol", "camera", "img_url"]
        if args.catalog == "raw":
            local_columns.append("sample_type")
        if args.catalog == "pds" and args.camera == "chemcam":
            local_columns.append("processing_level")
        local = pd.read_parquet(catalog_path, columns=local_columns)
        local_sol = pd.to_numeric(local["sol"], errors="coerce")
        mask = (
            local["camera"].fillna("").astype(str).str.casefold().eq(args.camera.casefold())
            & local_sol.between(args.sol_start, args.sol_end, inclusive="both")
        )
        local = local.loc[mask]
        if args.catalog == "raw":
            # _raw_camera() (shared with core/make_msl_raw_catalog.py) never
            # classifies a thumbnail as belonging to any camera -- by
            # sampleType=="thumbnail" OR "THUMBNAIL"/"EDR_T" in the URL -- so
            # the remote scan structurally can't ever find one. The local
            # catalog still holds thumbnails predating that exclusion (some
            # with sample_type set, some only identifiable by the EDR_T
            # filename marker, mirrored here exactly). Comparing them against
            # a scan that will never produce a match would flag every one of
            # them as "local_only" -- noise, not a real gap.
            sample_type = local["sample_type"].astype("string").fillna("").str.casefold()
            url_upper = local["img_url"].astype("string").fillna("").str.upper()
            is_thumbnail = sample_type.eq("thumbnail") | url_upper.str.contains("THUMBNAIL") | url_upper.str.contains("EDR_T")
            local = local.loc[~is_thumbnail]
        if args.catalog == "pds" and args.camera == "chemcam":
            # Catalog_PDS's chemcam section also holds ~1.4k quicklook EDR
            # records pulled in from the RAW archive host at some point
            # (img_url under mars.nasa.gov/msl-raw-images, processing_level
            # left unset) alongside the real RDR_PRC products from the PDS
            # Geosciences node. discover_sol_urls/discover_rmi_products only
            # ever scan the Geosciences node, so those quicklook records can
            # never be matched -- same false-gap risk as the RAW thumbnails.
            local = local.loc[local["processing_level"].astype("string").eq("RDR_PRC")]
        local_ids = set(local["product_id"].dropna().astype(str))

        base_url = ""
        camera_cfg: dict[str, Any] = {}
        selection_rules: dict[str, Any] = {}
        request_timeout = 45
        client: PDSClient | None = None
        if args.catalog == "pds":
            cfg = json.loads((PROJECT_ROOT / "config" / "msl_catalog_config.json").read_text(encoding="utf-8"))
            selection_rules = json.loads((PROJECT_ROOT / "config" / "camera_rules.json").read_text(encoding="utf-8"))
            selection_rules = copy.deepcopy(selection_rules)
            camera_rule = selection_rules.get(args.camera, {})
            pds_rule = (camera_rule.get("rules", {}) or {}).get("pds", {}) if isinstance(camera_rule, dict) else {}
            if isinstance(pds_rule, dict):
                # Size thresholds govern legacy selection/LBL work, but current
                # Catalog_PDS membership retains valid small products as well.
                pds_rule.pop("min_img_size_bytes", None)
                pds_rule.pop("min_img_size_exempt_markers_any", None)
            base_url = str(cfg.get("base_url"))
            request_timeout = int(cfg.get("timeout", 30))
            # ChemCam PDS lives on a different PDS node entirely (see
            # discover_sol_urls/discover_rmi_products below) and has no entry
            # in msl_catalog_config.json's camera_config -- _camera_cfg would
            # KeyError for it.
            if args.camera != "chemcam":
                camera_cfg = _camera_cfg(cfg)[args.camera]
            client = PDSClient(timeout=request_timeout, retries=5)
        locations: list[Any] = []
        discovery_failures: list[dict[str, Any]] = []
        source_result: dict[str, Any] | None = None

        if args.retry_of:
            source_state = load_job(args.retry_of)
            if not source_state or not source_state.get("result_path"):
                raise RuntimeError(f"Retry source not found: {args.retry_of}")
            source_result = json.loads((PROJECT_ROOT / str(source_state["result_path"])).read_text(encoding="utf-8"))
            for item in source_result.get("failed_locations") or []:
                url = str(item.get("url") or "").strip()
                if not url:
                    continue
                locations.append(
                    SimpleNamespace(
                        sol=int(item.get("sol") or 0), sol_url=url,
                        collection="targeted-retry", data_root="", sol_dir_name=str(item.get("sol") or 0),
                    )
                )
            update(
                phase="scanning",
                local_products=len(local),
                targeted_retry=True,
                retry_of=args.retry_of,
            )
        elif args.catalog == "raw":
            update(phase="discovering_remote_sols", local_products=len(local))
            # A single manifest fetch gives every Sol's catalog_url directly --
            # deliberately not wrapped to tolerate partial failure the way the
            # PDS per-collection crawl below does (see discover_raw_locations).
            locations, _manifest_url = discover_raw_locations(args.sol_start, args.sol_end, request_timeout, 4)
            update(locations_discovered=len(locations), discovery_failures=0)
        elif args.camera == "chemcam":
            update(phase="discovering_remote_sols", local_products=len(local))
            # ChemCam PDS lives on a different PDS node with flat Sol
            # directories (no collections) -- discover_sol_urls lists every
            # Sol in one pass, unlike the per-collection crawl below.
            sol_urls = discover_sol_urls(client, CHEMCAM_RDR_DATA_URL)
            locations = [
                SimpleNamespace(
                    sol=sol, sol_url=url, collection="chemcam-rdr-flat",
                    data_root="", sol_dir_name=str(sol),
                )
                for sol, url in sol_urls.items()
                if args.sol_start <= sol <= args.sol_end
            ]
            update(locations_discovered=len(locations), discovery_failures=0)
        else:
            update(phase="discovering_remote_sols", local_products=len(local))
            collections = discover_collections_for_camera(client, base_url, str(camera_cfg["collection_token"]))
            update(collections_total=len(collections), collections_done=0)

            def discover_collection(collection: str) -> tuple[str, list[Any], str]:
                """List one collection's Sol locations; returns `(collection, locations, error_message)` for the caller to aggregate across the thread pool."""
                try:
                    collection_client = PDSClient(timeout=request_timeout, retries=3)
                    found = discover_sol_locations(collection_client, base_url, collection, camera_cfg.get("data_roots", []))
                    return collection, found, ""
                except Exception as exc:  # noqa: BLE001
                    return collection, [], f"{type(exc).__name__}: {exc}"

            with ThreadPoolExecutor(max_workers=min(6, max(1, len(collections)))) as executor:
                futures = [executor.submit(discover_collection, collection) for collection in collections]
                for index, future in enumerate(as_completed(futures), start=1):
                    collection, found, error = future.result()
                    locations.extend(found)
                    if error:
                        discovery_failures.append({"collection": collection, "error": error})
                    update(
                        collections_done=index,
                        locations_discovered=len(locations),
                        discovery_failures=len(discovery_failures),
                    )
                    if cancel_path.exists():
                        for pending in futures:
                            pending.cancel()
                        update(status="cancelled", phase="cancelled", cancelled_at_utc=utc_now())
                        move_to_completed()
                        return 2
        locations = [loc for loc in locations if args.sol_start <= int(loc.sol) <= args.sol_end]
        locations.sort(key=lambda loc: (int(loc.sol), loc.collection, loc.sol_url), reverse=True)

        remote_by_id: dict[str, dict[str, Any]] = {}
        remote_seen_ids: set[str] = set()
        completed_location_urls: set[str] = set()
        if args.resume_of:
            resume_path = JOBS_ROOT / "checkpoints" / f"{args.resume_of}.json"
            resume_data = json.loads(resume_path.read_text(encoding="utf-8"))
            completed_location_urls = {str(url) for url in resume_data.get("completed_location_urls") or []}
            for product in resume_data.get("remote_products") or []:
                if product.get("product_id"):
                    remote_by_id[str(product["product_id"])] = product
            update(
                resumed_from=args.resume_of,
                checkpoint_locations_loaded=len(completed_location_urls),
                checkpoint_products_loaded=len(remote_by_id),
            )
        if source_result is not None:
            unresolved_local_ids = {
                str(item.get("product_id")) for item in source_result.get("local_only_products") or []
                if item.get("product_id")
            }
            for row in local.itertuples(index=False):
                product_id = str(row.product_id)
                if product_id not in unresolved_local_ids:
                    remote_by_id[product_id] = {
                        "product_id": product_id, "sol": int(row.sol), "img_url": row.img_url,
                    }
            for product in source_result.get("missing_products") or []:
                if product.get("product_id"):
                    remote_by_id[str(product["product_id"])] = product
        failed: list[dict[str, Any]] = list(discovery_failures)
        all_locations_total = len(locations)
        locations = [location for location in locations if location.sol_url not in completed_location_urls]
        base_done = all_locations_total - len(locations)
        total = all_locations_total
        # Mirrors the discovery phase's own worker cap a few lines above --
        # this used to be min(1, ...), which always evaluates to 1 no matter
        # how many locations there are, making the scan phase fully
        # sequential despite the ThreadPoolExecutor below being set up for
        # concurrency (this is a read-only check, so more workers is safe).
        scan_workers = min(6, max(1, len(locations)))
        checkpoint_path = JOBS_ROOT / "checkpoints" / f"{args.job_id}.json"

        def save_checkpoint() -> None:
            """Persist scan progress (completed locations + remote products found so far) so a cancelled/failed run can be resumed via `--resume-of` instead of rescanning everything."""
            write_json_atomic(
                checkpoint_path,
                {
                    "schema_version": 1,
                    "job_id": args.job_id,
                    "camera": args.camera,
                    "sol_start": args.sol_start,
                    "sol_end": args.sol_end,
                    "completed_location_urls": sorted(completed_location_urls),
                    "remote_products": list(remote_by_id.values()),
                    "saved_at_utc": utc_now(),
                },
            )

        update(
            phase="scanning",
            locations_total=total,
            locations_done=base_done,
            failed_locations=0,
            scan_workers=scan_workers,
            checkpoint_interval=20,
        )

        # requests.Session is not guaranteed to be thread-safe. Each worker
        # therefore gets its own PDS client/session, reused for all locations
        # handled by that thread.
        worker_local = threading.local()

        def scan_one(location: Any) -> tuple[Any, list[dict[str, Any]], set[str], str]:
            """Scan one remote location for `args.camera`'s products (PDS or RAW, per `args.catalog`); returns `(location, products, seen_ids, error_message)` for the caller to aggregate."""
            try:
                if args.catalog == "raw":
                    products, seen_ids = scan_location_raw(location, args.camera, request_timeout, 4)
                else:
                    worker_client = getattr(worker_local, "client", None)
                    if worker_client is None:
                        worker_client = PDSClient(timeout=request_timeout, retries=5)
                        worker_local.client = worker_client
                    if args.camera == "chemcam":
                        # Read-only existence check: no LBL parsing here (unlike
                        # the real builder's enrich_from_labels), site/drive/pose
                        # aren't needed just to compare product IDs.
                        products = discover_rmi_products(worker_client, int(location.sol), location.sol_url)
                    else:
                        products = scan_location_pds(worker_client, location, base_url, args.camera, selection_rules)
                    seen_ids = set()
                return location, products, seen_ids, ""
            except Exception as exc:  # noqa: BLE001
                return location, [], set(), f"{type(exc).__name__}: {exc}"

        cancelled = False
        retry_queue: list[tuple[Any, str]] = []
        with ThreadPoolExecutor(max_workers=scan_workers) as executor:
            futures = [executor.submit(scan_one, location) for location in locations]
            for index, future in enumerate(as_completed(futures), start=1):
                location, products, seen_ids, error = future.result()
                if error:
                    retry_queue.append((location, error))
                for product in products:
                    # A product can be republished in more than one PDS
                    # collection. Keep one canonical record per product ID.
                    remote_by_id.setdefault(product["product_id"], product)
                remote_seen_ids.update(seen_ids)
                if not error:
                    completed_location_urls.add(str(location.sol_url))
                elapsed = max(time.monotonic() - started, 0.001)
                completed_now = base_done + index
                rate = index / elapsed
                remaining = (total - completed_now) / rate if rate else None
                update(
                    current_sol=int(location.sol),
                    locations_done=completed_now,
                    remote_products=len(remote_by_id),
                    missing_products=sum(1 for product_id in remote_by_id if product_id not in local_ids),
                    failed_locations=len(failed) + len(retry_queue),
                    elapsed_seconds=round(elapsed, 2),
                    rate_locations_per_second=round(rate, 4),
                    estimated_remaining_seconds=round(remaining, 2) if remaining is not None else None,
                )
                if index % 20 == 0:
                    save_checkpoint()
                if cancel_path.exists():
                    cancelled = True
                    for pending in futures:
                        pending.cancel()
                    break

        if cancelled:
            save_checkpoint()
            update(status="cancelled", phase="cancelled", cancelled_at_utc=utc_now())
            move_to_completed()
            return 2

        # Retry only the locations that survived all retries in the first
        # pass. A fresh Session avoids reusing a connection that may have
        # become unhealthy. This second pass remains sequential and does not
        # put additional concurrent load on the NASA server.
        if retry_queue:
            update(
                phase="retrying_failed_locations",
                retry_locations_total=len(retry_queue),
                retry_locations_done=0,
                failed_locations=len(failed) + len(retry_queue),
                estimated_remaining_seconds=None,
            )
            time.sleep(2.0)
            retry_client = PDSClient(timeout=request_timeout, retries=5) if args.catalog == "pds" else None
            for retry_index, (location, first_error) in enumerate(retry_queue, start=1):
                if cancel_path.exists():
                    update(status="cancelled", phase="cancelled", cancelled_at_utc=utc_now())
                    move_to_completed()
                    return 2
                try:
                    if args.catalog == "raw":
                        products, seen_ids = scan_location_raw(location, args.camera, request_timeout, 4)
                        remote_seen_ids.update(seen_ids)
                    elif args.camera == "chemcam":
                        products = discover_rmi_products(retry_client, int(location.sol), location.sol_url)
                    else:
                        products = scan_location_pds(retry_client, location, base_url, args.camera, selection_rules)
                    for product in products:
                        remote_by_id.setdefault(product["product_id"], product)
                    completed_location_urls.add(str(location.sol_url))
                except Exception as exc:  # noqa: BLE001
                    failed.append(
                        {
                            "sol": int(location.sol),
                            "url": location.sol_url,
                            "error": f"{type(exc).__name__}: {exc}",
                            "first_pass_error": first_error,
                        }
                    )
                elapsed = max(time.monotonic() - started, 0.001)
                update(
                    current_sol=int(location.sol),
                    retry_locations_done=retry_index,
                    remote_products=len(remote_by_id),
                    missing_products=sum(1 for product_id in remote_by_id if product_id not in local_ids),
                    failed_locations=len(failed) + len(retry_queue) - retry_index,
                    elapsed_seconds=round(elapsed, 2),
                )
                save_checkpoint()

        missing = [product for product_id, product in remote_by_id.items() if product_id not in local_ids]
        local_only = [
            {"product_id": row.product_id, "sol": int(row.sol), "img_url": row.img_url}
            for row in local.itertuples(index=False)
            if str(row.product_id) not in remote_by_id and str(row.product_id) not in remote_seen_ids
        ]
        result = {
            "schema_version": 1,
            "job_id": args.job_id,
            "operation": "integrity_check",
            "catalog": args.catalog,
            "camera": args.camera,
            "sol_start": args.sol_start,
            "sol_end": args.sol_end,
            "complete": not failed,
            "local_products": len(local),
            "remote_products": len(remote_by_id),
            "missing_products": missing,
            "local_only_products": local_only,
            "failed_locations": failed,
            "generated_at_utc": utc_now(),
        }
        result_path = JOBS_ROOT / "results" / f"{args.job_id}.json"
        write_json_atomic(result_path, result)
        elapsed = time.monotonic() - started
        update(
            status="completed" if not failed else "partial",
            phase="finished",
            completed_at_utc=utc_now(),
            elapsed_seconds=round(elapsed, 2),
            remote_products=len(remote_by_id),
            missing_products=len(missing),
            local_only_products=len(local_only),
            failed_locations=len(failed),
            result_path=str(result_path.relative_to(PROJECT_ROOT)),
        )
        checkpoint_path.unlink(missing_ok=True)
        completed_path = JOBS_ROOT / "completed" / state_path.name
        completed_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.replace(completed_path)
        return 0 if not failed else 3
    except Exception as exc:  # noqa: BLE001
        update(status="failed", phase="failed", error=f"{type(exc).__name__}: {exc}", failed_at_utc=utc_now())
        return 1
    finally:
        lock_path.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    """Parse this worker's CLI arguments."""
    parser = argparse.ArgumentParser(description="Read-only MSL catalog background worker")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--catalog", choices=["pds", "raw"], required=True)
    # chemcam is valid for --catalog raw (the unified RAW builder already
    # handles it like any other camera). For --catalog pds it additionally
    # requires the chemcam-specific discovery/scan branch below.
    parser.add_argument("--camera", choices=["mastcam", "mahli", "navcam", "hazcam", "mardi", "chemcam"], required=True)
    parser.add_argument("--sol-start", type=int, required=True)
    parser.add_argument("--sol-end", type=int, required=True)
    parser.add_argument("--retry-of")
    parser.add_argument("--resume-of")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
