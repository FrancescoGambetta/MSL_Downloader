# MSL Downloader V03 — Handoff (passaggio da Windows a Linux)

Questo file serve a far ripartire una sessione Claude su un'altra macchina (Linux) senza dover rispiegare da capo cosa è stato fatto. Tutti i path sotto sono **relativi alla root del repo** — su Linux la root sarà una directory diversa (non più `E:\Msl_Downloader_V03` / `D:\Msl_Downloader_V03` di Windows), il resto della struttura è identico.

## ⚠️ Prima di fare qualunque cosa

- **Non creare l'ambiente conda in automatico.** Lo crea l'utente sulla macchina Linux. Se serve, limitati a verificare/segnalare cosa manca.
- **`Avvia_MSL_App.bat` e `Create_env.bat` sono script Windows puri** (sintassi `cmd.exe` + PowerShell) — su Linux non girano così come sono. I comandi che lanciano (`uvicorn webapi.main:app --port 8000`, `npm run dev --prefix frontend`, `conda env create -f environment.yml`) sono invece cross-platform. Se in futuro serve un lanciatore Linux, va scritto come `.sh` equivalente (controllo porte con `ss`/`lsof` invece di `Get-NetTCPConnection`, processi in background invece di `start cmd /k`) — **non farlo finché non viene chiesto esplicitamente**, per ora limitati a verificare che la logica dei due bat sia compatibile/riproducibile.
- L'utente scrive in italiano, informale, a volte con refusi — rispondi in italiano, tono diretto, **pochi token**, niente giri di parole. Chiede spesso conferma prima di azioni irreversibili o mentre un job sta girando: **non avviare/fermare/testare job reali senza permesso esplicito**, soprattutto se l'utente dice "ci stiamo ragionando" o "non farlo ora".
- Cancellazioni file finora fatte sempre "solo cestino" (mai delete permanente) — su Windows via `Microsoft.VisualBasic.FileIO.FileSystem` con `RecycleOption.SendToRecycleBin`. Su Linux non esiste equivalente diretto pronto: se serve cancellare qualcosa, chiedi prima come preferisce farlo (es. `trash-cli`/`gio trash` se disponibile) invece di fare `rm` diretto.

## 1. Cos'è il progetto

App per scaricare immagini del rover Mars Curiosity (MSL) dagli archivi NASA, più un **Catalog Manager** che costruisce/aggiorna in locale i cataloghi prodotto (due fonti: **PDS** e **RAW Archive**) leggendo dai server NASA/PDS Geosciences.

- **Frontend**: React + Vite + Tailwind, in `frontend/`
- **Backend**: FastAPI, in `webapi/`
- **Logica di scansione/catalogazione**: `core/*.py` (un modulo per camera/fonte)
- **Orchestrazione job del Catalog Manager**: `catalog_manager/`
- Ambiente conda: `dwnapp` (definito in `environment.yml` + `requirements.txt`)
- Branch git di lavoro: `FINAL` (main branch: `main`)

## 2. Struttura repo (essenziale)

```
frontend/src/components/download/     UI flusso download (DownloadPreparation.jsx, LiveLog.jsx, ImageResults.jsx, MetadataPanel.jsx)
frontend/src/components/catalog/tabs/ UI Catalog Manager (CatalogOverview.jsx, CatalogUpdates.jsx, ...)
frontend/src/components/settings/     SettingsPanel.jsx
frontend/src/lib/                     translations.js (i18n it/en/fr/es/de), AppSettingsContext.jsx,
                                       useDownloader.js, mslApi.js, catalogManagerApi.js, themes.js

webapi/main.py                        route FastAPI (incl. /api/meta/{job_id}/{product_id}, route catalog manager)
webapi/download_service.py            job runner download (start_job, _run_job, get_meta_json, _find_file_any_case)
webapi/i18n_state.py                  stato lingua thread-local + t() per i messaggi log lato backend
webapi/catalog_manager_service.py     webapi/catalog_manager_routes.py

catalog_manager/jobs.py               stato job (JSON) in data/catalog/jobs/{active,completed}/,
                                       ogni job ha sol_start/sol_end/camera(e)
catalog_manager/workers/*.py          worker come subprocess staccati (pds_update_worker.py, raw_update_worker.py, ...),
                                       cancellazione cooperativa via file sentinella .cancel + STOP_EVENT condiviso

core/make_msl_catalog.py              camere standard (mastcam/mahli/navcam/hazcam/mardi), proprio STOP_EVENT,
                                       scan con ThreadPoolExecutor (scan_workers = max(1, min(8, len(pending_locs))))
core/make_msl_chemcam_catalog.py      ChemCam dentro il catalogo PDS — reso STOP_EVENT-aware in questa sessione
core/make_msl_pds_catalog.py          dispatcher standard+chemcam, gestisce exit code 2 = "annullato" per entrambi
core/make_msl_raw_catalog.py          RAW Archive (tutte le camere incl. chemcam in un unico loop per-Sol),
                                       proprio STOP_EVENT separato, già corretto da prima di questa sessione

app/i18n_app.json                     stringhe di traduzione backend (5 lingue), incl. chiavi webapi_* aggiunte in sessione
data/catalog/jobs/{active,completed,logs,staging}/   stato job, log testuali, cartelle di staging (possono pesare 600MB+,
                                                       non ripulite automaticamente se un job viene ucciso/interrotto)
```

## 3. Lavoro completato in questa sessione (Windows)

- **Lanciatori**: ridotti a uno solo per l'app (`Avvia_MSL_App.bat`, avvia webapi+frontend) + uno per l'ambiente (`Create_env.bat`), rimossi i vecchi bat Streamlit legacy; shortcut `MSL_Downloader.lnk` ripuntato.
- **UI download**: spaziatura sidebar sistemata, rimossa impostazione API key NASA (morta), nomi palette resi multilingua, aggiunta sezione "metadati avanzati" (GPS/EXIF/post-processing) letta da dati reali via nuovo endpoint `GET /api/meta/{job_id}/{product_id}`, fix overflow testo bottone filtri, traduzione end-to-end dei messaggi di log (frontend **e** backend, con lingua passata per-job).
- **Bug reali trovati e risolti**:
  - Lookup file case-insensitive (`_find_file_any_case` in `webapi/download_service.py`).
  - Stato "aggiornamento disponibile" non ricalcolato da cache stantia (`attach_remote_status` in `webapi/catalog_manager_service.py`).
  - **Cancellazione ChemCam nel PDS update non funzionava**: `core/make_msl_chemcam_catalog.py` non controllava mai `STOP_EVENT`; `core/make_msl_pds_catalog.py` trattava qualunque exit code ChemCam ≠0 come errore fatale invece di riconoscere 2="annullato". Corretti entrambi, verificato con test live (cancellazione <2s).
- **Catalog Manager → tab Updates** (`frontend/src/components/catalog/tabs/CatalogUpdates.jsx`), riscritta parecchio:
  - Pannello log live a destra (stile identico a `LiveLog.jsx` della parte download: `Panel min-h-[17rem]`, `PanelBody scroll max-h-[20rem]`).
  - `condenseLog()`: collassa righe consecutive con stesso tag `[...]` contenente "product" in `[tag] × N`, tranne `camera_product_scan` (fix: quel tag porta il vero progresso `[X/Y] indexing SOL Z`, non va collassato).
  - `parseProgress()`: legge dal log grezzo lo scan in corso e i prodotti aggiunti — per camere standard da `[camera_product_scan]`/`[catalog_live] items=N`; per ChemCam (che non emette quei tag) conta le righe `[chemcam_sol]`/`[chemcam_sol_missing]` contro `job.sol_start`/`job.sol_end`, e legge i prodotti da `[checkpoint] ... products=N`. Renderizza barra di progresso + contatori (`cat.up.scanned`/`cat.up.products`, 5 lingue in `translations.js`).
  - Righe del log renderizzate con icona+colore per categoria (`classifyLine()`), stile `LiveLog.jsx`: rosso per errori reali, giallo per warning Python, verde per `done`/`checkpoint`/`catalog_live`/`installing`, grigio (`Radio`) di default per tutto il resto — **non** una categoria "scan" a parte (prima versione coloriva quasi tutto di blu perché il tag matchava quasi sempre "scan/sol/product", corretto).
  - Pulsanti-camera disattivati/grigi a job completato; `handleCheck` ora resetta `job`/`logText` a un nuovo controllo (prima restava visibile il riepilogo del job precedente, es. "+8801 total products" non correlato); etichetta "+N" ora specifica "Sol" (es. "+1183 Sol").

## 4. Bug noti, diagnosticati ma NON ancora corretti

**Bug di rimontaggio tab Updates**: `CatalogUpdates.jsx` viene smontato/rimontato ogni volta che si naviga via (Overview, ecc.) e si torna su Updates. Al rimontaggio l'`useEffect` iniziale azzera sempre `newCameras`/`selectedCameras` (mentre `job` viene correttamente ripristinato via `getLatestJob`). Siccome l'intera sezione "Cameras involved" — che contiene barra di progresso e tasto **Stop** — è condizionata da `newCameras.length > 0`, sparisce anche se il job è ancora vivo lato server, finché non si rifà "Check for updates" (che ripopola `newCameras` e fa riapparire tutto, job compreso). Il job non si perde mai (gira indipendente dal frontend), ma si perde temporaneamente l'accesso al tasto Stop. Due possibili fix discussi non ancora scelti/implementati: (a) non azzerare `newCameras`/`selectedCameras` al mount quando c'è già un job attivo, ricostruendoli dai dati del job stesso; (b) scorporare il pannello "job in corso + Stop" da quello "camere rilevate", cosicché non dipenda più da `newCameras`.

## 5. Note operative aggiuntive

- I job del Catalog Manager sono **subprocess staccati**: sopravvivono a un F5/riavvio del frontend, e anche se il webapi viene killato non muoiono da soli — vanno controllati/uccisi separatamente se serve (via PID reale, non solo dal tasto Stop della UI, specie se il bug del punto 4 nasconde il tasto).
- `catalog_manager/jobs.py` ha un meccanismo di self-healing (`_job_is_stale`/`_reap_stale_job`): se il processo di un job è morto (PID non più vivo), al prossimo `load_job` il job viene marcato "failed" e spostato da `active/` a `completed/` automaticamente.
