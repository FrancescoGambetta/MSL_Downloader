#!/usr/bin/env python3
"""FastAPI entrypoint for the MSL Downloader / Catalog Manager web API.

Run with `uvicorn webapi.main:app --reload --port 8000` from the project root (see
`Run_WebApi.bat`). This is the bridge step of the React migration: the frontend
(`frontend/`, currently talking to NASA's public API and localStorage) will be
switched over to call these endpoints instead, one feature at a time, while the
existing Streamlit apps keep working unchanged in the meantime.

sys.path setup below mirrors `app/app.py`'s own trick: the project root (for
`core.*`/`catalog_manager.*` package imports), `app/` itself (for its internal
same-directory imports like `from runtime import ...`), and `core/` itself (for
`app/actions.py`'s own `from portable_engine_adapter import ...`, since `app.py`
adds `core/` directly to `sys.path` too) all need to be importable -- `app/`'s
modules were written to run as `streamlit run app/app.py` sets them up, not as an
`app.xxx` package.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for path in (PROJECT_ROOT, APP_DIR, CORE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from webapi import catalog_manager_routes, catalog_service, download_service, i18n_state, session_routes  # noqa: E402 -- must follow the sys.path setup above
import runtime as app_runtime  # noqa: E402
import actions as app_actions  # noqa: E402

app = FastAPI(title="MSL Downloader API", version="0.1.0")

# Wire actions.py's translator so log/organize messages come back as real text
# instead of raw i18n keys -- same i18n_app.json the Streamlit app reads. Reads
# the current *thread's* language (webapi/i18n_state.py), which download_service
# sets to whatever the frontend passed when the job's own thread started, so
# messages from a job launched with the UI in French come back in French, etc.
# (falls back to Italian for request paths that never set one, e.g. catalog search).
app_actions.set_translator(i18n_state.t)

# The Vite dev server runs on a different origin (localhost:5173) than this API
# (localhost:8000) -- CORS must be explicit for the browser to allow the fetch.
# Wide open for local development only; tighten before any real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(catalog_manager_routes.router)
app.include_router(session_routes.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness check: confirms the API process is up and can see the project root."""
    return {
        "status": "ok",
        "project_root": str(PROJECT_ROOT),
    }


class CatalogSearchRequest(BaseModel):
    """Search request body -- one field per `DownloadPreparation.jsx` filter control."""

    sol_start: int = Field(..., ge=0)
    sol_end: int = Field(..., ge=0)
    cameras: list[str] = Field(default_factory=list)
    catalog: str = Field(default="both", description='"PDS" | "RAW" | "both"')
    min_size_kb: int = Field(default=0, ge=0)
    max_images: int = Field(default=0, ge=0, description="0 means no cap")


@app.post("/api/catalog/search")
def catalog_search(body: CatalogSearchRequest) -> dict:
    """Filter the real local PDS+RAW catalog and return matching products -- the live counterpart of the mockup's `nasaApi.searchPhotos`."""
    catalog_key = body.catalog.strip().lower()
    source_pds = catalog_key in {"pds", "both"}
    source_raw = catalog_key in {"raw", "both"}
    return catalog_service.search(
        sol_start=body.sol_start,
        sol_end=body.sol_end,
        cameras=body.cameras,
        source_pds=source_pds,
        source_raw=source_raw,
        min_img_size_kb=body.min_size_kb or None,
        max_images=body.max_images or None,
    )


class DownloadStartRequest(BaseModel):
    """Download-job request body: the exact records `catalog_search` returned (must still carry `img_url`/`lbl_url`/`source`), plus where to save them."""

    records: list[dict] = Field(..., min_length=1)
    output_folder: Optional[str] = None
    organize_by_camera: bool = False
    organize_by_sol: bool = False
    lang: str = "it"


@app.post("/api/download/start")
def download_start(body: DownloadStartRequest) -> dict:
    """Launch a real download+process job (full parity with the Streamlit builder's RUN button: PDS engine decode, RAW Bayer/EXIF/meta, alpha-pairs, MARDI correction, ChemCam, folder organization) and return its job id."""
    output_folder = body.output_folder or app_runtime._default_download_path()
    ok, resolved = app_runtime._ensure_writable_download_path(output_folder)
    if not ok:
        raise HTTPException(status_code=400, detail=f"Output path is not writable: {output_folder}")
    organize = {"by_camera": body.organize_by_camera, "by_sol": body.organize_by_sol}
    job_id = download_service.start_job(body.records, resolved, organize, lang=body.lang)
    return {"job_id": job_id, "output_folder": resolved}


@app.get("/api/download/{job_id}")
def download_status(job_id: str) -> dict:
    """Poll a download job's status/progress/log -- call every ~1-2s while `status == "running"`."""
    job = download_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id")
    return job


@app.post("/api/download/{job_id}/cancel")
def download_cancel(job_id: str) -> dict:
    """Request cooperative cancellation of a running job (takes effect between records, not mid-file)."""
    if not download_service.request_cancel(job_id):
        raise HTTPException(status_code=404, detail="Unknown job id")
    return {"status": "cancel_requested"}


@app.get("/api/files/{job_id}/{product_id}")
def download_file(job_id: str, product_id: str, root: Optional[str] = None) -> FileResponse:
    """Serve one product's real, locally processed JPG -- only ever a file that job actually wrote, or (if the in-memory job registry was lost to a server restart) a file found by exact name under `root` or the default download folder. Never an arbitrary filesystem path outside those roots."""
    path = download_service.get_servable_file(job_id, product_id, root_hint=root)
    if path is None:
        raise HTTPException(status_code=404, detail="No file for this job/product")
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/meta/{job_id}/{product_id}")
def download_meta(job_id: str, product_id: str, root: Optional[str] = None) -> dict:
    """Real post-processing metadata for one product (its actual `.meta.json`), curated to the same fields the Streamlit app's metadata panel shows -- the frontend's own panel used to show catalog-search-time values instead."""
    meta = download_service.get_meta_json(job_id, product_id, root_hint=root)
    if meta is None:
        raise HTTPException(status_code=404, detail="No metadata for this job/product")
    return meta
