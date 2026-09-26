# -*- coding: utf-8 -*-
"""Utilidades comunes de las rutas. Toda respuesta es JSON:
    éxito: {"ok": true,  "datos": ...}
    error: {"ok": false, "error": "mensaje explícito", "codigo": ...}   (HTTP 400/401/403/404/409)"""
import hmac
from functools import wraps

from flask import current_app, jsonify, request

from models.errores import ErrorPermiso


def entrada():
    """Cuerpo de la petición: JSON o formulario."""
    datos = request.get_json(silent=True)
    if datos is None:
        datos = request.form.to_dict() if request.form else {}
    return datos


def ok(datos=None, status=200, **extra):
    return jsonify({"ok": True, "datos": datos, **extra}), status


def arg(nombre, defecto=None):
    v = request.args.get(nombre)
    return defecto if v in (None, "") else v


def token_interno(f):
    """Protege los endpoints que usan el bot, el puente y el simulador (no usan sesión web).
    Deben enviar el encabezado:  X-Portus-Token: <PORTUS_TOKEN_INTERNO>"""
    @wraps(f)
    def envoltura(*args, **kwargs):
        recibido = request.headers.get("X-Portus-Token", "")
        if not hmac.compare_digest(recibido, current_app.config["TOKEN_INTERNO"]):
            raise ErrorPermiso("Token interno inválido o ausente (encabezado X-Portus-Token).")
        return f(*args, **kwargs)
    return envoltura
