// Placeholder catalog figures.
//
// Nothing here talks to Google Drive or the NASA servers yet — the screens are
// built against this shape so that swapping in the real reader later is a
// change of source, not a change of layout. Keep the field names as they are
// when wiring the backend.

export const CATALOG_KINDS = [
  { id: 'pds', label: 'PDS' },
  { id: 'raw', label: 'RAW Archive' },
];

export const CAMERAS = ['Mastcam', 'Navcam', 'Hazcam', 'MAHLI', 'ChemCam', 'MARDI'];

const CATALOGS = {
  pds: {
    localSol: 4521,
    serverSol: 4533,
    totalProducts: 412880,
    sizeMB: 318,
    distribution: [
      { camera: 'Mastcam', count: 128400 },
      { camera: 'Navcam', count: 98200 },
      { camera: 'Hazcam', count: 76300 },
      { camera: 'MAHLI', count: 54100 },
      { camera: 'ChemCam', count: 41880 },
      { camera: 'MARDI', count: 14000 },
    ],
  },
  raw: {
    localSol: 4519,
    serverSol: 4533,
    totalProducts: 286540,
    sizeMB: 194,
    distribution: [
      { camera: 'Mastcam', count: 91200 },
      { camera: 'Navcam', count: 74600 },
      { camera: 'Hazcam', count: 58900 },
      { camera: 'MAHLI', count: 33800 },
      { camera: 'ChemCam', count: 21040 },
      { camera: 'MARDI', count: 7000 },
    ],
  },
};

export function getCatalog(kind) {
  const c = CATALOGS[kind] || CATALOGS.pds;
  return { ...c, newSols: Math.max(0, c.serverSol - c.localSol) };
}

// NASA product codes carry no meaning to most people, so every code is paired
// with a readable name. `included` marks what the installed catalog already
// holds — the customization screen defaults to exactly this set.
export const PRODUCT_FAMILIES = {
  Mastcam: [
    { code: 'EDR', name: 'Immagini originali', included: true },
    { code: 'RDR', name: 'Immagini elaborate', included: true },
    { code: 'DRCL', name: 'Immagini calibrate', included: true },
    { code: 'THM', name: 'Miniature', included: true },
    { code: 'MSK', name: 'Maschere', included: false },
    { code: 'DRXX', name: 'Prodotti scientifici', included: false },
  ],
  Navcam: [
    { code: 'EDR', name: 'Immagini originali', included: true },
    { code: 'RDR', name: 'Immagini elaborate', included: true },
    { code: 'DRCL', name: 'Immagini calibrate', included: true },
    { code: 'THM', name: 'Miniature', included: false },
  ],
  Hazcam: [
    { code: 'EDR', name: 'Immagini originali', included: true },
    { code: 'RDR', name: 'Immagini elaborate', included: true },
    { code: 'THM', name: 'Miniature', included: false },
  ],
  MAHLI: [
    { code: 'EDR', name: 'Immagini originali', included: true },
    { code: 'RDR', name: 'Immagini elaborate', included: true },
    { code: 'DRCL', name: 'Immagini calibrate', included: false },
  ],
  ChemCam: [
    { code: 'EDR', name: 'Immagini originali', included: true },
    { code: 'CCAM', name: 'Spettri LIBS', included: true },
    { code: 'RMI', name: 'Remote Micro-Imager', included: false },
  ],
  MARDI: [
    { code: 'EDR', name: 'Immagini originali', included: true },
    { code: 'RDR', name: 'Immagini elaborate', included: false },
  ],
};
