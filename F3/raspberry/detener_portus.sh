#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
for name in web telegram fase3 operacion pesaje garita persistencia bridge; do
  f=".run/${name}.pid"
  [[ -e "$f" ]] || continue
  pid="$(cat "$f")"
  case "$pid" in *[!0-9]*|'') echo "PID inválido en $f";continue;; esac
  if kill -0 "$pid" 2>/dev/null; then
    args="$(ps -p "$pid" -o args= || true)"
    if [[ "$args" == *"${name}"* ]] || [[ "$name" == web && "$args" == *'app_portus.py'* ]] || [[ "$name" == telegram && "$args" == *'mensajeria_portus.py'* ]]; then
      kill "$pid"
      echo "Detenido ${name} (PID ${pid})"
    elif [[ "$args" == *'bridge_portus.py'* || "$args" == *'persistencia_portus.py'* || "$args" == *'garita_portus.py'* || "$args" == *'pesaje_portus.py'* || "$args" == *'operacion_portus.py'* || "$args" == *'fase3_servicio.py'* ]]; then
      kill "$pid";echo "Detenido ${name} (PID ${pid})"
    else
      echo "No se detiene PID ${pid}: no coincide con un proceso PORTUS."
    fi
  fi
  rm -f "$f"
done
echo 'No se detuvieron instancias externas no creadas por este script.'
