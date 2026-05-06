# `core/` (engine / pipeline)

Core “engine” code used by the app to build catalogs and run processing pipelines.

Main scripts/modules:
- `make_msl_catalog.py`: main catalog builder
- `make_msl_catalog_pre3000.py`: pre-3000 catalog builder
- `engine_pipeline.py`: processing pipeline
- `portable_engine_adapter.py`: adapter layer for portable execution
- `metashape_engine.py`: Metashape-related integration (if available)

