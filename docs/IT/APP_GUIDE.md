# Guida App DWNAPP (IT)

Questa guida è pensata per una persona che scarica il progetto da GitHub e vuole:
1) installare l’app, 2) avviarla, 3) capire cosa vede a schermo, 4) usarla per filtrare e scaricare/processare immagini.

Nota importante:
- Questo progetto è stato sviluppato e usato principalmente con **Anaconda/Conda**.
- La procedura con `python -m venv` + `pip` è inclusa come alternativa, ma **potrebbe non essere ancora stata testata a fondo** su tutte le macchine.

## 1) Cos’è DWNAPP (in breve)
DWNAPP è una app Streamlit che ti permette di lavorare con un catalogo di immagini della missione MSL (Curiosity):
- sfogliare e filtrare il catalogo (per sol, camera, ecc.)
- creare una selezione di immagini
- scaricare la selezione e/o processarla (output in una cartella sul tuo PC)
- aggiornare il catalogo quando serve

## 2) Requisiti
- **Python**: consigliato **3.11 o 3.12**
- **Conda**: consigliato su Windows (riduce problemi con librerie “binare” come `pyarrow`)
- Connessione internet: necessaria per download/aggiornamenti catalogo e per scaricare alcuni file esterni (se previsto)

Nota tecnica: `numpy` è vincolato a `<2` per compatibilità con `pyarrow` in alcuni ambienti.

## 3) Installazione (passo‑passo)

### 3.1 Scarica il progetto
Opzione A (Git):
```bash
mkdir NOME_CARTELLA
cd NOME_CARTELLA
git clone <URL_REPO> .
```

Cosa fanno questi comandi:
- `mkdir NOME_CARTELLA`: crea una nuova cartella dove mettere il progetto.
- `cd NOME_CARTELLA`: entra nella cartella appena creata.
- `git clone <URL_REPO> .`: scarica (clona) il progetto da GitHub dentro la cartella corrente (`.`).

Opzione B (ZIP da GitHub):
- scarica lo ZIP
- estrailo in una cartella (es. `C:\\Users\\...\\dwnapp`)
- apri un terminale dentro la cartella estratta

### 3.2 Crea l’ambiente (consigliato: Conda)
Da repo root:
```bash
conda env create -f environment.yml
conda activate dwnapp
```

Cosa fanno questi comandi:
- `conda env create -f environment.yml`: crea un ambiente Conda chiamato `dwnapp` con Python e dipendenze richieste.
- `conda activate dwnapp`: attiva l’ambiente `dwnapp` (da qui in poi userai quelle librerie).

Nota su `environment.yml`:
- `environment.yml` serve a creare l’ambiente (Python + pip) e poi installa le librerie tramite `pip -r requirements.txt`.
- In altre parole: **la lista delle dipendenze è in `requirements.txt`**, mentre lo YAML serve per creare un env “pulito” e coerente.

Alternativa (venv + pip):
```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

Cosa fanno questi comandi:
- `python -m venv .venv`: crea un ambiente virtuale locale nella cartella `.venv`.
- `.\.venv\Scripts\activate`: attiva l’ambiente virtuale (Windows PowerShell/cmd).
- `pip install -r requirements.txt`: installa tutte le librerie necessarie.

## 4) Avvio dell’app
Da repo root:
```bash
streamlit run app/app.py
```

Cosa fa questo comando:
- `streamlit run app/app.py`: avvia l’app e apre una pagina nel browser (di solito `http://localhost:8501`).

Streamlit aprirà il browser automaticamente. Se non lo apre, copia/incolla l’URL che vedi nel terminale (di solito `http://localhost:8501`).

### (Windows) Avvio con doppio click
Se non vuoi usare il terminale ogni volta:
1) una volta sola: esegui `Create_env.bat` (crea l’ambiente conda)
2) per avviare: doppio click su `Run_App.bat`

## 5) Cosa vedo nella UI (tour rapido)
L’interfaccia è divisa in aree:
- **Sidebar** (a sinistra): comandi/azioni principali, filtri, selezione corrente, bottoni di controllo
- **Area centrale**: risposta/testo informativo e/o risultati
- **Viewport/Metadata** (se presenti): preview immagine e metadati associati
- **Live log**: durante download/process mostra avanzamento e messaggi

## 6) Come usare l’app (workflow tipico)
Un flusso tipico è:
1) Impostare (se richiesto) la cartella di output/download
2) Applicare filtri (sol, camera, ecc.)
3) Controllare la selezione (quante immagini, cosa contiene)
4) Eseguire **download** oppure **process**

### 6.1 Impostare la cartella di output
Se l’app ti segnala che manca la cartella di output:
- usa il comando per scegliere la cartella (dialog) oppure imposta un percorso manuale (vedi esempi sotto)
- poi riprova download/process

### 6.2 Filtrare il catalogo
Puoi filtrare per:
- **sol** (range o singolo)
- **camera**
- (opzionale) dimensione minima, varianti, token e altri filtri disponibili

### 6.3 Scaricare o processare
Comportamento generale:
- **Download**: salva i file raw (tipicamente `.IMG` + `.LBL`) nella cartella di output
- **Process/Convert**: produce output finali (tipicamente `.jpg` + `.meta.json`) nella cartella di output

## 7) Esempi di comandi pronti (copia/incolla)
Filtri:
- `sol 3371`
- `sol da 3300 a 3425`
- `camera mastcam, navcam`
- `mostra filtri`
- `report selezione`

Workflow:
- `scarica`
- `elabora`
- `scarica e elabora`

Configurazione:
- `show config`
- `show download path`
- `path download = C:\\percorso\\output`

Aggiornamento catalogo:
- `aggiorna catalogo sol 3371 a 3380 workers 4`

Per approfondire (tecnico): `docs/IT/TECHNICAL_GUIDE.md`.

## 8) Problemi comuni (soluzioni rapide)
- **Non si apre il browser**: usa l’URL mostrato dal terminale (es. `http://localhost:8501`).
- **“Output path required”**: imposta la cartella di output e riprova.
- **“Niente da scaricare/processare”**: controlla `report selezione` e rimuovi filtri troppo restrittivi.
- **L’app sembra “bloccata”**: usa il tasto/azione di stop (se presente) e riprova con una selezione più piccola.

## 9) Dati locali (normale)
Queste cartelle salvano dati locali e possono restare vuote su Git:
- `cache/` (cache runtime)
- `data/sessions/` (sessioni locali)

