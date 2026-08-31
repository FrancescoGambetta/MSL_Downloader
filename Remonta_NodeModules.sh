#!/usr/bin/env bash
# Rimonta frontend/node_modules su una cartella reale ext4 (~/.cache/msl-frontend-node_modules)
# tramite bind-mount. Serve perché il repo vive su un drive exFAT, che non supporta
# symlink -- npm ne crea in node_modules/.bin/ ad ogni install, quindi senza questo
# bind-mount "npm install"/"npm run dev" falliscono con EPERM su symlink.
#
# Il bind-mount NON è persistente: va rilanciato ogni volta che riavvii il pc o
# stacchi/riattacchi il drive SSK, prima di "npm install" o "npm run dev".
# Richiede sudo (ti chiede la password se serve).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_NODE_MODULES="$REPO_ROOT/frontend/node_modules"
REAL_DIR="$HOME/.cache/msl-frontend-node_modules"

mkdir -p "$REAL_DIR"

if mountpoint -q "$FRONTEND_NODE_MODULES" 2>/dev/null; then
    echo "OK: node_modules è già montato ($FRONTEND_NODE_MODULES -> $REAL_DIR)."
    exit 0
fi

# mountpoint per il bind-mount: deve esistere come cartella vuota su exFAT
# (una mkdir normale funziona, solo i symlink sono impossibili su exFAT).
mkdir -p "$FRONTEND_NODE_MODULES"

echo "Monto $REAL_DIR su $FRONTEND_NODE_MODULES (serve sudo)..."
sudo mount --bind "$REAL_DIR" "$FRONTEND_NODE_MODULES"
echo "OK: montato. Ora puoi lanciare npm install / npm run dev in frontend/."
