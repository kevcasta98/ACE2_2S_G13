# -*- coding: utf-8 -*-
from flask import Blueprint

from auth import sesion
from auth.permisos import matriz_para
from models import constantes as C
from routes.util import entrada, ok

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.post("/login")
def login():
    d = entrada()
    usuario = sesion.iniciar_sesion(d.get("usuario") or d.get("username"), d.get("password"))
    return ok(usuario)


@bp.post("/logout")
def logout():
    sesion.cerrar_sesion()
    return ok()


@bp.get("/yo")
@sesion.login_requerido
def yo():
    """Usuario en sesión, sus pestañas y sus permisos (para mostrar nombre y rol permanentemente)."""
    u = sesion.usuario_actual()
    return ok({**sesion.publico(u), "pestanas": C.PESTANAS[u["rol"]], "permisos": matriz_para(u["rol"])})
