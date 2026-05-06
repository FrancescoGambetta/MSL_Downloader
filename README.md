# DWNAPP

Streamlit app for building, browsing, filtering, and downloading MSL (Curiosity) image products with a parser-first workflow and optional LLM fallback.

Made during an internship at GET (Géosciences Environnement Toulouse).

## Setup

This repo keeps both `requirements.txt` and `environment.yml`, with `requirements.txt` as the single source of truth.

Python: 3.11–3.12 supported. Note that `numpy` is pinned to `<2` to avoid binary incompatibilities with `pyarrow` on some environments.

### Conda (recommended)

```bash
conda env create -f environment.yml
conda activate dwnapp
```

### Pip

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## Run

### Windows (double-click)

1) First time only: run `Create_env.bat` (creates the Conda env from `environment.yml`)
2) To start the app: run `Run_App.bat`

### Manual (any OS)

```bash
streamlit run app/app.py
```

## Local UI config

The app reads/writes local UI preferences (theme, language, download path, etc.) in `config/app_ui_config.json`.

- This file is **machine-specific** and should not be published.
- Use `config/app_ui_config.example.json` as a template when setting up a new machine.

## Prepublish smoke test

```bash
python devtools/devtools/prepublish_smoke.py --skip-catalog
```

## Docs

See `docs/README.md` (language guides under `docs/IT`, `docs/EN`, `docs/FR`).

## License

GPL-3.0 (see `LICENSE`).
