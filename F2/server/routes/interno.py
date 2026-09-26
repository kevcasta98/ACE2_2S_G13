# -*- coding: utf-8 -*-
"""
Entrada alternativa de eventos del controlador por HTTP (misma lógica que MQTT).
Sirve para el simulador y para probar sin Mosquitto. Requiere X-Portus-Token.

POST /api/interno/eventos
    {"topico": "portus/evt/garita", "mensaje": {"id": "...", "ts": "...", "origen": "controlador",
     "tipo": "VEHICULO_DETECTADO", "seq": 1, "datos": {"rfid": "EA225305"}}}
"""
from flask import Blueprint

from models.errores import ErrorPortus
from routes.util import entrada, ok, token_interno
from services import mqtt_bus, operacion

bp = Blueprint("interno", __name__, url_prefix="/api/interno")


@bp.post("/eventos")
@token_interno
def recibir_evento():
    d = entrada()
    topico, mensaje = d.get("topico"), d.get("mensaje")
    if not topico or not isinstance(mensaje, dict):
        raise ErrorPortus("Se requiere 'topico' y 'mensaje' (objeto con id, ts, origen, tipo, datos).")
    mensaje.setdefault("origen", "controlador")
    mensaje.setdefault("id", mqtt_bus.sobre(mensaje.get("tipo", ""))["id"])
    return ok(operacion.procesar_mensaje(topico, mensaje))


@bp.get("/publicados")
@token_interno
def publicados():
    """Últimos mensajes publicados por el servidor (depuración sin Mosquitto)."""
    return ok([{"topico": t, "mensaje": m} for t, m in mqtt_bus.PUBLICADOS[-100:]])
