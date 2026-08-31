// Real client for the local MSL Downloader web API (`webapi/`), replacing the
// public-NASA-API + fabricated-data approach in `nasaApi.js`. Search results
// here are the actual local PDS/RAW catalog, filtered by the same engine
// (`camera_rules.json` included) the Streamlit app's sidebar uses.

export const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

// Camera group -> display label. Keys match this app's own camera keys
// (also what the backend's `camera` column and camera_rules.json use).
export const CAMERA_GROUPS = [
  { id: 'mastcam', label: 'Mastcam' },
  { id: 'mahli', label: 'MAHLI' },
  { id: 'navcam', label: 'Navcam' },
  { id: 'hazcam', label: 'Hazcam' },
  { id: 'chemcam', label: 'ChemCam' },
  { id: 'mardi', label: 'MARDI' },
];

const CAMERA_LABEL_BY_ID = Object.fromEntries(CAMERA_GROUPS.map((c) => [c.id, c.label]));

export function buildOutputPath(folder, organization, camera, sol) {
  const parts = [folder];
  if (organization === 'camera' || organization === 'both') parts.push(camera);
  if (organization === 'sol' || organization === 'both') parts.push(`sol_${sol}`);
  return parts.join('/') + '/';
}

// The filter form speaks in 'PDS' | 'RAW' | 'both'; records store the source
// catalog they actually came from ('pds' | 'raw' from the backend).
function sourceCatalogLabel(source) {
  return String(source || '').toUpperCase() || 'PDS';
}

function normalizeProduct(rec, outputFolder, organization) {
  const cameraLabel = CAMERA_LABEL_BY_ID[rec.camera] || rec.camera;
  const sizeKb = rec.img_size_bytes ? Math.round(rec.img_size_bytes / 1024) : 0;
  return {
    product_id: rec.product_id,
    sol: rec.sol,
    camera: cameraLabel,
    instrument: rec.instrument_id || cameraLabel,
    earth_date: (rec.image_time || rec.start_time || '').slice(0, 10),
    // NOTE: not a real browser-viewable image until it's actually been
    // downloaded+processed -- `img_url` points at the NASA PDS/RAW server's
    // raw product, not a local JPEG. `runDownload` overwrites this with a
    // real local path once the download job finishes.
    img_src: rec.img_url,
    source_catalog: sourceCatalogLabel(rec.source),
    rover: 'Curiosity',
    site: rec.site ?? '—',
    drive: rec.drive ?? '—',
    pose: rec.pose ?? '—',
    file_size_kb: sizeKb,
    output_path: buildOutputPath(outputFolder, organization, cameraLabel, rec.sol),
    metadata_path: `${outputFolder}/metadata/${rec.product_id}.json`,
    status: 'not_downloaded',
    warnings: '',
    // Raw backend fields, needed by /api/download/start (img_url is also the
    // display img_src above, kept separate here so the download step never
    // depends on a UI-facing field the rest of the app might reshape).
    img_url: rec.img_url,
    lbl_url: rec.lbl_url,
    source: rec.source,
  };
}

// Search the local catalog across a Sol range and selected camera groups.
// Returns { photos: normalizedProducts[], totalFound, error }
export async function searchPhotos({ solStart, solEnd, cameras, catalog, minSize, outputFolder, organization }) {
  try {
    const res = await fetch(`${API_BASE}/api/catalog/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sol_start: solStart,
        sol_end: solEnd,
        cameras,
        catalog,
        min_size_kb: minSize || 0,
        max_images: 0, // cap is applied client-side (maxImages) after size filtering, as before
      }),
    });
    if (!res.ok) {
      return { photos: [], totalFound: 0, error: res.status === 429 ? '429' : 'network' };
    }
    const data = await res.json();
    const photos = (data.products || []).map((rec) => normalizeProduct(rec, outputFolder, organization));
    return { photos, totalFound: data.total_found ?? photos.length, error: null };
  } catch {
    return { photos: [], totalFound: 0, error: 'network' };
  }
}

// Launch a real download+process job for `records` (as returned by
// searchPhotos -- must still carry img_url/lbl_url/source). `organization`
// is the filter form's 'camera' | 'sol' | 'both' value. Returns
// { jobId, outputFolder } or throws on a network/HTTP failure.
export async function startDownloadJob(records, outputFolder, organization, lang) {
  const res = await fetch(`${API_BASE}/api/download/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      records,
      output_folder: outputFolder || null,
      organize_by_camera: organization === 'camera' || organization === 'both',
      organize_by_sol: organization === 'sol' || organization === 'both',
      lang: lang || 'it',
    }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Download start failed (${res.status})`);
  }
  const data = await res.json();
  return { jobId: data.job_id, outputFolder: data.output_folder };
}

// One poll of a running/finished download job's status.
export async function fetchDownloadJob(jobId) {
  const res = await fetch(`${API_BASE}/api/download/${jobId}`);
  if (!res.ok) throw new Error(`Job status fetch failed (${res.status})`);
  return res.json();
}

export async function cancelDownloadJob(jobId) {
  await fetch(`${API_BASE}/api/download/${jobId}/cancel`, { method: 'POST' }).catch(() => {});
}

// Real, browser-viewable URL for a product a finished job actually wrote to disk
// (see webapi/main.py::download_file). `rootHint` (the output folder that job
// actually resolved to) lets the backend still find the file by a real
// filesystem search if its in-memory job registry was lost to a server
// restart since -- without it, any image saved before the last webapi
// restart would go permanently unpreviewable even though the file is still
// on disk. Always pass it when known (e.g. `started.outputFolder` from
// `startDownloadJob`, or a saved record's own `output_root`).
export function fileUrl(jobId, productId, rootHint) {
  const base = `${API_BASE}/api/files/${jobId}/${encodeURIComponent(productId)}`;
  return rootHint ? `${base}?root=${encodeURIComponent(rootHint)}` : base;
}

// Real post-processing metadata (the actual .meta.json the job wrote), same
// root-hint fallback as fileUrl. Returns null if unavailable (no job_id yet,
// job not found, or the file genuinely isn't there).
export async function fetchRealMeta(jobId, productId, rootHint) {
  if (!jobId) return null;
  const base = `${API_BASE}/api/meta/${jobId}/${encodeURIComponent(productId)}`;
  const url = rootHint ? `${base}?root=${encodeURIComponent(rootHint)}` : base;
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}
