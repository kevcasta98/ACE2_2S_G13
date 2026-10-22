#!/usr/bin/env bash
set -euo pipefail
DEST="${1:-$HOME/portus}"
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$DEST"
if [[ -f "$DEST/portus.db" ]]; then
  cp "$DEST/portus.db" "$DEST/portus_respaldo_$(date +%Y%m%d_%H%M%S).db"
  echo "[OK] Respaldo de portus.db creado."
fi
cp -a "$HERE/." "$DEST/"
rm -f "$DEST/INSTALAR_SOBRE_PROYECTO_EXISTENTE.sh"
echo "[OK] Archivos actualizados en $DEST"
echo "[INFO] No se incluyó ni sobrescribió portus.db desde el paquete."
