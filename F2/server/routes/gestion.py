# -*- coding: utf-8 -*-
"""Rutas del rol TERMINAL: Alarmas, Citas, Reportes y códigos de vinculación."""
from datetime import date

from flask import Blueprint, Response

from auth.permisos import requiere
from auth.sesion import usuario_actual
from models.errores import NoEncontrado
from models import db
from routes.util import arg, entrada, ok
from services import alarmas, citas, metricas, vinculacion

bp = Blueprint("gestion", __name__, url_prefix="/api")


# ----- Alarmas -----
@bp.get("/alarmas")
@requiere("VER_ALARMAS")
def listar_alarmas():
    """?estado=activas|historicas  ?severidad=CRITICA|ALTA|MEDIA|BAJA"""
    return ok(alarmas.listar(arg("estado", "activas"), arg("severidad")))


@bp.post("/alarmas/<int:aid>/reconocer")
@requiere("RECONOCER_ALARMAS")
def reconocer(aid):
    return ok(alarmas.reconocer(aid, usuario_actual()["id"], entrada().get("comentario")))


@bp.post("/alarmas/reconocer-todas")
@requiere("RECONOCER_ALARMAS")
def reconocer_todas():
    """Solo BAJA y MEDIA. Las CRÍTICAS y ALTAS se reconocen una por una."""
    return ok({"reconocidas": alarmas.reconocer_todas(usuario_actual()["id"], entrada().get("comentario"))})


# ----- Citas -----
@bp.get("/citas/agenda")
@requiere("VER_AGENDA_CITAS")
def agenda():
    """?fecha=2026-09-26 (hoy por defecto). Franjas con capacidad, asignadas y citas + % cumplimiento."""
    return ok(citas.agenda(arg("fecha", date.today().isoformat())))


@bp.get("/citas/franjas-disponibles")
@requiere("GESTIONAR_CITAS")
def franjas_disponibles():
    return ok(citas.franjas_disponibles(int(arg("cantidad", 12))))


@bp.post("/citas/<int:cid>/cancelar")
@requiere("GESTIONAR_CITAS")
def cancelar_cita(cid):
    return ok(citas.cancelar(cid, usuario_actual()["id"], entrada().get("motivo")))


@bp.post("/citas/<int:cid>/reprogramar")
@requiere("GESTIONAR_CITAS")
def reprogramar_cita(cid):
    return ok(citas.reprogramar(cid, int(entrada().get("franja_id")), usuario_actual()["id"]))


@bp.post("/franjas/<int:fid>/bloquear")
@requiere("GESTIONAR_CITAS")
def bloquear_franja(fid):
    return ok(citas.bloquear_franja(fid, True))


@bp.post("/franjas/<int:fid>/desbloquear")
@requiere("GESTIONAR_CITAS")
def desbloquear_franja(fid):
    return ok(citas.bloquear_franja(fid, False))


# ----- Reportes -----
@bp.post("/reportes")
@requiere("GENERAR_REPORTE")
def generar_reporte():
    """{"desde": "2026-09-26 08:00", "hasta": "2026-09-26 12:00", "etiqueta": "corrida de evaluación"}"""
    d = entrada()
    return ok(metricas.generar_reporte(d.get("desde") or date.today().isoformat(),
                                       d.get("hasta") or date.today().isoformat(),
                                       d.get("etiqueta"), usuario_actual()["id"]), 201)


@bp.get("/reportes")
@requiere("GENERAR_REPORTE")
def listar_reportes():
    return ok(db.todos("SELECT id, etiqueta, desde, hasta, generado_en FROM reportes ORDER BY id DESC"))


@bp.get("/reportes/<int:rid>/exportar.csv")
@requiere("GENERAR_REPORTE")
def exportar_reporte(rid):
    contenido = metricas.exportar_csv(rid)
    if contenido is None:
        raise NoEncontrado("El reporte no existe.")
    return Response(contenido, mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=reporte_corrida_{rid}.csv"})


# ----- Vinculación de transportistas -----
@bp.post("/transportistas/<ref>/codigo-vinculacion")
@requiere("GENERAR_CODIGO_VINCULACION")
def codigo_vinculacion(ref):
    """<ref> = id o código (TRANS-A). Devuelve un código de 6 caracteres válido 60 minutos."""
    return ok(vinculacion.generar_codigo(ref, usuario_actual()["id"]), 201)
