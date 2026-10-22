#!/usr/bin/env bash
# Ejecutar DENTRO de la carpeta del ZIP extraído EN la Raspberry.
set -euo pipefail
BASE="$(cd "$(dirname "$0")" && pwd)"
ORIGEN="$BASE/raspberry"
DESTINO="$HOME/portus"
if [[ ! -d "$ORIGEN" || ! -f "$ORIGEN/app_portus.py" ]]; then
  echo 'ERROR: carpeta raspberry/ no encontrada';exit 1
fi
if [[ ! -d "$DESTINO" || ! -f "$DESTINO/portus.db" ]]; then
  echo 'ERROR: no existe ~/portus/portus.db. Instalación nueva: siga el README.';exit 1
fi
for s in bridge_portus.py persistencia_portus.py garita_portus.py pesaje_portus.py operacion_portus.py app_portus.py mensajeria_portus.py; do
  if pgrep -af "[p]ython.*${s}" >/dev/null; then
    echo "ERROR: ${s} sigue ejecutándose. Detén los servicios y vuelve a correr el instalador."
    exit 1
  fi
done
MARCA="$(date +%Y%m%d-%H%M%S)"
RESPALDO="$DESTINO/respaldo_antes_v09_$MARCA"
mkdir -p "$RESPALDO"
# Backup consistente de SQLite usando API de backups, no copy simple sobre WAL abierto.
python3 - "$DESTINO/portus.db" "$RESPALDO/portus.db" <<'PY'
import sqlite3,sys
source=sqlite3.connect(sys.argv[1]);target=sqlite3.connect(sys.argv[2]);
with target:source.backup(target)
source.close();target.close()
print('SQLite respaldado correctamente')
PY
cp -a "$DESTINO/app_portus.py" "$RESPALDO/" 2>/dev/null || true
cp -a "$DESTINO/db_portus.py" "$RESPALDO/" 2>/dev/null || true
cp -a "$DESTINO/templates" "$RESPALDO/" 2>/dev/null || true
# Nunca copia una base, llaves, venv ni configuración local.
cp -a "$ORIGEN"/. "$DESTINO"/
cd "$DESTINO"
chmod +x iniciar_portus.sh detener_portus.sh estado_portus.sh
if [[ -x venv/bin/python ]]; then
  ./venv/bin/python inicializar_db.py
  ./venv/bin/python -m compileall -q .
else
  python3 inicializar_db.py
  python3 -m compileall -q .
  echo 'Recuerda crear el entorno: python3 -m venv venv && venv/bin/pip install -r requirements.txt'
fi
python3 - <<'PY'
from db_portus import conectar
conn=conectar()
rows=conn.execute("SELECT id,estado FROM turnos WHERE estado NOT IN ('Cerrado','Anulado')").fetchall()
if rows:
  print('\nATENCIÓN: existen turnos activos: '+', '.join(f'{r["id"]}/{r["estado"]}' for r in rows))
  print('NO reprogrames el Mega con esos turnos dentro; cargar firmware reinicia la RAM física.')
conn.close()
PY
printf '\nActualización instalada. Backup: %s\n' "$RESPALDO"
echo 'Para iniciar: cd ~/portus && ./iniciar_portus.sh'
echo 'El firmware NO se carga automáticamente (requiere placa sin operaciones activas).'
