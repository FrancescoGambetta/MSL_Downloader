# Catalog JSON Rebuild

Questa cartella serve per ricreare con calma i cataloghi JSON grandi, senza mescolarli ai cataloghi ufficiali usati ora dall'app.

## Builder disponibili

- `core/make_msl_catalog.py`
- `core/make_msl_catalog_pre3000.py`

## Config utili

- `config/msl_catalog_config.json`
- `config/pre3000_catalog_config.json`

## Link sorgente attualmente presenti nelle config

- Base PDS MSL:
  - `https://planetarydata.jpl.nasa.gov/img/data/msl/`
- Geo CSV:
  - `https://planetarydata.jpl.nasa.gov/w10n/msl/msl_places/data_localizations/localized_interp_demv2.csv`

## Nota pratica

I JSON ricostruiti progressivamente possono essere salvati qui durante i prossimi giorni, lasciando in `data/catalog/` solo i file ufficiali realmente usati dal runtime.
