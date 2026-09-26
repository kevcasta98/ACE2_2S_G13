# -*- coding: utf-8 -*-
"""Rutas del rol TERMINAL: Operación (sinóptico + comandos), Turnos, Retenciones, Patio, Grúa.
También la bandeja de retenciones aduaneras de la AUTORIDAD."""
import csv
import io

from flask import Blueprint, Response

from auth.permisos import requiere, verificar
from auth.sesion import login_requerido, usuario_actual
from models import constantes as C
from models import db
from models.errores import ErrorPortus, NoEncontrado
from routes.util import arg, entrada, ok
from services import comandos, eventos, parqueo, patio, retenciones, turnos

bp = Blueprint("operacion", __name__, url_prefix="/api")


# ---------------------------------------------------------------------------
# Sinóptico: SOLO la carga inicial. Después la página se actualiza por MQTT.
# ---------------------------------------------------------------------------
@bp.get("/sistema/estado")
@requiere("VER_SINOPTICO")
def estado_sistema():
    return ok({
        "enlace": db.leer_estado("enlace", C.ENLACE_DESCONECTADO),
        "ultimo_latido": db.leer_estado("ultimo_latido"),
        "modo": db.leer_estado("modo", C.MODO_NORMAL),
        "aguja": db.leer_estado("aguja"),
        "grua": db.de_json(db.leer_estado("grua")),
        "ultimo_estado_controlador": db.de_json(db.leer_estado("ultimo_estado")),
        "politica_patio": patio.politica(),
        "parqueo": parqueo.plazas(),
        "patio": patio.estado_posiciones(),
        "turnos_activos": turnos.listar(seccion="activos"),
        "alarmas_activas": db.valor("SELECT COUNT(*) FROM alarmas WHERE reconocida = 0"),
        "mqtt": {"topicos_controlador": "portus/evt/#", "topicos_servidor": "portus/srv/#",
                 "respuestas_comandos": C.TOPICO_SRV_COMANDO},
    })


@bp.post("/sistema/politica-patio")
@requiere("EMITIR_COMANDOS")
def politica_patio():
    patio.cambiar_politica(entrada().get("politica"))
    return ok({"politica_patio": patio.politica()})


# ---------------------------------------------------------------------------
# Comandos remotos
# ---------------------------------------------------------------------------
@bp.post("/comandos")
@requiere("EMITIR_COMANDOS")
def emitir_comando():
    """{"comando": "GruaSuspender", "parametros": {}}. Responde 202: el resultado (aceptado/rechazado)
    llega por MQTT en portus/srv/comando, o consultando GET /api/comandos/<id>."""
    d = entrada()
    return ok(comandos.emitir(d.get("comando"), d.get("parametros"), usuario_id=usuario_actual()["id"]), 202)


@bp.get("/comandos")
@requiere("EMITIR_COMANDOS")
def listar_comandos():
    return ok(comandos.listar(int(arg("limite", 50))))


@bp.get("/comandos/<int:cid>")
@requiere("EMITIR_COMANDOS")
def ver_comando(cid):
    c = comandos.obtener(cid)
    if not c:
        raise NoEncontrado("El comando no existe.")
    return ok(c)


# ---------------------------------------------------------------------------
# Turnos
# ---------------------------------------------------------------------------
@bp.get("/turnos")
@requiere("GESTIONAR_TURNOS")
def listar_turnos():
    """?seccion=activos|historicos  ?estado=EnRuta  ?tipo=DEPOSITO|RETIRO  ?desde=2026-09-26  ?hasta=...  ?q=CONT-001"""
    return ok(turnos.listar(seccion=arg("seccion"), estado=arg("estado"), tipo=arg("tipo"),
                            desde=arg("desde"), hasta=arg("hasta"), q=arg("q")))


@bp.get("/turnos/<int:tid>")
@requiere("GESTIONAR_TURNOS")
def ver_turno(tid):
    t = turnos.obtener_o_error(tid)
    t["retenciones"] = retenciones.listar(turno_id=tid)
    t["pesajes"] = db.todos("SELECT * FROM pesajes WHERE turno_id = ? ORDER BY id", (tid,))
    return ok(t)


@bp.get("/turnos/<int:tid>/linea-tiempo")
@requiere("GESTIONAR_TURNOS")
def linea_tiempo(tid):
    t = turnos.obtener_o_error(tid)
    return ok({"turno": t, "eventos": eventos.linea_tiempo(tid)})


@bp.post("/turnos/<int:tid>/retener")
@requiere("GESTIONAR_TURNOS")
def retener_turno(tid):
    """Retención manual operativa RT06 con observación opcional."""
    u = usuario_actual()
    return ok(retenciones.crear(tid, "RT06", origen=C.ORIGEN_USUARIO, usuario_id=u["id"],
                                observacion=entrada().get("observacion")), 201)


@bp.post("/turnos/<int:tid>/retencion-documental")
@requiere("ORDENAR_RETENCION_DOCUMENTAL")
def retencion_documental(tid):
    """RT05: la AUTORIDAD ordena una retención documental sobre un turno en curso."""
    u = usuario_actual()
    d = entrada()
    if not (d.get("motivo") or "").strip():
        raise ErrorPortus("Debe indicar el motivo de la retención documental.")
    return ok(retenciones.crear(tid, "RT05", origen=C.ORIGEN_USUARIO, usuario_id=u["id"],
                                observacion=d.get("motivo")), 201)


@bp.post("/turnos/<int:tid>/anular")
@requiere("GESTIONAR_TURNOS")
def anular_turno(tid):
    u = usuario_actual()
    return ok(turnos.anular(tid, entrada().get("motivo"), origen=C.ORIGEN_USUARIO, usuario_id=u["id"]))


# ---------------------------------------------------------------------------
# Retenciones (TERMINAL ve todas; AUTORIDAD solo RT03 y RT05)
# ---------------------------------------------------------------------------
@bp.get("/retenciones")
@requiere("VER_RETENCIONES")
def listar_retenciones():
    """?estado=ABIERTA|RESUELTA  ?causa=RT01"""
    u = usuario_actual()
    return ok(retenciones.listar(estado=arg("estado"), causa=arg("causa"),
                                 solo_aduaneras=u["rol"] == C.ROL_AUTORIDAD))


@bp.get("/retenciones/<int:rid>")
@requiere("VER_RETENCIONES")
def ver_retencion(rid):
    r = retenciones.obtener(rid)
    if not r or (usuario_actual()["rol"] == C.ROL_AUTORIDAD and not r["aduanera"]):
        raise NoEncontrado("La retención no existe.")
    return ok(r)


def _resolver(rid, resolucion):
    u = usuario_actual()
    r = retenciones.obtener(rid)
    if not r:
        raise NoEncontrado("La retención no existe.")
    verificar("RESOLVER_RETENCION_ADUANERA" if r["aduanera"] else "RESOLVER_RETENCION_OPERATIVA", u)
    if resolucion == C.RES_CORREGIR:
        verificar("CORREGIR_PESO", u)
    d = entrada()
    return ok(retenciones.resolver(rid, resolucion, u, motivo=d.get("motivo"), observacion=d.get("observacion")))


@bp.post("/retenciones/<int:rid>/aclarar")
@login_requerido
def aclarar(rid):
    return _resolver(rid, C.RES_ACLARAR)


@bp.post("/retenciones/<int:rid>/corregir")
@login_requerido
def corregir(rid):
    return _resolver(rid, C.RES_CORREGIR)


@bp.post("/retenciones/<int:rid>/rechazar")
@login_requerido
def rechazar(rid):
    return _resolver(rid, C.RES_RECHAZAR)


# ---------------------------------------------------------------------------
# Parqueo
# ---------------------------------------------------------------------------
@bp.get("/parqueo")
@requiere("VER_SINOPTICO")
def ver_parqueo():
    return ok(parqueo.plazas())


@bp.post("/parqueo/<int:plaza>/liberar")
@requiere("EMITIR_COMANDOS")
def liberar_parqueo(plaza):
    """Botón 'Liberar parqueo': solo si la plaza está ocupada y su retención fue resuelta."""
    return ok(parqueo.solicitar_liberacion(plaza, usuario_actual()["id"]), 202)


# ---------------------------------------------------------------------------
# Patio
# ---------------------------------------------------------------------------
@bp.get("/patio")
@requiere("VER_SINOPTICO")
def ver_patio():
    """Posiciones con su estado por nivel + inventario (ordenado por permanencia descendente)."""
    inv = [f for f in patio.inventario() if f["ubicacion"] == "PATIO"]
    return ok({"posiciones": patio.estado_posiciones(), "inventario": inv})


@bp.post("/patio/<int:pos>/bloquear")
@requiere("EMITIR_COMANDOS")
def bloquear_posicion(pos):
    return ok(comandos.emitir("PosicionBloquear", {"posicion": pos, "motivo": entrada().get("motivo")},
                              usuario_id=usuario_actual()["id"]), 202)


@bp.post("/patio/<int:pos>/liberar")
@requiere("EMITIR_COMANDOS")
def liberar_posicion(pos):
    if not db.valor("SELECT bloqueada FROM posiciones_patio WHERE numero = ?", (pos,)):
        raise ErrorPortus("La posición no está bloqueada.")
    return ok(comandos.emitir("PosicionLiberar", {"posicion": pos}, usuario_id=usuario_actual()["id"]), 202)


# ---------------------------------------------------------------------------
# Grúa
# ---------------------------------------------------------------------------
def _ciclos(limite):
    limite = int(limite) if str(limite) in ("50", "100", "200") else 50
    return db.todos(f"""SELECT * FROM (SELECT * FROM ciclos_grua WHERE fin_en IS NOT NULL ORDER BY id DESC LIMIT {limite})
                        ORDER BY id""")


@bp.get("/grua")
@requiere("VER_SINOPTICO")
def ver_grua():
    """?limite=50|100|200. Estado, cola, ciclos (gráfica), promedio y fallas."""
    ciclos = _ciclos(arg("limite", 50))
    ok_ciclos = [c for c in ciclos if c["resultado"] == "OK"]
    con_duracion = [c["duracion_ms"] for c in ok_ciclos if c["duracion_ms"] is not None]
    return ok({
        "estado": db.de_json(db.leer_estado("grua")),
        "trabajos_pendientes": db.todos("""SELECT * FROM trabajos_grua WHERE estado IN ('ENVIADO','EN_CURSO')
                                           ORDER BY creado_en, orden"""),
        "ciclos": ciclos,
        "ciclos_completados": len(ok_ciclos),
        "tiempo_promedio_ciclo_ms": round(sum(con_duracion) / len(con_duracion)) if con_duracion else 0,
        "fallas": db.todos("SELECT * FROM fallas_grua ORDER BY id DESC LIMIT 100"),
    })


@bp.get("/grua/exportar.csv")
@requiere("VER_SINOPTICO")
def exportar_grua():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["id", "trabajo_id", "turno_id", "tipo", "contenedor", "origen", "destino", "inicio", "fin",
                "duracion_ms", "distancia_mm", "resultado"])
    for c in _ciclos(arg("limite", 50)):
        w.writerow([c["id"], c["trabajo_id"], c["turno_id"], c["tipo"], c["contenedor"], c["origen"], c["destino"],
                    c["inicio_en"], c["fin_en"], c["duracion_ms"], c["distancia_mm"], c["resultado"]])
    w.writerow([])
    w.writerow(["falla_id", "tipo", "trabajo_id", "turno_id", "detalle", "fecha"])
    for f in db.todos("SELECT * FROM fallas_grua ORDER BY id"):
        w.writerow([f["id"], f["tipo"], f["trabajo_id"], f["turno_id"], f["detalle"], f["creado_en"]])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=grua_historial.csv"})
