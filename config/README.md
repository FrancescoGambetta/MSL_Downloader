# `config/` (configuration)

JSON configuration files used by the app and builders.

Common files:
- `runtime_paths.json`: runtime path overrides (catalog parquet paths, geo csv path, selection cache path, etc.)
- `msl_catalog_config.json`: main catalog build config
- `pre3000_catalog_config.json`: pre-3000 catalog build config
- `parser_defaults.json`, `prompt_rules.json`, `intent_config.json`: parsing/intent rules
- `camera_rules.json`, `camera_intrinsics.json`: camera rules and constants

Local-only:
- `app_ui_config.json`: local UI preferences (machine-specific; template is `app_ui_config.example.json`)

