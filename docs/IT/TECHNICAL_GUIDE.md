# DWNAPP — Technical Guide (IT)

Questa guida è per chi vuole capire **come funziona il codice** (architettura, moduli, stato runtime) e dove mettere le mani per estendere o fare refactoring senza rompere l’app.

## 1) Panoramica architetturale

L’app è una Streamlit app con layering “pratico”:
- `app/app.py`: entrypoint UI e orchestrazione (rendering + chiamate alle API interne).
- Facade/API interne (stabili): `app/actions.py`, `app/catalog.py`, `app/runtime.py`, `app/session.py`.
  - Obiettivo: mantenere import e rerun stabili anche durante refactor.
- Logica applicativa: `app/services/` (classi e funzioni per responsabilità).
  - I services sono pensati per essere più testabili/riutilizzabili: quando possibile **non dipendono direttamente** da Streamlit e ricevono `state` (che in runtime è `st.session_state`).
- Engine/pipeline: `core/` (decoding, processing, pipeline di output).
- Config: `config/` (paths, intent, regole camera, pipeline catalogo).
- Dati: `data/` (cataloghi parquet, riferimenti geo, ecc.).

## 2) Entry point e UI

- File principale: `app/app.py`
- UI “spezzata” in moduli: `app/ui_panels/`
  - esempio: sidebar/builder, config panel, live log, viewport, metadata.
- Stili: `app/Styles/` (CSS e temi)

Regola pratica:
- UI/panels fanno rendering + raccolgono input utente.
- Le azioni vere (download/process/update) passano sempre da `actions.py` / services.

## 3) Stato runtime (Streamlit session_state)

Lo stato vive in `st.session_state` e include tipicamente:
- dataset corrente e dataframe:
  - `df`, `df_pds`, `df_raw` (cataloghi caricati)
  - `df_filtered`, `df_filtered_pds`, `df_filtered_raw` (risultati filtrati)
- filtri: `filters` (sol range, camere, min size, varianti, token, ecc.)
- selezione: `selected_df` + id persistiti
- output: `download_path`, `saved_output_files`, selection store
- chat/history e live log: `chat_history`, `operation_live_text`, flags di pipeline

File chiave:
- `app/runtime.py`: path, cache, selection store, output index (delegando ai services runtime).
- `app/session.py`: gestione login/salvataggi sessione, snapshot dello “stato utente”, preload asincrono.

### Persistenza locale
Per design, questi dati sono locali (non versionati):
- `cache/` (cache runtime, es. selezioni)
- `data/sessions/` (sessioni utente locali)

Nel repo pubblicato restano vuoti con `.gitkeep`.

## 4) Catalogo: loading, unione e filtri

Cataloghi principali:
- `data/catalog/Catalog_PDS.parquet`
- `data/catalog/Catalog_RawArch.parquet` (opzionale, se presente)

Logica “catalogo”:
- Facade: `app/catalog.py`
- Services principali:
  - `app/services/catalog_io_service.py` (load/prepare index)
  - `app/services/catalog_filter_service.py` (logica filtri)
  - `app/services/catalog_apply_filters_service.py` (apply + cache + selection persistence)
  - `app/services/catalog_analytics_service.py` (report/analytics)
  - `app/services/catalog_rules_service.py` (camera rules compile/load)
  - `app/services/catalog_dataframe_ops_service.py` (dedup/ops dataframe)

Nota: quando sono presenti PDS + RAW, l’app può mantenere anche viste separate e una vista combinata.

## 5) Actions: comandi utente → servizi

- Facade: `app/actions.py`
  - contiene funzioni “API interne” che la UI chiama
  - costruisce e cache-a istanze di service (factory `_get_*`)
  - passa `st.session_state` ai services quando serve

Services tipici coinvolti:
- `DownloadProcessingService`, `ImageProcessingService` (pipeline download/process)
- `LocalCommandHandlerService`, `CommandSubmissionService` (interpretazione comando + esecuzione)
- `CatalogUpdateService` (update catalogo da comando)
- `SelectionService` (reset/default filtri, selezione, ecc.)

## 6) Sessione e preload

`app/session.py` gestisce:
- start/resume/end sessione utente
- snapshot/restore “last_state” (per riaprire l’app come l’ultima volta)
- preload asincrono dello “stato pesante” (cataloghi + config) tramite:
  - `app/services/session_preload_service.py`
  - `app/services/session_store_service.py`

Obiettivo: ridurre tempi percepiti a login/rerun senza cambiare comportamento.

## 7) Config e path

File più importanti:
- `config/runtime_paths.json`: dove si trovano cataloghi/config/selection store
- `config/intent_config.json`: keyword/intenti per comandi
- `config/msl_catalog_config.json`: parametri pipeline catalogo
- `config/camera_rules.json`: regole camera/varianti

Regola: i path runtime vanno risolti sempre da `runtime_paths.json` (non hardcodare path assoluti).

## 8) Devtools

- `devtools/devtools/prepublish_smoke.py`: smoke (compile, JSON validity, import principali, sanity config)
- `devtools/tools/`: tool standalone (EXIF, PDS3 IMG→PNG, ecc.)

## 9) Linee guida per modifiche sicure

1) Cambi piccoli e verificabili: spostare logica nei services mantenendo wrapper in facade.
2) Non cambiare le chiavi di `st.session_state` senza motivo.
3) Evitare dipendenze circolari:
   - preferire `app/app.py` → facade → services
   - evitare `services -> facade` (se serve, passare callable/injection)
4) Validare con smoke test:
```bash
python devtools/devtools/prepublish_smoke.py --skip-catalog
```

## 10) Dove iniziare se vuoi contribuire

- UI/UX: `app/ui_panels/`
- Filtri catalogo: `app/services/catalog_*`
- Pipeline download/process: `app/services/download_processing_service.py`, `app/services/image_processing_service.py`
- Stato/sessione: `app/runtime.py`, `app/session.py`, `app/services/session_*`

