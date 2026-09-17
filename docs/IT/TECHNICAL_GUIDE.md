# MSL Downloader — Guida Tecnica (IT)

Questa guida è per chi vuole capire come funziona il codice (architettura,
moduli, stato runtime) e dove metter mano per estendere o fare refactoring
senza rompere l'app.

## 1) Panoramica architetturale

L'app è un frontend React che parla con un backend FastAPI:

- `frontend/`: UI (React più Vite più Tailwind). Vedi `frontend/AGENTS.md`
  per la mappa dei file.
- `webapi/`: backend FastAPI (`main.py` più i suoi moduli di route/service).
- `core/`: motore di scansione/catalogazione e di decodifica/processing
  delle immagini.
- `catalog_manager/`: orchestrazione dei job che costruiscono e aggiornano
  i due cataloghi locali (PDS e RAW Archive). Nessuna UI propria.
- `app/`: libreria condivisa di sessione/azioni/runtime, nata per una UI
  Streamlit più vecchia che è stata rimossa (vedi punto 2); oggi è
  importata direttamente dal backend.

## 2) Come app/ diventa parte del backend

`webapi/main.py`, `webapi/download_service.py`, `webapi/catalog_service.py`
e `webapi/session_service.py` importano direttamente `runtime`, `actions`,
`catalog` e alcuni moduli di `services/` da `app/`. La UI Streamlit vera e
propria (`app.py`, `ui.py`, `ui_panels/`, `help.py`, `Guida.md`) è stata
rimossa perché sostituita dal frontend React; lo stesso vale per la UI
Streamlit del Catalog Manager (`catalog_manager/app.py`,
`catalog_manager/i18n_catalog.py`).

Due particolarità da tenere a mente:

- `app/session.py` importa ancora `Styles/themes.py` (solo per i valori di
  default di tema), quindi la cartella `Styles/` resta nel repo anche se non
  c'è più nessuna UI che la usi per il rendering.
- `app/actions.py`, `runtime.py`, `session.py` e `catalog.py` fanno tutti
  `import streamlit` in testa al file. Per questo `streamlit` resta una
  dipendenza reale in `requirements.txt`, anche se in tutto il repo non c'è
  più nessuna riga di UI Streamlit.

## 3) Ciclo di una richiesta (esempio: download)

1. Il frontend (`frontend/src/lib/mslApi.js`) chiama `POST
   /api/download/start` con i record trovati dalla ricerca e la cartella di
   destinazione.
2. `webapi/main.py` valida la richiesta e chiama
   `webapi/download_service.start_job(...)`.
3. `download_service.py` lancia un **thread in background** (non un
   subprocess) che richiama le stesse funzioni di `app/actions.py` (decodifica
   PDS via `core/engine_pipeline.py`, demosaic Bayer Mastcam, correzione
   geometrica MARDI, gestione ChemCam, organizzazione cartelle in output).
4. Lo stato del job vive in un dizionario in memoria (`_JOBS`), niente
   persistenza su riavvio del server: va bene per un uso locale mono utente.
5. Il frontend fa polling di `GET /api/download/{job_id}` ogni 1 o 2 secondi
   per log/progresso, e può cancellare con `POST
   /api/download/{job_id}/cancel` (cancellazione cooperativa, non a metà
   file).

## 4) Ciclo di un job del Catalog Manager

Modello diverso da quello dei download: qui i job (aggiornamento catalogo,
verifica integrità, personalizzazione per camera, ecc.) sono **subprocess
veri e staccati**, lanciati da `catalog_manager/jobs.py` come script in
`catalog_manager/workers/`, con stato persistito su file JSON sotto
`data/catalog/jobs/{active,completed}/`. Sopravvivono a un riavvio del
frontend e vengono "sanati" automaticamente se il processo muore
(`_job_is_stale`/`_reap_stale_job` in `jobs.py`). Il frontend li raggiunge
tramite `webapi/catalog_manager_routes.py` più `catalog_manager_service.py`,
non direttamente.

## 5) Config e path

File più importanti:

- `config/runtime_paths.json`: dove si trovano cataloghi/config/selection
  store
- `config/msl_catalog_config.json`: parametri pipeline catalogo
- `config/camera_rules.json`: regole camera/varianti
- `config/app_ui_config.json`: preferenze/default locali machine specific,
  letto da `app/runtime.py` (quindi anche dal backend, per i default come la
  cartella di download); il frontend React tiene le sue preferenze UI
  (lingua, tema, font) separatamente nel `localStorage` del browser via
  `AppSettingsContext.jsx`

Regola: i path runtime vanno risolti sempre da `runtime_paths.json`, non
hardcodare path assoluti.

## 6) Traduzioni (i18n)

Due livelli separati:

- `frontend/src/lib/translations.js`: stringhe della UI React (5 lingue)
- `app/i18n_app.json` più `app/i18n_helper.py`: stringhe backend/log, lette
  da `webapi/i18n_state.py` (stato lingua thread-local, così i messaggi di
  un job lanciato in francese tornano in francese)

## 7) Devtools

- `devtools/prepublish_smoke.py`: smoke test (compile, validità JSON,
  import principali, sanity config). Copre solo `core/` e `app/`: non
  controlla ancora `webapi/` o `frontend/`.
  ```bash
  python devtools/prepublish_smoke.py --skip-catalog
  ```
- `devtools/tools/`: tool standalone (EXIF, PDS3 IMG→PNG, ecc.)

## 8) Linee guida per modifiche sicure

1. Cambi piccoli e verificabili: se tocchi `app/actions.py` o
   `app/runtime.py`, ricorda che sono importati anche da
   `webapi/download_service.py` e `webapi/main.py`.
2. Evitare dipendenze circolari tra `webapi/` e `app/`: il backend importa
   da `app/`, non il contrario.
3. Validare con lo smoke test:

```bash
python devtools/prepublish_smoke.py --skip-catalog
```

4. Per cambi solo nel frontend: `npm run lint` e `npm run typecheck` dentro
   `frontend/`.

## 9) Dove iniziare se vuoi contribuire

- UI React: `frontend/src/pages/`, `frontend/src/components/` (vedi
  `frontend/AGENTS.md`)
- Backend/API: `webapi/main.py` più i suoi moduli `*_routes.py`/
  `*_service.py`
- Pipeline download/process condivisa:
  `app/services/download_processing_service.py`,
  `app/services/image_processing_service.py`, `core/engine_pipeline.py`
- Catalog Manager: `catalog_manager/jobs.py`, `catalog_manager/services.py`,
  `catalog_manager/workers/`
