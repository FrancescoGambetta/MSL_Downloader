# MSL Downloader

Local web app to search, filter and download NASA Mars Science Laboratory
(Curiosity rover) image products, plus a Catalog Manager that builds and keeps
up to date the local product catalogs it searches (PDS and RAW Archive).
Includes camera specific decoding/processing (Mastcam Bayer demosaic, MARDI
geometric correction, ChemCam handling) and a multi language UI (IT, EN, FR,
ES, DE).

Made during an internship at GET (Géosciences Environnement Toulouse).

## Architecture

- Frontend: React + Vite + Tailwind, in `frontend/`
- Backend: FastAPI, in `webapi/`
- Scanning / cataloging engine: `core/`
- Catalog Manager job orchestration: `catalog_manager/`
- Shared backend library, originally built for an earlier Streamlit
  interface (since removed): `app/`, imported directly by `webapi/`.

## Setup

Python 3.11 to 3.12. `numpy` is pinned below 2.0 to avoid binary
incompatibilities with `pyarrow` on some systems.

### Backend (Python)

Conda (recommended):

```bash
conda env create -f environment.yml
conda activate dwnapp
```

Pip:

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Note: `requirements.txt` still lists `streamlit`. There is no Streamlit UI in
this repo anymore, but `app/actions.py`, `runtime.py`, `session.py` and
`catalog.py` (reused as a library by `webapi/`) import it directly, so it
stays a real dependency.

### Frontend (Node.js 18+)

```bash
cd frontend
npm install
```

If the project folder lives on a filesystem without symlink support (exFAT,
FAT32, some network drives), `npm install` fails inside `node_modules/.bin`.
Run `./Remonta_NodeModules.sh` first (Linux/macOS, needs sudo once per
boot/mount) to bind mount `frontend/node_modules` onto a real filesystem,
then retry.

## Run

Windows: double click `launchers/Avvia_MSL_App.bat`. It starts the backend
(port 8000) and the frontend dev server (port 5173) and opens your browser.

Linux/macOS: `launchers/Avvia_MSL_App.sh` (marked BETA). If it does not work
on your setup, run the two services by hand in two terminals:

```bash
conda activate dwnapp
uvicorn webapi.main:app --port 8000
```

```bash
cd frontend
npm run dev
```

Then open http://localhost:5173.

## First run: catalog data

The PDS and RAW Archive catalogs are not stored in this git repo. On first
run, use the Catalog Manager's "Download and Install" flow inside the app to
fetch a prebuilt catalog release instead of scanning NASA/PDS servers from
scratch.

## Checks

Frontend:

```bash
cd frontend
npm run lint
npm run typecheck
```

Backend / engine smoke test (currently covers `core/` and `app/` only, not
yet `webapi/` or `frontend/`):

```bash
python devtools/prepublish_smoke.py --skip-catalog
```

## Docs

See `docs/README.md`.

## License

GPL-3.0 (see `LICENSE`).
