# -*- coding: utf-8 -*-
"""
Parqueo de retención: 3 plazas lógicas (sección 8.1).
  * Al retener se asigna la plaza libre de MENOR número y se envía AgujaParqueo.
  * Al resolver se envía AgujaLiberar; la plaza queda libre cuando el controlador
    ACEPTA ese comando. Si lo rechaza, la plaza sigue ocupada con la retención
    resuelta y el botón "Liberar parqueo" del sinóptico vuelve a enviarlo.
"""
from models import db
from models import constantes as C
from models.errores import Conflicto, NoEncontrado
from services import alarmas, comandos, mqtt_bus


def plazas():
    filas = db.todos("""
        SELECT p.numero, p.turno_id, p.retencion_id, p.ocupada_desde, p.liberacion_pendiente,
               t.codigo AS turno, v.placa AS vehiculo, r.codigo AS retencion, r.causa, r.estado AS estado_retencion,
               CAST((julianday('now','localtime') - julianday(p.ocupada_desde)) * 86400 AS INTEGER) AS segundos_retenido
        FROM plazas_parqueo p
        LEFT JOIN turnos t ON t.id = p.turno_id
        LEFT JOIN vehiculos v ON v.id = t.vehiculo_id
        LEFT JOIN retenciones r ON r.id = p.retencion_id
        ORDER BY p.numero""")
    for f in filas:
        f["estado"] = "OCUPADA" if f["turno_id"] else "LIBRE"
        if not f["turno_id"]:
            f["segundos_retenido"] = None
    return filas


def libres():
    return db.valor("SELECT COUNT(*) FROM plazas_parqueo WHERE turno_id IS NULL")


def lleno():
    return libres() == 0


def ocupar(turno_id, retencion_id):
    """Asigna la plaza libre de menor número. Devuelve el número o None si está lleno (genera AL11)."""
    with db.transaccion():
        numero = db.valor("SELECT MIN(numero) FROM plazas_parqueo WHERE turno_id IS NULL")
        if numero is None:
            alarmas.generar("AL11", clave="parqueo", turno_id=turno_id)
            return None
        db.actualizar("plazas_parqueo", {"turno_id": turno_id, "retencion_id": retencion_id,
                                         "ocupada_desde": db.ahora(), "liberacion_pendiente": 0},
                      "numero = ?", (numero,))
        if lleno():
            alarmas.generar("AL11", clave="parqueo", turno_id=turno_id)
        comandos.emitir("AgujaParqueo", {"plaza": numero}, turno_id=turno_id)
        mqtt_bus.publicar(C.TOPICO_SRV_PARQUEO, "PARQUEO_ACTUALIZADO", {"plazas": plazas()})
    return numero


def plaza_de_turno(turno_id):
    return db.valor("SELECT numero FROM plazas_parqueo WHERE turno_id = ?", (turno_id,))


def solicitar_liberacion(numero, usuario_id=None):
    """Envía AgujaLiberar para la plaza. Solo si está ocupada y su retención ya fue resuelta."""
    with db.transaccion():
        p = db.uno("""SELECT p.*, r.estado AS estado_retencion FROM plazas_parqueo p
                      LEFT JOIN retenciones r ON r.id = p.retencion_id WHERE p.numero = ?""", (numero,))
        if not p:
            raise NoEncontrado("La plaza no existe.")
        if not p["turno_id"]:
            raise Conflicto("La plaza está libre.")
        if p["estado_retencion"] != C.RETENCION_RESUELTA:
            raise Conflicto("La retención de esta plaza aún no ha sido resuelta.")
        db.actualizar("plazas_parqueo", {"liberacion_pendiente": 1}, "numero = ?", (numero,))
        return comandos.emitir("AgujaLiberar", {"plaza": numero}, usuario_id=usuario_id, turno_id=p["turno_id"])


def confirmar_liberacion(numero):
    """El controlador aceptó AgujaLiberar: la plaza queda libre."""
    with db.transaccion():
        db.actualizar("plazas_parqueo", {"turno_id": None, "retencion_id": None, "ocupada_desde": None,
                                         "liberacion_pendiente": 0}, "numero = ?", (numero,))
        alarmas.cesar_condicion("AL11", "parqueo")
        mqtt_bus.publicar(C.TOPICO_SRV_PARQUEO, "PARQUEO_ACTUALIZADO", {"plazas": plazas()})
