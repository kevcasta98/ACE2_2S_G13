# -*- coding: utf-8 -*-
"""
API para el bot del transportista (Compañero 4). No usa sesión web: cada
petición lleva el encabezado X-Portus-Token y el chat_id del usuario de
mensajería. El servidor resuelve chat_id -> transportista y SOLO devuelve
carga de ese transportista (regla 6.3).

Si el chat_id no está vinculado, todas las rutas (salvo /vincular) responden
403 con codigo "NO_VINCULADO": el bot debe responder siempre el mismo mensaje
de solicitud de vinculación (6.1.5).
"""
from flask import Blueprint

from models import constantes as C
from models import db
from models.errores import ErrorPermiso, NoEncontrado
from routes.util import arg, entrada, ok, token_interno
from services import citas, notificaciones, patio, turnos, vinculacion

bp = Blueprint("bot", __name__, url_prefix="/api/bot")

MENSAJE_NO_VINCULADO = ("Su cuenta no está vinculada. Solicite un código al operador de la terminal "
                        "y escriba /vincular CODIGO")


def _transportista(chat_id):
    t = vinculacion.transportista_por_chat(chat_id) if chat_id else None
    if not t:
        raise ErrorPermiso(MENSAJE_NO_VINCULADO, codigo="NO_VINCULADO")
    return t


@bp.post("/vincular")
@token_interno
def vincular():
    """{"chat_id": "123456", "codigo": "AB12CD"}"""
    d = entrada()
    return ok(vinculacion.vincular(d.get("chat_id"), d.get("codigo")))


@bp.get("/yo")
@token_interno
def yo():
    return ok(_transportista(arg("chat_id")))


@bp.get("/contenedores-para-cita")
@token_interno
def contenedores_para_cita():
    """/cita paso 1: contenedores con levante otorgado y sin cita."""
    t = _transportista(arg("chat_id"))
    return ok(citas.contenedores_para_cita(t["id"]))


@bp.get("/franjas-disponibles")
@token_interno
def franjas_disponibles():
    """/cita paso 2: próximas franjas con capacidad (hora de inicio y fin)."""
    _transportista(arg("chat_id"))
    return ok(citas.franjas_disponibles(int(arg("cantidad", C.FRANJAS_A_OFRECER))))


@bp.post("/citas")
@token_interno
def solicitar_cita():
    """/cita paso 3: {"chat_id": "...", "contenedor": "CONT-001", "franja_id": 42}"""
    d = entrada()
    t = _transportista(d.get("chat_id"))
    return ok(citas.solicitar(t["id"], d.get("contenedor"), int(d.get("franja_id"))), 201)


@bp.get("/citas")
@token_interno
def mis_citas():
    """/miscitas"""
    t = _transportista(arg("chat_id"))
    return ok(citas.de_transportista(t["id"]))


@bp.get("/contenedores/<codigo>")
@token_interno
def estado_contenedor(codigo):
    """/estado CONTENEDOR. Si no es suyo: 404 'No tiene carga asociada a ese identificador.'"""
    t = _transportista(arg("chat_id"))
    codigo = codigo.strip().upper()
    propio = db.valor("SELECT 1 FROM manifiestos WHERE contenedor = ? AND transportista_id = ? LIMIT 1",
                      (codigo, t["id"]))
    if not propio:
        raise NoEncontrado("No tiene carga asociada a ese identificador.")
    info = patio.inventario(contenedor=codigo)
    if not info:
        raise NoEncontrado("No tiene carga asociada a ese identificador.")
    c = info[0]
    turno = db.uno("""SELECT codigo, estado, estacion FROM turnos WHERE contenedor = ? AND transportista_id = ?
                      ORDER BY id DESC LIMIT 1""", (codigo, t["id"]))
    return ok({"contenedor": codigo, "estado": turno["estado"] if turno else c["estado_operativo"],
               "ubicacion": c["ubicacion"],
               "posicion": f"P{c['posicion']}-{c['nivel']}" if c["ubicacion"] == "PATIO" else None,
               "permanencia": c["permanencia"], "autorizacion": c["autorizacion"], "canal": c["canal"]})


@bp.get("/turnos")
@token_interno
def mis_turnos():
    """/misturnos: turnos activos con vehículo, contenedor, tipo, estado y estación."""
    t = _transportista(arg("chat_id"))
    return ok([{"turno": x["codigo"], "vehiculo": x["vehiculo"], "contenedor": x["contenedor"], "tipo": x["tipo"],
                "estado": x["estado"], "estacion": x["estacion"]}
               for x in turnos.listar(seccion="activos", transportista_id=t["id"])])


# ----- Bandeja de notificaciones -----
@bp.get("/notificaciones/pendientes")
@token_interno
def notificaciones_pendientes():
    """Notificaciones por enviar con su chat_id destino. Las de transportistas sin chat_id quedan
    pendientes hasta que se vinculen."""
    return ok(notificaciones.pendientes(int(arg("limite", 50))))


@bp.post("/notificaciones/<int:nid>/enviada")
@token_interno
def notificacion_enviada(nid):
    notificaciones.marcar_enviada(nid)
    return ok()


@bp.post("/notificaciones/<int:nid>/error")
@token_interno
def notificacion_error(nid):
    notificaciones.marcar_error(nid, entrada().get("error"))
    return ok()
