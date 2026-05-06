# DWNAPP App Guide (EN)

This guide is for someone who downloads the project from GitHub and wants to:
1) install the app, 2) run it, 3) understand what they see on screen, 4) use it to filter and download/process images.

Important note:
- This project was developed and used mainly with **Anaconda/Conda**.
- The `python -m venv` + `pip` procedure is included as an alternative, but **it may not have been fully tested** on all machines yet.

## 1) What is DWNAPP (short)
DWNAPP is a Streamlit app that lets you work with an image catalog from the MSL (Curiosity) mission:
- browse and filter the catalog (by sol, camera, etc.)
- build an image selection
- download and/or process the selection (output to a folder on your computer)
- update the catalog when needed

## 2) Requirements
- **Python**: recommended **3.11 or 3.12**
- **Conda**: recommended on Windows (reduces binary-library issues such as `pyarrow`)
- Internet connection: needed for downloads/catalog updates and to fetch external files (when applicable)

Technical note: `numpy` is pinned to `<2` for compatibility with `pyarrow` in some environments.

## 3) Installation (step by step)

### 3.1 Download the project
Option A (Git):
```bash
mkdir FOLDER_NAME
cd FOLDER_NAME
git clone <REPO_URL> .
```

What these commands do:
- `mkdir FOLDER_NAME`: creates a new folder for the project.
- `cd FOLDER_NAME`: moves into the folder you just created.
- `git clone <REPO_URL> .`: clones the GitHub repository into the current folder (`.`).

Option B (ZIP from GitHub):
- download the ZIP
- extract it to a folder (e.g. `C:\\Users\\...\\dwnapp`)
- open a terminal inside the extracted folder

### 3.2 Create the environment (recommended: Conda)
From repo root:
```bash
conda env create -f environment.yml
conda activate dwnapp
```

What these commands do:
- `conda env create -f environment.yml`: creates a Conda environment named `dwnapp` with the required Python and dependencies.
- `conda activate dwnapp`: activates the `dwnapp` environment (from now on you will use those libraries).

Note about `environment.yml`:
- `environment.yml` creates the environment (Python + pip) and then installs libraries via `pip -r requirements.txt`.
- In other words: **the dependency list is in `requirements.txt`**, while the YAML helps create a clean, consistent environment.

Alternative (venv + pip):
```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

What these commands do:
- `python -m venv .venv`: creates a local virtual environment in the `.venv` folder.
- `.\.venv\Scripts\activate`: activates the virtual environment (Windows PowerShell/cmd).
- `pip install -r requirements.txt`: installs all required libraries.

## 4) Run the app
From repo root:
```bash
streamlit run app/app.py
```

What this command does:
- `streamlit run app/app.py`: starts the app and opens a page in your browser (usually `http://localhost:8501`).

Streamlit should open your browser automatically. If it doesn’t, copy/paste the URL shown in the terminal (usually `http://localhost:8501`).

### (Windows) Double‑click runner
If you don’t want to use the terminal every time:
1) once only: run `Create_env.bat` (creates the Conda environment)
2) to start the app: double‑click `Run_App.bat`

## 5) What you see in the UI (quick tour)
The interface is split into areas:
- **Sidebar** (left): main commands/actions, filters, current selection, control buttons
- **Main area**: response/information text and/or results
- **Viewport/Metadata** (if present): image preview and related metadata
- **Live log**: during download/process it shows progress and messages

## 6) How to use the app (typical workflow)
A typical flow is:
1) Set the output/download folder (if required)
2) Apply filters (sol, camera, etc.)
3) Check the current selection (how many images, what it contains)
4) Run **download** or **process**

### 6.1 Set the output folder
If the app tells you the output folder is missing:
- use the command to choose a folder (dialog) or set a path manually (see examples below)
- then retry download/process

### 6.2 Filter the catalog
You can filter by:
- **sol** (range or single)
- **camera**
- (optional) minimum size, variants, tokens, and other available filters

### 6.3 Download or process
General behavior:
- **Download**: saves raw files (typically `.IMG` + `.LBL`) into the output folder
- **Process/Convert**: produces final outputs (typically `.jpg` + `.meta.json`) into the output folder

## 7) Ready‑to‑paste command examples
Filters:
- `sol 3371`
- `sol da 3300 a 3425`
- `camera mastcam, navcam`
- `mostra filtri`
- `report selezione`

Workflow:
- `scarica`
- `elabora`
- `scarica e elabora`

Configuration:
- `show config`
- `show download path`
- `path download = C:\\percorso\\output`

Catalog update:
- `aggiorna catalogo sol 3371 a 3380 workers 4`

For deeper technical details: `docs/IT/TECHNICAL_GUIDE.md`.

## 8) Common issues (quick fixes)
- **Browser does not open**: use the URL shown in the terminal (e.g. `http://localhost:8501`).
- **“Output path required”**: set an output folder and retry.
- **“Nothing to download/process”**: check `report selezione` and remove overly strict filters.
- **The app looks “stuck”**: use the stop button/action (if available) and retry with a smaller selection.

## 9) Local data (normal)
These folders store local data and can stay empty on Git:
- `cache/` (runtime cache)
- `data/sessions/` (local sessions)
