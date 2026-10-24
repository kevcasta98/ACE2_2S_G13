#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
echo '=== PORTUS ==='
systemctl is-active mosquitto || true
ls -l /dev/ttyACM* 2>/dev/null || true
for n in bridge_portus.py persistencia_portus.py garita_portus.py pesaje_portus.py operacion_portus.py fase3_servicio.py app_portus.py mensajeria_portus.py; do
  echo "[$n]";pgrep -af "[p]ython.*${n}" || true
done
echo '[Puerto web]';ss -lnt | grep ':5000 ' || true
echo '[Ultimo log bridge]';tail -n 5 logs/bridge.log 2>/dev/null || true
