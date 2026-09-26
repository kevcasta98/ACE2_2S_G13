# -*- coding: utf-8 -*-
"""
Fábrica de la aplicación Flask de PORTUS Fase 2 (backend).

    from app import create_app
    app = create_app()

Registra la API JSON bajo /api, el manejo de errores explícitos, la conexión
MQTT y las tareas periódicas. Las páginas HTML del Compañero 2 pueden
registrarse como otro Blueprint en esta misma app (ver docs/INTEGRACION.md).
"""
import logging
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from config import Config
from models import db
from models import semilla
from models.errores import ErrorPortus
from services import citas, mqtt_bus, operacion, tareas


def create_app(config=None, iniciar_servicios=True):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config:
        app.config.update(config)
    app.json.ensure_ascii = False  # tildes legibles en las respuestas JSON

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    db.configurar(app.config["DB_PATH"])
    os.makedirs(os.path.dirname(os.path.abspath(app.config["DB_PATH"])), exist_ok=True)
    semilla.crear_esquema(app.config["SCHEMA_PATH"])
    semilla.cargar_base()
    db.guardar_estado("servidor_iniciado", db.ahora())

    h, m = app.config["AGENDA_APERTURA"].split(":")
    h2, m2 = app.config["AGENDA_CIERRE"].split(":")
    citas.configurar_horario(int(h) * 60 + int(m), int(h2) * 60 + int(m2))

    from routes import auth, bot, catalogos, documental, gestion, interno
    from routes import operacion as rutas_operacion
    for modulo in (auth, catalogos, documental, rutas_operacion, gestion, bot, interno):
        app.register_blueprint(modulo.bp)

    @app.errorhandler(ErrorPortus)
    def error_portus(e):
        return jsonify({"ok": False, "error": e.mensaje, "codigo": e.codigo}), e.status

    @app.errorhandler(HTTPException)
    def error_http(e):
        return jsonify({"ok": False, "error": e.description, "codigo": e.name}), e.code

    @app.errorhandler(Exception)
    def error_general(e):
        app.logger.exception("Error no controlado")
        return jsonify({"ok": False, "error": f"Error interno del servidor: {e}"}), 500

    @app.teardown_appcontext
    def _cerrar(_exc):
        pass  # las conexiones son por hilo y se reutilizan

    @app.get("/api/salud")
    def salud():
        return jsonify({"ok": True, "servicio": "portus-backend", "db": app.config["DB_PATH"]})

    if iniciar_servicios:
        if app.config["MQTT_HABILITADO"]:
            mqtt_bus.iniciar(app.config["MQTT_HOST"], app.config["MQTT_PORT"], operacion.procesar_mensaje)
        if app.config["TAREAS_PERIODICAS"]:
            tareas.iniciar()
    return app
