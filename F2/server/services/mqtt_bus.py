# -*- coding: utf-8 -*-
"""
Conexión del servidor con el intermediario MQTT (Mosquitto).

Formato OBLIGATORIO de todo mensaje (sección 10.2), igual en todos los tópicos:
    {
      "id":     "uuid único",
      "ts":     "2026-09-26T10:15:02.123",
      "origen": "controlador" | "servidor" | "usuario",
      "tipo":   "VEHICULO_DETECTADO",
      "seq":    123,              # solo mensajes del controlador (lo pone el puente)
      "datos":  { ... propios del evento ... }
    }

Si paho-mqtt no está instalado o PORTUS_MQTT=0, el servidor sigue funcionando:
los mensajes se guardan en PUBLICADOS (útil para pruebas) y se registran en el log.
"""
import json
import logging
import uuid
from datetime import datetime

from models import db

log = logging.getLogger("portus.mqtt")

_cliente = None
PUBLICADOS = []          # últimos mensajes publicados (depuración / pruebas)
_MAX_PUBLICADOS = 500


def sobre(tipo, datos=None, origen="servidor", seq=None, mensaje_id=None):
    msg = {
        "id": mensaje_id or str(uuid.uuid4()),
        "ts": datetime.now().isoformat(timespec="milliseconds"),
        "origen": origen,
        "tipo": tipo,
        "datos": datos or {},
    }
    if seq is not None:
        msg["seq"] = seq
    return msg


def publicar(topico, tipo, datos=None, origen="servidor", mensaje_id=None):
    """Publica después del COMMIT de la transacción en curso. Devuelve el sobre."""
    msg = sobre(tipo, datos, origen, mensaje_id=mensaje_id)

    def _enviar():
        PUBLICADOS.append((topico, msg))
        del PUBLICADOS[:-_MAX_PUBLICADOS]
        if _cliente is not None:
            _cliente.publish(topico, json.dumps(msg, ensure_ascii=False, default=str), qos=1)
        else:
            log.debug("MQTT deshabilitado, no se envía %s %s", topico, tipo)

    db.al_confirmar(_enviar)
    return msg


def iniciar(host, puerto, al_recibir, suscripciones=("portus/evt/#", "portus/cmd/respuesta")):
    """Conecta en segundo plano. `al_recibir(topico, mensaje_dict)` procesa cada mensaje."""
    global _cliente
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        log.warning("paho-mqtt no está instalado: el servidor corre SIN MQTT.")
        return None

    try:
        cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="portus-servidor")
    except AttributeError:  # paho-mqtt 1.x
        cliente = mqtt.Client(client_id="portus-servidor")

    def on_connect(c, userdata, flags, rc, properties=None):
        log.info("Conectado a MQTT %s:%s (rc=%s)", host, puerto, rc)
        for t in suscripciones:
            c.subscribe(t, qos=1)

    def on_message(c, userdata, m):
        try:
            mensaje = json.loads(m.payload.decode("utf-8"))
        except Exception:
            log.error("Mensaje no JSON en %s: %r", m.topic, m.payload[:200])
            return
        try:
            al_recibir(m.topic, mensaje)
        except Exception:
            log.exception("Error procesando %s", m.topic)

    cliente.on_connect = on_connect
    cliente.on_message = on_message
    cliente.reconnect_delay_set(min_delay=1, max_delay=10)
    cliente.connect_async(host, puerto, keepalive=30)
    cliente.loop_start()
    _cliente = cliente
    return cliente
