# -*- coding: utf-8 -*-
"""
Autenticación y sesión.
  * Contraseñas con hash (werkzeug: scrypt/pbkdf2), nunca en texto plano (2.2.2).
  * La sesión de Flask guarda solo el id; en cada petición se recarga el usuario
    desde la BD, así un usuario desactivado pierde acceso inmediatamente.
  * TRANSPORTISTA no tiene acceso web: el login lo rechaza con mensaje explícito.
"""
from functools import wraps

from flask import request, session
from werkzeug.security import check_password_hash, generate_password_hash

from models import db
from models.constantes import ROL_TRANSPORTISTA
from models.errores import ErrorPermiso, NoAutenticado

CAMPOS_PUBLICOS = ("id", "username", "nombre", "rol", "naviera_id", "transportista_id",
                   "naviera_codigo", "naviera_nombre", "transportista_codigo")


def hash_password(password):
    return generate_password_hash(password)


def _cargar(usuario_id):
    return db.uno("""
        SELECT u.*, n.codigo AS naviera_codigo, n.nombre AS naviera_nombre, t.codigo AS transportista_codigo
        FROM usuarios u
        LEFT JOIN navieras n ON n.id = u.naviera_id
        LEFT JOIN transportistas t ON t.id = u.transportista_id
        WHERE u.id = ? AND u.activo = 1""", (usuario_id,))


def publico(usuario):
    return {k: usuario.get(k) for k in CAMPOS_PUBLICOS}


def iniciar_sesion(username, password):
    fila = db.uno("SELECT * FROM usuarios WHERE username = ?", ((username or "").strip(),))
    if not fila or not fila["activo"] or not check_password_hash(fila["password_hash"], password or ""):
        raise NoAutenticado("Usuario o contraseña incorrectos.")
    if fila["rol"] == ROL_TRANSPORTISTA:
        raise ErrorPermiso("El rol TRANSPORTISTA no tiene acceso a la aplicación web. Use el canal de mensajería.")
    session.clear()
    session.permanent = True
    session["uid"] = fila["id"]
    db.ejecutar("UPDATE usuarios SET ultimo_acceso = ? WHERE id = ?", (db.ahora(), fila["id"]))
    return publico(_cargar(fila["id"]))


def cerrar_sesion():
    session.clear()


def usuario_actual(obligatorio=True):
    """Usuario en sesión (dict) o excepción 401."""
    cache = request.environ.get("portus.usuario")
    if cache:
        return cache
    uid = session.get("uid")
    usuario = _cargar(uid) if uid else None
    if usuario is None:
        session.clear()
        if obligatorio:
            raise NoAutenticado("Debe iniciar sesión.")
        return None
    request.environ["portus.usuario"] = usuario
    return usuario


def login_requerido(f):
    @wraps(f)
    def envoltura(*args, **kwargs):
        usuario_actual()
        return f(*args, **kwargs)
    return envoltura
