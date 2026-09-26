# -*- coding: utf-8 -*-
from flask import Blueprint, g

from auth.permisos import MATRIZ, requiere
from auth.sesion import login_requerido, usuario_actual
from models import constantes as C
from models import db
from routes.util import arg, ok
from services import patio

bp = Blueprint("catalogos", __name__, url_prefix="/api")


@bp.get("/catalogos/transportistas")
@login_requerido
def transportistas():
    """Para el selector 'Transportista asignado' del formulario de manifiesto."""
    return ok(db.todos("""SELECT id, codigo, nombre, (chat_id IS NOT NULL) AS vinculado
                          FROM transportistas ORDER BY codigo"""))


@bp.get("/catalogos/contenedores")
@login_requerido
def catalogo_contenedores():
    """Catálogo de contenedores de la maqueta (código y ubicación, sin datos de carga)."""
    u = usuario_actual()
    sql = "SELECT codigo, ubicacion, naviera_id FROM contenedores"
    if u["rol"] == C.ROL_NAVIERA:
        return ok(db.todos(sql + " WHERE naviera_id IS NULL OR naviera_id = ? ORDER BY codigo", (u["naviera_id"],)))
    return ok(db.todos(sql + " ORDER BY codigo"))


@bp.get("/catalogos/constantes")
def constantes():
    """Todos los nombres oficiales (estados, causas, alarmas, comandos, tópicos) para el equipo."""
    return ok({
        "roles": C.ROLES, "pestanas": C.PESTANAS, "estados_turno": C.ESTADOS_TURNO,
        "transiciones_turno": C.TRANSICIONES_TURNO, "estados_documentales": C.ESTADOS_DOCUMENTALES,
        "estados_operativos": C.ESTADOS_OPERATIVOS, "canales": C.CANALES, "regimenes": C.REGIMENES,
        "tipos_operacion": C.TIPOS_OPERACION, "causas_retencion": C.CAUSAS_RETENCION,
        "resoluciones": C.RESOLUCIONES,
        "alarmas": {k: {"descripcion": v[0], "severidad": v[1]} for k, v in C.ALARMAS.items()},
        "comandos": C.COMANDOS, "estados_cita": C.ESTADOS_CITA, "notificaciones": C.NOTIFICACIONES,
        "matriz_permisos": {k: dict(zip(C.ROLES, v)) for k, v in MATRIZ.items()},
        "topicos": {k: v for k, v in vars(C).items() if k.startswith("TOPICO_")},
    })


@bp.get("/contenedores")
@requiere("CONSULTAR_CONTENEDOR")
def contenedores():
    """Mis contenedores (NAVIERA, solo propios), Patio (TERMINAL), Consulta de carga (AUTORIDAD), AGENTE.
    Filtros: ?q=CONT-00  ?naviera=NAVIERA1  ?autorizacion=LEVANTE_OTORGADO  ?ubicacion=PATIO"""
    u = usuario_actual()
    filas = patio.inventario(naviera_id=u["naviera_id"] if g.alcance == "PROPIOS" else None)
    if g.alcance == "PROPIOS":
        filas = [f for f in filas if f["naviera"] == u["naviera_codigo"]]
    q, nav, aut, ubi = arg("q"), arg("naviera"), arg("autorizacion"), arg("ubicacion")
    if q:
        filas = [f for f in filas if q.upper() in f["contenedor"]]
    if nav:
        filas = [f for f in filas if f["naviera"] == nav.upper()]
    if aut:
        filas = [f for f in filas if f["autorizacion"] == aut.upper()]
    if ubi:
        filas = [f for f in filas if f["ubicacion"] == ubi.upper()]
    return ok(filas)
