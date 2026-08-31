"""Background job workers for Catalog Manager.

Each module here is a standalone CLI script, launched by `catalog_manager/jobs.py`
as a detached subprocess (`python -m catalog_manager.workers.<name> --job-id ...`),
never imported directly by the Streamlit app. Every worker follows the same
contract: read its job's state JSON under `catalog_manager/data/jobs/`, do its
work while periodically writing progress back to that same file, and watch for
a `.cancel` sentinel file so `jobs.py`'s `request_cancel` can stop it cooperatively.
"""
