# DWNAPP Docs

This folder contains the current documentation package for the app, organized by language.

## Language folders

- `IT/`: `APP_GUIDE.md` (app guide, Italian), `TECHNICAL_GUIDE.md` (architecture notes, Italian)
- `EN/`, `FR/`, `ES/`, `DE/`: `APP_GUIDE.md`

## Quick pointers

- Frontend: `frontend/` (React + Vite + Tailwind)
- Backend: `webapi/` (FastAPI)
- Shared engine/session library, used by both the backend and the legacy Streamlit app: `app/` (see `docs/APP_STRUCTURE.md`)
- Scanning/cataloging engine: `core/`
- Catalog Manager orchestration: `catalog_manager/`
- Shared runtime paths: `config/runtime_paths.json`
- Local UI config (legacy Streamlit app + shared runtime defaults; machine specific): `config/app_ui_config.json` (template: `config/app_ui_config.example.json`)
- Catalog pipeline config: `config/msl_catalog_config.json`
- Catalog outputs (parquet): `data/catalog/Catalog_PDS.parquet` (+ optional `data/catalog/Catalog_RawArch.parquet`)
- Pre-3000 catalog builder: `core/make_msl_catalog_pre3000.py`
- Pre-3000 catalog config: `config/pre3000_catalog_config.json`

## Code structure

- `docs/APP_STRUCTURE.md` (project folder map)
- `docs/IT/TECHNICAL_GUIDE.md` (architecture deep dive, Italian)

## Notes

- Dependency policy: keep both `requirements.txt` and `environment.yml`;
  `requirements.txt` is the single source of truth; `environment.yml`
  installs via `pip -r requirements.txt` to avoid drift.
