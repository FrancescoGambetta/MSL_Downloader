# Guida MSL Image Downloader (IT)

Questa guida è pensata per una persona che scarica il progetto da GitHub e vuole:
1) installare l'app, 2) avviarla, 3) capire cosa vede a schermo, 4) usarla per filtrare e scaricare/processare immagini.

> **Nota importante**
> - Questo progetto è stato sviluppato e usato principalmente con **Anaconda/Conda**.
> - La procedura con `python -m venv` + `pip` è inclusa come alternativa, ma **potrebbe non essere ancora stata testata a fondo** su tutte le macchine.

## 1) Cos'è MSL Image Downloader
MSL Image Downloader è un'app per cercare, scaricare e organizzare le immagini della missione MSL (Curiosity) della NASA. All'apertura si entra da una schermata con il proprio nome, poi si arriva sull'app vera e propria, divisa in due sezioni scelte dall'alto in qualsiasi momento:

- **Downloader**: cerca, filtra e scarica le immagini.
- **Cataloghi (Catalog Manager)**: gestisce il catalogo locale su cui si basa la ricerca del Downloader (stato, aggiornamenti da NASA, verifica, ecc.).

Il catalogo si scarica automaticamente al primo avvio, nessun passaggio manuale richiesto.

## 2) Requisiti
- **Python**: consigliato **3.11 o 3.12**
- **Conda**: consigliato (riduce problemi con librerie "binarie" come `pyarrow`)
- Connessione internet: necessaria per download/aggiornamenti catalogo e per scaricare alcuni file esterni (se previsto)

> **Nota tecnica**: `numpy` è vincolato a `<2` per compatibilità con `pyarrow` in alcuni ambienti.

## 3) Installazione (passo‑passo) — Windows

> Questa sezione riguarda l'installazione **su Windows**.

### 3.1 Scarica il progetto
Opzione A (Git):
```bash
mkdir NOME_CARTELLA
cd NOME_CARTELLA
git clone <URL_REPO> .
```

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

Nota su `environment.yml`:
- `environment.yml` serve a creare l’ambiente (Python + pip) e poi installa le librerie tramite `pip -r requirements.txt`.
- In altre parole: **la lista delle dipendenze è in `requirements.txt`**, mentre lo YAML serve per creare un env “pulito” e coerente.

Alternativa (venv + pip):
```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## 4) Avvio dell'app
Per semplificare l'avvio è stato creato un unico file: basta aprirlo (doppio click, da Windows) e l'applicazione si avvia da sola.

Doppio click su `launchers/Avvia_MSL_App.bat`: apre il browser su `http://localhost:5173` quando è tutto pronto.

## 5) Cosa vedo nella UI (tour rapido)
Dopo il login si apre la sezione **Cataloghi**, per scaricare ed eventualmente modificare il catalogo locale. Una volta completata la procedura guidata di installazione, si passa al **Downloader** dal selettore in alto.

Nel Downloader l'interfaccia è divisa in aree:
- **Sidebar** (a sinistra): filtri, selezione corrente, bottoni di controllo
- **Area centrale**: risultati della ricerca
- **Viewport/Metadata**: anteprima immagine e metadati associati
- **Live log**: durante il download mostra avanzamento e messaggi

La cartella di output è selezionabile dalle Impostazioni, in alto a destra.

## 6) Come usare l’app (workflow tipico)
Un flusso tipico è:
1) Impostare la cartella di output/download
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


