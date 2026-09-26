# -*- coding: utf-8 -*-
"""Rutas de la cadena documental: NAVIERA (Manifiestos), AGENTE (Declaraciones, Seguimiento),
AUTORIDAD (Solicitudes de levante)."""
from flask import Blueprint, g

from auth.permisos import requiere
from auth.sesion import usuario_actual
from models import constantes as C
from routes.util import arg, entrada, ok
from services import cadena_documental as doc

bp = Blueprint("documental", __name__, url_prefix="/api")


# ----- Manifiestos -----
@bp.get("/manifiestos")
@requiere("VER_MANIFIESTO")
def listar_manifiestos():
    return ok(doc.listar(usuario_actual(), g.alcance, estado=arg("estado"), contenedor=arg("contenedor")))


@bp.post("/manifiestos")
@requiere("CREAR_MANIFIESTO")
def crear_manifiesto():
    return ok(doc.crear_manifiesto(usuario_actual(), entrada()), 201)


@bp.get("/manifiestos/<int:mid>")
@requiere("VER_MANIFIESTO")
def ver_manifiesto(mid):
    return ok(doc.detalle(mid, usuario_actual(), g.alcance))


@bp.post("/manifiestos/<int:mid>/anular")
@requiere("ANULAR_MANIFIESTO")
def anular_manifiesto(mid):
    return ok(doc.anular_manifiesto(usuario_actual(), mid, entrada().get("motivo")))


# ----- AGENTE -----
@bp.get("/declaraciones/pendientes")
@requiere("PRESENTAR_DECLARACION")
def declaraciones_pendientes():
    return ok(doc.pendientes_de_levante())


@bp.post("/manifiestos/<int:mid>/declaracion")
@requiere("PRESENTAR_DECLARACION")
def presentar_declaracion(mid):
    return ok(doc.presentar_declaracion(usuario_actual(), mid, entrada()), 201)


@bp.post("/manifiestos/<int:mid>/solicitar-levante")
@requiere("PRESENTAR_DECLARACION")
def solicitar_levante(mid):
    return ok(doc.solicitar_levante(usuario_actual(), mid), 201)


@bp.post("/manifiestos/<int:mid>/observaciones")
@requiere("PRESENTAR_DECLARACION")
def agregar_observacion(mid):
    return ok(doc.agregar_observacion(usuario_actual(), mid, entrada().get("texto")), 201)


@bp.get("/declaraciones/seguimiento")
@requiere("VER_SEGUIMIENTO_AGENTE")
def seguimiento():
    return ok(doc.seguimiento(usuario_actual(), estado=arg("estado"), numero=arg("numero")))


# ----- AUTORIDAD -----
@bp.get("/levantes")
@requiere("OTORGAR_RETENER_LEVANTE")
def solicitudes_levante():
    """?estado=PENDIENTE (defecto) | RETENIDO | OTORGADO | TODAS"""
    return ok(doc.solicitudes((arg("estado") or C.LEVANTE_PENDIENTE).upper()))


@bp.get("/levantes/<int:sid>")
@requiere("OTORGAR_RETENER_LEVANTE")
def ver_solicitud(sid):
    """Botón 'Ver declaración': incluye la declaración de mercancías del agente."""
    return ok(doc.obtener_solicitud(sid))


@bp.post("/levantes/<int:sid>/otorgar")
@requiere("OTORGAR_RETENER_LEVANTE")
def otorgar_levante(sid):
    return ok(doc.otorgar_levante(usuario_actual(), sid, entrada().get("canal")))


@bp.post("/levantes/<int:sid>/retener")
@requiere("OTORGAR_RETENER_LEVANTE")
def retener_levante(sid):
    return ok(doc.retener_levante(usuario_actual(), sid, entrada().get("motivo")))
