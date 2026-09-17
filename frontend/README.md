# MSL Downloader — Frontend

React + Vite + Tailwind UI for MSL Downloader: search, filter, download and
process NASA MSL (Curiosity) imagery, and manage the local PDS/RAW catalogs,
via the FastAPI backend in `../webapi/`.

## Prerequisites

- Node.js 18+
- The backend running on http://localhost:8000 (see the project root README;
  `npm run dev` alone is not enough)

## Run

```bash
npm install
npm run dev
```

Open http://localhost:5173, with the backend already running.

If `node_modules` sits on a filesystem without symlink support (exFAT,
FAT32), run `../Remonta_NodeModules.sh` first.

## Build

```bash
npm run build
```

Output in `./dist`, previewable with `npm run preview`.

## Checks

```bash
npm run lint
npm run typecheck
```

## Configuration

Open **Settings** in the app for language, theme/palette, font and the
default download folder. These UI preferences are stored in the browser's
localStorage; the catalogs, downloads and jobs themselves live on the
backend and the filesystem, not in the browser.

## Pages

- `/` Landing
- `/download` MSL Downloader (search, filter, download)
- `/catalog-manager` Catalog Manager
