# DWNAPP Docs

This folder contains the current documentation package for the app, organized by language.

## Language folders

- `IT/`
  - `APP_GUIDE.md` (app guide in Italian)
  - `TECHNICAL_GUIDE.md` (technical/architecture notes in Italian)
- `EN/`
  - `APP_GUIDE.md` (app guide in English)
- `FR/`
  - `APP_GUIDE.md` (app guide in French)

## Quick pointers

- Main app: `app/app.py`
- Shared runtime paths: `config/runtime_paths.json`
- Local UI config (machine-specific): `config/app_ui_config.json` (template: `config/app_ui_config.example.json`)
- Catalog pipeline config: `config/msl_catalog_config.json`
- Catalog outputs (parquet): `data/catalog/Catalog_PDS.parquet` (+ optional `data/catalog/Catalog_RawArch.parquet`)
- Pre-3000 catalog builder: `core/make_msl_catalog_pre3000.py`
- Pre-3000 catalog config: `config/pre3000_catalog_config.json`

## Code structure

- `docs/APP_STRUCTURE.md` (app folder map)
- `docs/IT/TECHNICAL_GUIDE.md`

## Notes

- Dependency policy:
  - keep both `requirements.txt` and `environment.yml`
  - `requirements.txt` is the single source of truth
  - `environment.yml` installs via `pip -r requirements.txt` to avoid drift
