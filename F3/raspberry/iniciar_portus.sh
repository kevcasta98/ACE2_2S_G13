#!/usr/bin/env bash
# PORTUS v0.9: inicia servicios sin sobrescribir base ni reprogramar Arduino.
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -f portus.db ]]; then
  echo 'ERROR: falta portus.db. No se generará ni poblará una base automáticamente.' >&2
  exit 1
fi
if [[ ! -x venv/bin/python ]]; then
  echo 'ERROR: falta ~/portus/venv. Crea el venv y pip install -r requirements.txt.' >&2
  exit 1
fi
PUERTO_SERIAL="${PORTUS_SERIAL_PORT:-/dev/ttyACM0}"
if [[ ! -e "$PUERTO_SERIAL" ]]; then
  echo "ADVERTENCIA: $PUERTO_SERIAL no existe. Revisa USB antes de autorizar entradas." >&2
  exit 1
fi
if ! systemctl is-active --quiet mosquitto; then
  echo 'ERROR: Mosquitto no está activo. Ejecuta: sudo systemctl start mosquitto' >&2
  exit 1
fi
mkdir -p .run logs
# Solo crea el secreto la primera vez; nunca pisa uno previamente configurado.
if [[ -f .env ]]; then
  set -a; source ./.env; set +a
fi
if [[ -z "${PORTUS_SECRET_KEY:-}" ]]; then
  if [[ -f .run/secret_key ]]; then
    export PORTUS_SECRET_KEY="$(cat .run/secret_key)"
  else
    umask 077
    venv/bin/python -c 'import secrets;print(secrets.token_hex(32))' > .run/secret_key
    export PORTUS_SECRET_KEY="$(cat .run/secret_key)"
  fi
fi
# Una instancia por script; no lanzar un duplicado si ya existe manualmente.
run_one() {
  local script="$1" name="$2"
  if pgrep -af "[p]ython.*${script}" >/dev/null; then
    echo "EN EJECUCIÓN: ${script} (no se inicia duplicado)"
    return
  fi
  nohup ./venv/bin/python -u "${script}" >>"logs/${name}.log" 2>&1 </dev/null &
  local pid=$!
  echo "$pid" > ".run/${name}.pid"
  sleep 0.25
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "ERROR iniciando ${script}. Revisa logs/${name}.log" >&2
    return 1
  fi
  echo "INICIADO ${script} PID ${pid}"
}
run_one bridge_portus.py bridge
run_one persistencia_portus.py persistencia
run_one garita_portus.py garita
run_one pesaje_portus.py pesaje
run_one operacion_portus.py operacion
# Evitar dos instancias del servidor web incluso si se llama con gunicorn u otra forma.
if ! ./venv/bin/python - <<'PY'
import socket
s=socket.socket(); s.settimeout(.3)
rc=s.connect_ex(('127.0.0.1',5000)); s.close()
raise SystemExit(0 if rc else 1)
PY
then
  echo 'WEB ya ocupa el puerto 5000: no iniciar otra instancia.'
else
  run_one app_portus.py web
fi
if [[ -n "${PORTUS_TELEGRAM_TOKEN:-}" && "${PORTUS_TELEGRAM_TOKEN}" != 'PEGAR_TOKEN_AQUI' ]]; then
  run_one mensajeria_portus.py telegram
else
  echo 'TELEGRAM no configurado; usar simular_transportista.py para pruebas.'
fi
echo 'PORTUS listo para comprobación. Ejecuta ./estado_portus.sh y revisa http://IP_RASPBERRY:5000'
