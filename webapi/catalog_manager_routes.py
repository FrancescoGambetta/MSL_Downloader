"""FastAPI routes for Catalog Manager, mounted under `/api/cm/` by `webapi/main.py`.

Thin HTTP layer over `webapi/catalog_manager_service.py` -- every function here
just validates the request shape and calls straight into the service module,
mirroring `webapi/main.py`'s own endpoints for the downloader side.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from webapi import catalog_manager_service as cms

router = APIRouter(prefix="/api/cm", tags=["catalog-manager"])

Catalog = Literal["pds", "raw"]


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


@router.get("/status")
def status(catalog: Catalog) -> dict[str, Any]:
    """Local-only inspection (no network) for one catalog."""
    return cms.local_status(catalog)


@router.get("/status-full")
def status_full(catalog: Catalog) -> dict[str, Any]:
    """Local status merged with the last saved remote-comparison report, if any (no live network call)."""
    return cms.status_with_cached_remote(catalog)


class CheckUpdatesRequest(BaseModel):
    catalog: Catalog


@router.post("/check-updates")
def check_updates(body: CheckUpdatesRequest) -> dict[str, Any]:
    """Cross-check the local catalog against NASA. Blocking -- can take up to ~1-2 minutes for PDS."""
    return cms.check_updates(body.catalog)


@router.get("/json-status")
def json_status(catalog: Catalog) -> dict[str, Any]:
    return cms.json_status(catalog)


# ---------------------------------------------------------------------------
# Jobs (generic: integrity checks, updates, repairs, customization, json rebuild)
# ---------------------------------------------------------------------------


# NOTE: static "/jobs/active", "/jobs/history", "/jobs/latest" must be
# registered BEFORE the "/jobs/{job_id}" parameterized routes below -- FastAPI
# matches routes in registration order, so a parameterized route declared
# first would otherwise swallow "active"/"history"/"latest" as a job_id.


@router.get("/jobs/active")
def get_active_job(catalog: Catalog) -> dict[str, Any] | None:
    return cms.active_job(catalog)


@router.get("/jobs/latest")
def get_latest_job(catalog: Catalog, operation: str = "integrity_check") -> dict[str, Any] | None:
    return cms.latest_job(catalog, operation=operation)


@router.get("/jobs/history")
def get_recent_jobs(catalog: Catalog, limit: int = 8) -> list[dict[str, Any]]:
    return cms.recent_jobs(catalog, limit=limit)


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = cms.load_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id")
    return job


@router.get("/jobs/{job_id}/lineage")
def get_job_lineage(job_id: str) -> list[dict[str, Any]]:
    job = cms.load_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id")
    return cms.job_lineage(job)


@router.get("/jobs/{job_id}/log")
def get_job_log(job_id: str) -> dict[str, str]:
    return {"log": cms.get_job_log(job_id)}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, str]:
    try:
        cms.request_cancel(job_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Unknown job id")
    return {"status": "cancel_requested"}


# ---------------------------------------------------------------------------
# Integrity checks
# ---------------------------------------------------------------------------


@router.get("/integrity/estimate")
def integrity_estimate(catalog: Catalog, camera: str, sol_start: int, sol_end: int) -> dict[str, int]:
    low, high = cms.estimate_integrity_seconds(catalog, camera, sol_start, sol_end)
    return {"low_seconds": low, "high_seconds": high}


@router.get("/integrity/last-sol")
def integrity_last_sol(catalog: Catalog, camera: str) -> dict[str, Optional[int]]:
    return {"last_checked_sol": cms.last_integrity_sol(catalog, camera)}


@router.get("/integrity/resumable")
def integrity_resumable(job_id: str) -> dict[str, bool]:
    return {"resumable": cms.resumable_job(job_id)}


class IntegrityStartRequest(BaseModel):
    catalog: Catalog
    camera: str
    sol_start: int = Field(..., ge=0)
    sol_end: int = Field(..., ge=0)


@router.post("/integrity/start")
def integrity_start(body: IntegrityStartRequest) -> dict[str, Any]:
    try:
        return cms.start_integrity_job(body.catalog, body.camera, body.sol_start, body.sol_end)
    except (RuntimeError, FileNotFoundError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


class IntegrityJobActionRequest(BaseModel):
    catalog: Catalog


@router.post("/integrity/{job_id}/retry-failed")
def integrity_retry_failed(job_id: str, body: IntegrityJobActionRequest) -> dict[str, Any]:
    try:
        return cms.start_failed_retry(body.catalog, job_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/integrity/{job_id}/resume")
def integrity_resume(job_id: str, body: IntegrityJobActionRequest) -> dict[str, Any]:
    try:
        return cms.start_resume_job(body.catalog, job_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/integrity/{job_id}/repair")
def integrity_repair(job_id: str, body: IntegrityJobActionRequest) -> dict[str, Any]:
    try:
        return cms.start_repair_job(body.catalog, job_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


# ---------------------------------------------------------------------------
# Catalog update
# ---------------------------------------------------------------------------


class UpdateStartRequest(BaseModel):
    catalog: Catalog
    sol_start: int = Field(..., ge=0)
    sol_end: int = Field(..., ge=0)
    cameras: list[str] = Field(default_factory=list)


@router.post("/update/start")
def update_start(body: UpdateStartRequest) -> dict[str, Any]:
    try:
        return cms.start_update_job(body.catalog, body.sol_start, body.sol_end, body.cameras)
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


# ---------------------------------------------------------------------------
# JSON rebuild / bootstrap
# ---------------------------------------------------------------------------


class CatalogOnlyRequest(BaseModel):
    catalog: Catalog


@router.post("/json-rebuild/start")
def json_rebuild_start(body: CatalogOnlyRequest) -> dict[str, Any]:
    try:
        return cms.start_json_rebuild_job(body.catalog)
    except (RuntimeError, FileNotFoundError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/bootstrap/state")
def bootstrap_state() -> dict[str, Any]:
    return cms.bootstrap_state()


class BootstrapChoiceRequest(BaseModel):
    choice: Literal["generate", "download_only"]


@router.post("/bootstrap/choice")
def bootstrap_choice(body: BootstrapChoiceRequest) -> dict[str, Any]:
    return cms.save_bootstrap_choice(body.choice)


@router.post("/bootstrap/start-json")
def bootstrap_start_json() -> dict[str, Any]:
    try:
        return cms.start_bootstrap_json_job()
    except (RuntimeError, FileNotFoundError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


# ---------------------------------------------------------------------------
# Distribution install (official release download)
# ---------------------------------------------------------------------------


@router.get("/distribution/status")
def distribution_status(catalog: Catalog) -> dict[str, Any]:
    return cms.distribution_status(catalog)


@router.post("/distribution/install")
def distribution_install(body: CatalogOnlyRequest) -> dict[str, str]:
    job_id = cms.start_distribution_install(body.catalog)
    return {"job_id": job_id}


@router.get("/distribution/install/{job_id}")
def distribution_install_status(job_id: str) -> dict[str, Any]:
    job = cms.get_install_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown install job id")
    return job


# ---------------------------------------------------------------------------
# Composition (read-only product-segment inventory)
# ---------------------------------------------------------------------------


@router.get("/composition")
def composition(catalog: Catalog) -> dict[str, Any]:
    return cms.composition(catalog)


@router.get("/composition/explain")
def composition_explain(dimension: str, code: str, lang: str = "en", camera: str = "") -> dict[str, str]:
    """Human-readable {role, explanation} for one composition() segment code, e.g. dimension="suffix", code="DRCL". `camera` is optional -- only sharpens processing_marker's wording for Navcam."""
    return cms.explain_segment(dimension, code, lang, camera)


# ---------------------------------------------------------------------------
# Customization (PDS-only, matches the Streamlit app)
# ---------------------------------------------------------------------------


@router.get("/customization/options")
def customization_options() -> dict[str, Any]:
    return cms.customization_options()


@router.get("/customization/current")
def customization_current() -> dict[str, Any]:
    return cms.customization_current()


class CustomizationStartRequest(BaseModel):
    changes: dict[str, dict[str, list[str]]]
    sol_start: int = Field(..., ge=0)
    sol_end: int = Field(..., ge=0)


@router.post("/customization/start")
def customization_start(body: CustomizationStartRequest) -> dict[str, Any]:
    try:
        return cms.start_customization_job(body.changes, body.sol_start, body.sol_end)
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/customization/{job_id}/resumable")
def customization_resumable(job_id: str) -> dict[str, bool]:
    return {"resumable": cms.customization_resumable(job_id)}


@router.post("/customization/{job_id}/resume")
def customization_resume(job_id: str) -> dict[str, Any]:
    try:
        return cms.start_customization_resume_job(job_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
