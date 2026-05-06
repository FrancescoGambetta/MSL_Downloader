# `app/services/` (application services)

Services implement the app’s business logic (catalog ops, filtering, IO, download/process orchestration, etc.).

Guideline used in this codebase:
- UI/panels do rendering and user input.
- Services do the actual work and (when possible) avoid direct Streamlit dependencies by receiving `state` and plain inputs.

Notable services (examples):
- `catalog_update_service.py`: catalog update workflow
- `catalog_filter_service.py`: filter parsing + application
- `download_processing_service.py`: download/process pipeline orchestration
- `runtime_paths_service.py`: resolves runtime paths from config

