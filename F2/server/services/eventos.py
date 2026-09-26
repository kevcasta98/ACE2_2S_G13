# -*- coding: utf-8 -*-
"""Registro de eventos: alimenta la línea de tiempo del turno (4.2.1)."""
import sqlite3

from models import db


def registrar(tipo, descripcion, origen="servidor", turno_id=None, datos=None, usuario_id=None,
              mensaje_id=None, topico=None, seq=None, ts=None):
    """Guarda un evento. Devuelve su id, o None si el mensaje_id ya existía (duplicado)."""
    try:
        return db.insertar("eventos", {
            "mensaje_id": mensaje_id, "turno_id": turno_id, "origen": origen, "tipo": tipo,
            "descripcion": descripcion, "datos_json": db.a_json(datos), "usuario_id": usuario_id,
            "topico": topico, "seq": seq, "creado_en": ts or db.ahora(),
        })
    except sqlite3.IntegrityError:
        return None


def linea_tiempo(turno_id):
    filas = db.todos("""
        SELECT e.id, e.creado_en AS marca_tiempo, e.origen, e.tipo, e.descripcion, e.datos_json,
               u.username AS usuario
        FROM eventos e LEFT JOIN usuarios u ON u.id = e.usuario_id
        WHERE e.turno_id = ? ORDER BY e.creado_en, e.id""", (turno_id,))
    for f in filas:
        f["valores"] = db.de_json(f.pop("datos_json"))
    return filas
