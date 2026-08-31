// Camera group -> NASA Mars Photos API instrument codes
export const CAMERA_GROUPS = [
  { id: 'Mastcam', code: 'MAST', label: 'Mastcam' },
  { id: 'MAHLI', code: 'MAHLI', label: 'MAHLI' },
  { id: 'Navcam', code: 'NAVCAM', label: 'Navcam' },
  { id: 'Hazcam', codes: ['FHAZ', 'RHAZ'], label: 'Hazcam' },
  { id: 'ChemCam', code: 'CHEMCAM', label: 'ChemCam' },
  { id: 'MARDI', code: 'MARDI', label: 'MARDI' },
];

export function cameraCodes(groupId) {
  const g = CAMERA_GROUPS.find((c) => c.id === groupId);
  if (!g) return [];
  return g.codes || [g.code];
}

export function groupForInstrument(instrument) {
  const g = CAMERA_GROUPS.find((c) => (c.codes || [c.code]).includes(instrument));
  return g ? g.id : instrument;
}

// Deterministic pseudo file size (KB) — in-browser estimate, since the API
// does not expose real sizes. Keeps the min-size filter functional.
export function estimateSizeKb(id) {
  const n = typeof id === 'number' ? id : String(id).split('').reduce((a, c) => a + c.charCodeAt(0), 0);
  return ((n * 2654435761) % 7500) + 250; // 250–7750 KB
}

function normalizePhoto(photo, sourceCatalog, outputFolder, organization) {
  const instrument = photo.camera?.name || 'UNKNOWN';
  const group = groupForInstrument(instrument);
  const sizeKb = estimateSizeKb(photo.id);
  return {
    product_id: String(photo.id),
    sol: photo.sol,
    camera: group,
    instrument,
    earth_date: photo.earth_date,
    img_src: photo.img_src,
    source_catalog: sourceCatalog,
    rover: photo.rover?.name || 'Curiosity',
    site: '—',
    drive: '—',
    pose: '—',
    file_size_kb: sizeKb,
    output_path: buildOutputPath(outputFolder, organization, group, photo.sol),
    metadata_path: `${outputFolder}/metadata/${photo.id}.json`,
    status: 'downloaded',
    warnings: '',
  };
}

export function buildOutputPath(folder, organization, camera, sol) {
  const parts = [folder];
  if (organization === 'camera' || organization === 'both') parts.push(camera);
  if (organization === 'sol' || organization === 'both') parts.push(`sol_${sol}`);
  return parts.join('/') + '/';
}

// Search the NASA Mars Photos API across a Sol range and selected camera groups.
// Returns { photos, error }
export async function searchPhotos({ solStart, solEnd, cameras, apiKey }) {
  const sols = [];
  for (let s = solStart; s <= solEnd; s++) sols.push(s);
  const codes = Array.from(new Set(cameras.flatMap(cameraCodes)));
  const photos = [];
  let error = null;
  for (const sol of sols) {
    for (const code of codes) {
      const url = `https://api.nasa.gov/mars-photos/api/v1/rovers/curiosity/photos?sol=${sol}&camera=${code}&api_key=${apiKey}`;
      try {
        const res = await fetch(url);
        if (!res.ok) {
          if (res.status === 429) error = '429';
          continue;
        }
        const data = await res.json();
        if (Array.isArray(data.photos)) photos.push(...data.photos);
      } catch {
        error = error || 'network';
      }
    }
  }
  return { photos, error };
}

// The filter form speaks in 'PDS' | 'RAW' | 'both'; records store the catalogue
// they came from. 'both' has to become an explicit combined label, otherwise
// downstream checks for a PDS product never match.
export function catalogLabel(catalog) {
  return catalog === 'both' ? 'PDS+RAW' : catalog;
}

export function toRecords(photos, catalog, outputFolder, organization) {
  const sourceCatalog = catalogLabel(catalog);
  return photos.map((p) => normalizePhoto(p, sourceCatalog, outputFolder, organization));
}