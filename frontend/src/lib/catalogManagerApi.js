// Real client for the local Catalog Manager web API (`webapi/catalog_manager_routes.py`),
// replacing `catalogData.js`'s placeholder figures. Mirrors `mslApi.js`'s approach for
// the downloader side: thin fetch wrappers, no client-side business logic duplicated
// from the backend.

export const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

// Camera keys as the backend/catalogs use them (lowercase) -> this app's display labels.
export const CAMERA_LABELS = {
  mastcam: 'Mastcam',
  navcam: 'Navcam',
  hazcam: 'Hazcam',
  mahli: 'MAHLI',
  chemcam: 'ChemCam',
  mardi: 'MARDI',
};
export const CAMERA_KEYS = Object.keys(CAMERA_LABELS);

async function getJSON(path) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ? JSON.stringify(body.detail) : `Request failed (${res.status})`);
  }
  return res.json();
}

async function postJSON(path, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) {
    const payload = await res.json().catch(() => ({}));
    throw new Error(payload.detail ? String(payload.detail) : `Request failed (${res.status})`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Status
// ---------------------------------------------------------------------------

export const getStatus = (catalog) => getJSON(`/api/cm/status?catalog=${catalog}`);

// getStatusFull() backs the Overview tab, which the parent page fully
// unmounts/remounts on every tab switch (see CatalogManager.jsx's
// TAB_CONTENT swap) -- without this, that means a blank spinner + a fresh
// request every single time, even seconds after the last visit. The last
// good response per catalog is kept here so a remounting Overview can paint
// instantly from getCachedStatusFull() while a fresh getStatusFull() call
// quietly keeps it current in the background (see CatalogOverview.jsx).
const _statusFullCache = new Map();

export function getStatusFull(catalog) {
  return getJSON(`/api/cm/status-full?catalog=${catalog}`).then((data) => {
    _statusFullCache.set(catalog, data);
    return data;
  });
}

export const getCachedStatusFull = (catalog) => _statusFullCache.get(catalog) ?? null;

export const checkUpdates = (catalog) => postJSON('/api/cm/check-updates', { catalog });
export const getJsonStatus = (catalog) => getJSON(`/api/cm/json-status?catalog=${catalog}`);

// ---------------------------------------------------------------------------
// Jobs (generic)
// ---------------------------------------------------------------------------

export const getJob = (jobId) => getJSON(`/api/cm/jobs/${encodeURIComponent(jobId)}`);
export const getJobLineage = (jobId) => getJSON(`/api/cm/jobs/${encodeURIComponent(jobId)}/lineage`);
export const getActiveJob = (catalog) => getJSON(`/api/cm/jobs/active?catalog=${catalog}`);
export const getLatestJob = (catalog, operation = 'integrity_check') =>
  getJSON(`/api/cm/jobs/latest?catalog=${catalog}&operation=${operation}`);
export const getJobHistory = (catalog, limit = 8) => getJSON(`/api/cm/jobs/history?catalog=${catalog}&limit=${limit}`);
export const cancelJob = (jobId) => postJSON(`/api/cm/jobs/${encodeURIComponent(jobId)}/cancel`);
export const getJobLog = (jobId) => getJSON(`/api/cm/jobs/${encodeURIComponent(jobId)}/log`);

// ---------------------------------------------------------------------------
// Integrity checks
// ---------------------------------------------------------------------------

export const getIntegrityEstimate = (catalog, camera, solStart, solEnd) =>
  getJSON(`/api/cm/integrity/estimate?catalog=${catalog}&camera=${camera}&sol_start=${solStart}&sol_end=${solEnd}`);
export const getIntegrityLastSol = (catalog, camera) =>
  getJSON(`/api/cm/integrity/last-sol?catalog=${catalog}&camera=${camera}`);
export const getIntegrityResumable = (jobId) => getJSON(`/api/cm/integrity/resumable?job_id=${encodeURIComponent(jobId)}`);
export const startIntegrityCheck = (catalog, camera, solStart, solEnd) =>
  postJSON('/api/cm/integrity/start', { catalog, camera, sol_start: solStart, sol_end: solEnd });
export const retryFailedIntegrity = (jobId, catalog) => postJSON(`/api/cm/integrity/${encodeURIComponent(jobId)}/retry-failed`, { catalog });
export const resumeIntegrity = (jobId, catalog) => postJSON(`/api/cm/integrity/${encodeURIComponent(jobId)}/resume`, { catalog });
export const repairIntegrity = (jobId, catalog) => postJSON(`/api/cm/integrity/${encodeURIComponent(jobId)}/repair`, { catalog });

// ---------------------------------------------------------------------------
// Catalog update
// ---------------------------------------------------------------------------

export const startCatalogUpdate = (catalog, solStart, solEnd, cameras) =>
  postJSON('/api/cm/update/start', { catalog, sol_start: solStart, sol_end: solEnd, cameras });

// ---------------------------------------------------------------------------
// JSON rebuild / bootstrap
// ---------------------------------------------------------------------------

export const startJsonRebuild = (catalog) => postJSON('/api/cm/json-rebuild/start', { catalog });
export const getBootstrapState = () => getJSON('/api/cm/bootstrap/state');
export const saveBootstrapChoice = (choice) => postJSON('/api/cm/bootstrap/choice', { choice });
export const startBootstrapJson = () => postJSON('/api/cm/bootstrap/start-json');

// ---------------------------------------------------------------------------
// Distribution install (first-run official release download)
// ---------------------------------------------------------------------------

export const getDistributionStatus = (catalog) => getJSON(`/api/cm/distribution/status?catalog=${catalog}`);
export const startDistributionInstall = (catalog) => postJSON('/api/cm/distribution/install', { catalog });
export const getDistributionInstallJob = (jobId) => getJSON(`/api/cm/distribution/install/${encodeURIComponent(jobId)}`);

// ---------------------------------------------------------------------------
// Composition (read-only)
// ---------------------------------------------------------------------------

export const getComposition = (catalog) => getJSON(`/api/cm/composition?catalog=${catalog}`);

// Explanation text is static per (dimension, code, lang) -- fixed vocabulary
// on the backend (segment_explain.py), never changes at runtime -- so once
// fetched it's cached forever, letting a tooltip re-shown on repeated hover
// paint instantly instead of re-fetching every time.
const _explainCache = new Map();

export function explainSegment(dimension, code, lang, camera = '') {
  const key = `${dimension}:${code}:${lang}:${camera}`;
  if (_explainCache.has(key)) return Promise.resolve(_explainCache.get(key));
  const cameraParam = camera ? `&camera=${encodeURIComponent(camera)}` : '';
  return getJSON(
    `/api/cm/composition/explain?dimension=${encodeURIComponent(dimension)}&code=${encodeURIComponent(code)}&lang=${encodeURIComponent(lang)}${cameraParam}`
  ).then(
    (data) => {
      _explainCache.set(key, data);
      return data;
    }
  );
}

// ---------------------------------------------------------------------------
// Customization (PDS-only)
// ---------------------------------------------------------------------------

export const getCustomizationOptions = () => getJSON('/api/cm/customization/options');
export const getCustomizationCurrent = () => getJSON('/api/cm/customization/current');
export const startCustomization = (changes, solStart, solEnd) =>
  postJSON('/api/cm/customization/start', { changes, sol_start: solStart, sol_end: solEnd });
export const getCustomizationResumable = (jobId) => getJSON(`/api/cm/customization/${encodeURIComponent(jobId)}/resumable`);
export const resumeCustomization = (jobId) => postJSON(`/api/cm/customization/${encodeURIComponent(jobId)}/resume`);
