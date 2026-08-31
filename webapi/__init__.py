"""HTTP API bridging the React frontend (`frontend/`) to the existing Python backend
(`core/`, `app/services/*`, `catalog_manager/*`). Nothing here reimplements business
logic -- every endpoint is a thin wrapper that imports and calls the same functions/
services the Streamlit apps (`app/app.py`, `catalog_manager/app.py`) already use, so the
three surfaces (MSL Downloader UI, Catalog Manager UI, this API) can never drift out of
sync on what a "camera filter" or a "catalog update" actually means.
"""
