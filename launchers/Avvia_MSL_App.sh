#!/usr/bin/env bash
# ==============================================================================
#  BETA — lanciatore Linux generico. Il percorso testato/principale resta
#  Avvia_MSL_App.bat (Windows, in questa stessa cartella). Su Linux le
#  variabili di sistema (percorso di conda, filesystem del drive del
#  progetto, ecc.) cambiano da macchina a macchina: se qualcosa non va, il
#  modo più affidabile resta lanciare i due comandi (uvicorn + npm run dev)
#  a mano in due terminali separati.
# ==============================================================================
set -uo pipefail
# This script lives in launchers/, one level below the project root --
# everything it runs (uvicorn, npm) is relative to the root, not here.
cd "$(dirname "$0")/.."

echo "============================================"
echo "  MSL Downloader + Catalog Manager (BETA)"
echo "============================================"
echo

# "Esegui/Apri nel terminale" dal file manager spesso lancia lo script con
# una shell non di login: ~/.bashrc (dove `conda init` mette conda nel PATH)
# non viene caricato, quindi anche con un terminale vero conda risulta
# "non trovato" pur essendo installato. Prima di arrenderci, proviamo a
# sorgere conda.sh direttamente dalle posizioni di installazione comuni.
if ! command -v conda >/dev/null 2>&1; then
    for candidate in "$HOME/anaconda3" "$HOME/miniconda3" /opt/anaconda3 /opt/miniconda3; do
        if [ -f "$candidate/etc/profile.d/conda.sh" ]; then
            # shellcheck disable=SC1091
            source "$candidate/etc/profile.d/conda.sh"
            break
        fi
    done
fi
if ! command -v conda >/dev/null 2>&1; then
    echo "[ERRORE] conda non trovato nel PATH né nelle posizioni di installazione comuni."
    exit 1
fi
# shellcheck disable=SC1091
source "$(conda info --base)/etc/profile.d/conda.sh"
if ! conda activate dwnapp; then
    echo "[ERRORE] Impossibile attivare l'ambiente Conda dwnapp."
    echo "Va creato una tantum a mano: conda env create -f environment.yml"
    exit 1
fi

# Su un drive exFAT/FAT (niente symlink) frontend/node_modules deve essere un
# bind-mount verso un filesystem nativo (Remonta_NodeModules.sh), altrimenti
# resta una cartella exFAT vuota e "npm run dev" fallisce con un criptico
# "vite: not found" dopo essere partito in background. Se manca, lo rimontiamo
# qui -- serve sudo, quindi questo script va lanciato da un vero terminale
# (un doppio click dal file manager non ha dove far comparire la richiesta
# di password e fallisce in silenzio).
if [ ! -x "frontend/node_modules/.bin/vite" ] && [ -x "./Remonta_NodeModules.sh" ]; then
    echo "frontend/node_modules non è pronto: provo a rimontarlo (serve sudo)..."
    ./Remonta_NodeModules.sh || true
fi
if [ ! -x "frontend/node_modules/.bin/vite" ]; then
    echo "[ERRORE] frontend/node_modules non è ancora pronto (manca node_modules/.bin/vite)."
    echo "Assicurati che 'npm install' sia stato fatto in frontend/, poi riprova."
    exit 1
fi

mkdir -p logs
BACKEND_LOG="logs/webapi.log"
FRONTEND_LOG="logs/frontend.log"

port_listening() {
    # "localhost" and not the literal 127.0.0.1: Vite 6 binds only to the
    # IPv6 loopback ([::1]) on this kind of setup, so a hardcoded IPv4 check
    # never sees it ready (frontend was actually up in ~300ms every time,
    # the script just kept waiting the full 30s regardless).
    (echo > "/dev/tcp/localhost/$1") >/dev/null 2>&1
}

# Backend (webapi, porta 8000) -- --reload-dir limitato alle cartelle python
# vere: senza, --reload guarderebbe anche frontend/node_modules e data/ (job
# staging/log che cambiano di continuo durante uno scan), sprecando inotify
# watch e rischiando riavvii indesiderati a metà job.
if port_listening 8000; then
    echo "Backend già in esecuzione su http://localhost:8000"
else
    echo "Avvio backend (webapi, porta 8000)..."
    nohup uvicorn webapi.main:app --port 8000 \
        --reload --reload-dir webapi --reload-dir core --reload-dir catalog_manager --reload-dir app \
        > "$BACKEND_LOG" 2>&1 &
    echo "  PID backend: $!"
fi

# Frontend (React/Vite, porta 5173). Se frontend/node_modules è su un drive
# exFAT/FAT (niente symlink), va rimontato prima -- vedi ../Remonta_NodeModules.sh.
if port_listening 5173; then
    echo "Frontend già in esecuzione su http://localhost:5173"
else
    echo "Avvio frontend (React, porta 5173)..."
    (cd frontend && nohup npm run dev > "../$FRONTEND_LOG" 2>&1 &)
    echo "  frontend avviato in background"
fi

echo
echo "Attendo che il frontend sia pronto..."
count=0
until port_listening 5173; do
    count=$((count + 1))
    if [ "$count" -ge 30 ]; then
        echo
        echo "[ATTENZIONE] Il frontend non risulta ancora pronto dopo 30s."
        echo "Controlla $FRONTEND_LOG per eventuali errori."
        break
    fi
    sleep 1
done
echo "Frontend pronto (o timeout raggiunto)."

echo
echo "Apro il browser su http://localhost:5173"
if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "http://localhost:5173" >/dev/null 2>&1 &
else
    echo "xdg-open non trovato: apri manualmente http://localhost:5173"
fi

echo
echo "Entrambi i servizi girano in background."
echo "Log: $BACKEND_LOG e $FRONTEND_LOG"
echo "Per fermarli: pkill -f 'uvicorn webapi.main:app' ; pkill -f vite"
