# -*- coding: utf-8 -*-
"""Configuración por variables de entorno (valores por defecto aptos para desarrollo)."""
import os
from datetime import timedelta
from pathlib import Path

DIR_SERVER = Path(__file__).resolve().parent      # F2/server
DIR_F2 = DIR_SERVER.parent                        # F2
DIR_DATABASE = DIR_F2 / "database"


class Config:
    SECRET_KEY = os.environ.get("PORTUS_SECRET_KEY", "dev-portus-cambiar-en-la-raspberry")
    DB_PATH = os.environ.get("PORTUS_DB", str(DIR_DATABASE / "portus.db"))
    SCHEMA_PATH = str(DIR_DATABASE / "schema.sql")

    # Token compartido con el bot, el puente y el simulador (encabezado X-Portus-Token)
    TOKEN_INTERNO = os.environ.get("PORTUS_TOKEN_INTERNO", "portus-interno-dev")

    MQTT_HABILITADO = os.environ.get("PORTUS_MQTT", "1") == "1"
    MQTT_HOST = os.environ.get("PORTUS_MQTT_HOST", "localhost")
    MQTT_PORT = int(os.environ.get("PORTUS_MQTT_PORT", "1883"))

    TAREAS_PERIODICAS = os.environ.get("PORTUS_TAREAS", "1") == "1"

    # Horario de la agenda de citas (HH:MM). Por defecto todo el día para facilitar la demo.
    AGENDA_APERTURA = os.environ.get("PORTUS_AGENDA_APERTURA", "00:00")
    AGENDA_CIERRE = os.environ.get("PORTUS_AGENDA_CIERRE", "24:00")

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
