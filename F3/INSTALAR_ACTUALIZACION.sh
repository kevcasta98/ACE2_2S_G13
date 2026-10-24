#!/usr/bin/env bash
# PORTUS Fase 3 - Actualización aditiva de la Raspberry, SIN portus.db en ZIP.
set -euo pipefail
BASE="$(cd "$(dirname "$0")" && pwd)"
ORIGEN="$BASE/raspberry"
DESTINO="$HOME/portus"
[[ -f "$ORIGEN/app_portus.py" ]] || { echo 'ERROR: no se encontró raspberry/app_portus.py';exit 1; }
[[ -f "$DESTINO/portus.db" ]] || { echo 'ERROR: no hay ~/portus/portus.db; no se crean datos de demostración.';exit 1; }
for s in bridge_portus.py persistencia_portus.py garita_portus.py pesaje_portus.py operacion_portus.py fase3_servicio.py app_portus.py mensajeria_portus.py; do
 if pgrep -af "[p]ython.*${s}" >/dev/null; then
  echo "ERROR: ${s} sigue activo. Detén PORTUS para aplicar la actualización." >&2
  exit 1
 fi
done
MARCA="$(date +%Y%m%d-%H%M%S)"
RESPALDO="$DESTINO/respaldo_antes_fase3_$MARCA"
mkdir -p "$RESPALDO"
python3 - "$DESTINO/portus.db" "$RESPALDO/portus.db" <<'PY'
import sqlite3,sys
con=sqlite3.connect(sys.argv[1]); b=sqlite3.connect(sys.argv[2]);con.backup(b);b.close();con.close()
PY
for p in app_portus.py garita_portus.py pesaje_portus.py db_portus.py iniciar_portus.sh; do
 [[ ! -f "$DESTINO/$p" ]] || cp -a "$DESTINO/$p" "$RESPALDO/"
done
[[ ! -d "$DESTINO/templates" ]] || cp -a "$DESTINO/templates" "$RESPALDO/"
# Copia solo código y plantillas: el paquete no contiene portus.db ni .env.
cp -a "$ORIGEN"/. "$DESTINO"/
cd "$DESTINO"
chmod +x iniciar_portus.sh estado_portus.sh detener_portus.sh
PYTHON=python3
[[ ! -x venv/bin/python ]] || PYTHON="./venv/bin/python"
"$PYTHON" -m compileall -q .
"$PYTHON" - <<'PY'
from db_portus import inicializar_bd
from fase3_db import migrar
inicializar_bd();migrar()
print('Migración Fase 3 completada. Datos anteriores preservados.')
PY
"$PYTHON" - <<'PY'
from db_portus import conectar
c=conectar()
r=c.execute("SELECT id,estado FROM turnos WHERE estado NOT IN ('Cerrado','Anulado')").fetchall()
if r:
 print('ADVERTENCIA: Turnos activos: '+', '.join(f"{x['id']}/{x['estado']}" for x in r))
 print('NO programes el Mega hasta reconciliar físicamente estas operaciones.')
c.close()
PY
printf '\nPaquete instalado. Respaldo consistente: %s\n' "$RESPALDO"
echo 'Configura la cámara, los modelos y el puerto de GARITA en ~/portus/.env antes de iniciar.'
echo 'El firmware Arduino NO se carga automáticamente.'
