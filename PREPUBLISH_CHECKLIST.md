# Pre-publish checklist (DWNAPP)

This document is a practical checklist to prepare a **clean, portable, professional** folder/repo before publishing.

## 0) Decide what you publish

- [ ] Code + docs only, or also **runtime data** (parquet catalogs, geo references)?
- [ ] Decide if `data/catalog/` is bundled (recommended for “works out of the box”) or generated/downloaded.

## 1) Clean local artifacts (must not ship)

- [ ] Remove Python caches: `**/__pycache__/`, `**/*.pyc`, `**/*.pyo`
- [ ] Remove app runtime caches if present:
  - `cache/selected_rows.bin` (selection cache; safe to delete)
  - `data/sessions/*.json` (local sessions; safe to delete)
- [ ] Ensure temporary folders are empty or excluded: `tmp/`, `.claude/`, `.push_export/`, `cache/` (keep `.gitkeep` only if needed)

## 2) Ensure portability (no machine-specific paths)

- [ ] Avoid absolute local paths (examples to check):
  - `C:\Users\...`
  - `/Users/...`, `/home/...`
- [ ] Prefer **relative paths** from project root in configs and metadata.
- [ ] Keep machine-specific UI config out of the publish repo:
  - use `config/app_ui_config.example.json`
  - do not ship `config/app_ui_config.json` (contains local paths/preferences)

## 3) Data policy (parquet catalogs)

If parquet files are **essential** to run the app:
- [ ] Keep required parquet files under `data/catalog/`:
  - `data/catalog/Catalog_PDS.parquet`
  - `data/catalog/Catalog_RawArch.parquet` (optional if your runtime supports missing file)
- [ ] Document size expectations in `data/catalog/README.md`.

If parquet files are large, use Git LFS:
- [ ] Add/verify `.gitattributes` has: `data/catalog/*.parquet filter=lfs diff=lfs merge=lfs -text`
- [ ] On the publishing machine: install/enable LFS (`git lfs install`)
- [ ] Before publishing: verify files are tracked by LFS (`git lfs ls-files`)
- [ ] After cloning the published repo: ensure LFS content is present (otherwise you only have pointers):
  - `git lfs pull`
  - if you still see small text pointer files, re-check that Git LFS is installed on that machine
- [ ] Avoid “manual zip” publishing if you rely on LFS (zip downloads can miss LFS objects depending on how the archive is produced).

## 4) WIP/work areas (keep tidy)

- [ ] Keep rebuild/work folders clearly separated and excluded from release artifacts:
  - `data/catalog_json_rebuild/` should contain only what you intentionally ship
  - ignore generated artifacts there (parquet/state/json as appropriate)

## 5) Docs and entrypoints

- [ ] Ensure root `README.md` is the single entrypoint and matches the shipped content.
- [ ] Ensure docs reference only files that actually ship (e.g. `devtools/` scripts).
- [ ] Add/verify minimal “how to run”:
  - `streamlit run app/app.py`
  - smoke test command (if available)

## 6) Project metadata (recommended for “professional” release)

- [ ] Add a license file (`LICENSE` or `LICENSE.md`)
- [ ] Add `.editorconfig` (line endings/indentation consistency)
- [ ] Optional but helpful: `CONTRIBUTING.md`, `SECURITY.md`, formatter/lint config (`pyproject.toml`, `ruff.toml`, etc.)

## 7) Final smoke check (before pushing/publishing)

- [ ] Fresh env install works (Conda or venv as documented)
- [ ] App starts without manual local tweaks
- [ ] A minimal workflow works:
  - load catalogs
  - apply filters
  - build selection
  - download/process to an output folder
