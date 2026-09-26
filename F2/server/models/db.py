# -*- coding: utf-8 -*-
"""
Acceso a SQLite compartido por las rutas HTTP, el hilo MQTT y las tareas
periódicas. Cada hilo tiene su propia conexión (sqlite3 no se comparte entre
hilos). Las operaciones de varios pasos usan `with transaccion():`.

Uso típico:
    from models import db
    fila = db.uno("SELECT * FROM turnos WHERE id = ?", (5,))
    with db.transaccion():
        db.ejecutar("UPDATE ...", (...))
        db.al_confirmar(lambda: print("se ejecuta después del COMMIT"))
"""
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime

_local = threading.local()
_ruta_db = None


def configurar(ruta):
    global _ruta_db
    _ruta_db = ruta


def ruta():
    return _ruta_db


def con():
    c = getattr(_local, "con", None)
    if c is None or getattr(_local, "ruta", None) != _ruta_db:
        c = sqlite3.connect(_ruta_db, timeout=15, isolation_level=None, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        c.execute("PRAGMA journal_mode = WAL")
        c.execute("PRAGMA busy_timeout = 15000")
        _local.con = c
        _local.ruta = _ruta_db
        _local.nivel = 0
        _local.pendientes = []
    return c


def cerrar():
    c = getattr(_local, "con", None)
    if c is not None:
        c.close()
        _local.con = None


@contextmanager
def transaccion():
    """Transacción anidable. Solo la más externa hace COMMIT/ROLLBACK."""
    c = con()
    if _local.nivel == 0:
        c.execute("BEGIN IMMEDIATE")
        _local.pendientes = []
    _local.nivel += 1
    try:
        yield c
    except BaseException:
        _local.nivel -= 1
        if _local.nivel == 0:
            c.execute("ROLLBACK")
            _local.pendientes = []
        raise
    _local.nivel -= 1
    if _local.nivel == 0:
        c.execute("COMMIT")
        pendientes, _local.pendientes = _local.pendientes, []
        for fn in pendientes:
            fn()


def al_confirmar(fn):
    """Ejecuta `fn` después del COMMIT (o de inmediato si no hay transacción).
    Se usa para publicar en MQTT solo lo que realmente quedó guardado."""
    con()
    if _local.nivel > 0:
        _local.pendientes.append(fn)
    else:
        fn()


def uno(sql, params=()):
    fila = con().execute(sql, params).fetchone()
    return dict(fila) if fila else None


def todos(sql, params=()):
    return [dict(f) for f in con().execute(sql, params).fetchall()]


def valor(sql, params=()):
    fila = con().execute(sql, params).fetchone()
    return fila[0] if fila else None


def ejecutar(sql, params=()):
    return con().execute(sql, params)


def insertar(tabla, datos):
    columnas = ", ".join(datos.keys())
    marcas = ", ".join("?" for _ in datos)
    cur = con().execute(f"INSERT INTO {tabla} ({columnas}) VALUES ({marcas})", tuple(datos.values()))
    return cur.lastrowid


def actualizar(tabla, datos, where, params=()):
    sets = ", ".join(f"{k} = ?" for k in datos)
    return con().execute(f"UPDATE {tabla} SET {sets} WHERE {where}", tuple(datos.values()) + tuple(params))


# ---------------------------------------------------------------------------
# Utilidades de fecha y JSON
# ---------------------------------------------------------------------------
FORMATO_FECHA = "%Y-%m-%d %H:%M:%S"


def ahora():
    return datetime.now().strftime(FORMATO_FECHA)


def a_fecha(texto):
    if texto is None or isinstance(texto, datetime):
        return texto
    texto = str(texto).replace("T", " ")
    for fmt in (FORMATO_FECHA, "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto[:26], fmt)
        except ValueError:
            continue
    raise ValueError(f"Fecha inválida: {texto}")


def texto_fecha(dt):
    return dt.strftime(FORMATO_FECHA) if dt else None


def a_json(obj):
    return json.dumps(obj, ensure_ascii=False, default=str) if obj is not None else None


def de_json(texto):
    return json.loads(texto) if texto else None


# ---------------------------------------------------------------------------
# estado_sistema (clave/valor)
# ---------------------------------------------------------------------------
def leer_estado(clave, defecto=None):
    v = valor("SELECT valor FROM estado_sistema WHERE clave = ?", (clave,))
    return defecto if v is None else v


def guardar_estado(clave, v):
    ejecutar("INSERT INTO estado_sistema (clave, valor, actualizado_en) VALUES (?, ?, ?) "
             "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor, actualizado_en = excluded.actualizado_en",
             (clave, None if v is None else str(v), ahora()))
