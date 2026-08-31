# MSL Image Downloader Guide (EN)

This guide is meant for someone downloading the project from GitHub who wants to:
1) install the app, 2) start it, 3) understand what's on screen, 4) use it to filter and download/process images.

> **Important note**
> - This project was developed and used mainly with **Anaconda/Conda**.
> - The `python -m venv` + `pip` procedure is included as an alternative, but **may not have been thoroughly tested yet** on every machine.

## 1) What MSL Image Downloader is
MSL Image Downloader is an app for finding, downloading, and organizing images from NASA's Mars Science Laboratory (Curiosity) mission. On opening you start from a screen where you enter your name, then land in the app itself, split into two sections you can switch between at any time from the top:

- **Downloader**: search, filter, and download images.
- **Catalogs (Catalog Manager)**: manages the local catalog the Downloader's search relies on (status, updates from NASA, verification, etc.).

The catalog downloads automatically on first launch — no manual step needed.

## 2) Requirements
- **Python**: **3.11 or 3.12** recommended
- **Conda**: recommended (reduces issues with "binary" libraries like `pyarrow`)
- Internet connection: needed for catalog downloads/updates and to fetch some external files (where applicable)

> **Technical note**: `numpy` is pinned to `<2` for compatibility with `pyarrow` in some environments.

## 3) Installation (step by step) — Windows

> This section covers installation **on Windows**.

### 3.1 Get the project
Option A (Git):
```bash
mkdir FOLDER_NAME
cd FOLDER_NAME
git clone <REPO_URL> .
```

Option B (ZIP from GitHub):
- download the ZIP
- extract it into a folder (e.g. `C:\Users\...\dwnapp`)
- open a terminal inside the extracted folder

### 3.2 Create the environment (Conda recommended)
From the repo root:
```bash
conda env create -f environment.yml
conda activate dwnapp
```

Note on `environment.yml`:
- `environment.yml` creates the environment (Python + pip) and then installs the libraries via `pip -r requirements.txt`.
- In other words: **the dependency list lives in `requirements.txt`**, while the YAML file creates a clean, consistent environment.

Alternative (venv + pip):
```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## 4) Starting the app
To keep things simple, a single file was created: just open it (double-click, on Windows) and the app starts on its own.

Double-click `launchers/Avvia_MSL_App.bat`: it opens the browser at `http://localhost:5173` once everything's ready.

## 5) What you'll see in the UI (quick tour)
After logging in, the **Catalogs** section opens first, so you can download and optionally customize the local catalog. Once the guided install is done, switch to the **Downloader** from the selector at the top.

In the Downloader, the interface is split into areas:
- **Sidebar** (left): filters, current selection, control buttons
- **Center area**: search results
- **Viewport/Metadata**: image preview and associated metadata
- **Live log**: shows progress and messages during download

The output folder can be set from Settings, top right.

## 6) Using the app (typical workflow)
A typical flow:
1) Set the output/download folder
2) Apply filters (sol, camera, etc.)
3) Check the selection (how many images, what it contains)
4) Run **download** or **process**

### 6.1 Setting the output folder
If the app tells you the output folder is missing:
- use the option to pick a folder (dialog) or set a manual path (see examples below)
- then retry download/process

### 6.2 Filtering the catalog
You can filter by:
- **sol** (range or single)
- **camera**
- (optional) minimum size, variants, tokens, and other available filters

### 6.3 Downloading or processing
General behavior:
- **Download**: saves the raw files (typically `.IMG` + `.LBL`) to the output folder
- **Process/Convert**: produces the final output (typically `.jpg` + `.meta.json`) in the output folder
