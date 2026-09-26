# -*- coding: utf-8 -*-
"""
Turnos y su máquina de estados (sección 7). Toda transición pasa por
`transicionar`, que valida contra TRANSICIONES_TURNO, registra el evento en la
línea de tiempo y publica el cambio en portus/srv/turno para el sinóptico.
"""
from models import db
from models import constantes as C
from models.errores import Conflicto, ErrorPortus, NoEncontrado
from services import eventos, mqtt_bus, notificaciones

_SELECT = """
    SELECT t.*, m.codigo AS manifiesto, m.canal, v.placa AS vehiculo, v.rfid_uid, v.tara_g,
           tr.codigo AS transportista, tr.nombre AS transportista_nombre, n.codigo AS naviera,
           c.codigo AS cita, CAST((julianday(COALESCE(t.cerrado_en, datetime('now','localtime'))) - julianday(t.creado_en)) * 86400 AS INTEGER) AS segundos_en_terminal
    FROM turnos t
    JOIN manifiestos m ON m.id = t.manifiesto_id
    JOIN vehiculos v ON v.id = t.vehiculo_id
    JOIN transportistas tr ON tr.id = t.transportista_id
    JOIN navieras n ON n.id = m.naviera_id
    LEFT JOIN citas c ON c.id = t.cita_id
"""


def duracion(segundos):
    if segundos is None:
        return None
    segundos = int(segundos)
    return f"{segundos // 3600}h {(segundos % 3600) // 60:02d}m {segundos % 60:02d}s"


def _decorar(t):
    if t:
        t["tiempo_en_terminal"] = duracion(t["segundos_en_terminal"])
        t["activo"] = t["estado"] not in C.ESTADOS_TURNO_FINALES
        t["posicion_patio"] = (f"P{t['posicion_asignada']}-{t['nivel_asignado']}"
                               if t["posicion_asignada"] else None)
    return t


def obtener(turno_id=None, codigo=None):
    if codigo is not None:
        t = db.uno(_SELECT + " WHERE t.codigo = ?", (codigo,))
    else:
        t = db.uno(_SELECT + " WHERE t.id = ?", (turno_id,))
    return _decorar(t)


def obtener_o_error(turno_id=None, codigo=None):
    t = obtener(turno_id, codigo)
    if not t:
        raise NoEncontrado("El turno no existe.")
    return t


def listar(seccion=None, estado=None, tipo=None, desde=None, hasta=None, q=None, transportista_id=None):
    sql, params = _SELECT + " WHERE 1 = 1", []
    if seccion == "activos":
        sql += " AND t.estado NOT IN ('Cerrado','Anulado')"
    elif seccion == "historicos":
        sql += " AND t.estado IN ('Cerrado','Anulado')"
    if estado:
        sql += " AND t.estado = ?"
        params.append(estado)
    if tipo:
        sql += " AND t.tipo = ?"
        params.append(tipo.upper())
    if desde:
        sql += " AND t.creado_en >= ?"
        params.append(desde)
    if hasta:
        sql += " AND t.creado_en <= ?"
        params.append(hasta if len(hasta) > 10 else hasta + " 23:59:59")
    if q:
        sql += " AND (t.contenedor LIKE ? OR v.placa LIKE ? OR v.rfid_uid LIKE ? OR t.codigo LIKE ?)"
        params += [f"%{q}%"] * 4
    if transportista_id:
        sql += " AND t.transportista_id = ?"
        params.append(transportista_id)
    return [_decorar(t) for t in db.todos(sql + " ORDER BY t.creado_en DESC, t.id DESC", params)]


def activo_de_vehiculo(vehiculo_id):
    t = db.uno(_SELECT + " WHERE t.vehiculo_id = ? AND t.estado NOT IN ('Cerrado','Anulado')", (vehiculo_id,))
    return _decorar(t)


def crear(manifiesto, vehiculo, cita_id=None):
    """Crea el turno cuando la garita AUTORIZA el ingreso (regla 7.1). Estado inicial EnGarita."""
    with db.transaccion():
        ahora = db.ahora()
        tid = db.insertar("turnos", {
            "manifiesto_id": manifiesto["id"], "cita_id": cita_id, "vehiculo_id": vehiculo["id"],
            "transportista_id": vehiculo["transportista_id"], "contenedor": manifiesto["contenedor"],
            "tipo": manifiesto["tipo"], "estado": C.T_EN_GARITA, "estacion": "GARITA",
            "peso_declarado_g": manifiesto["peso_declarado_g"], "tolerancia_pct": manifiesto["tolerancia_pct"],
            "creado_en": ahora, "actualizado_en": ahora,
        })
        db.ejecutar("UPDATE turnos SET codigo = ? WHERE id = ?", (f"T-{tid:04d}", tid))
        db.actualizar("manifiestos", {"estado_operativo": C.OP_EN_TERMINAL, "actualizado_en": ahora},
                      "id = ?", (manifiesto["id"],))
        if manifiesto["tipo"] == C.TIPO_DEPOSITO:
            db.ejecutar("UPDATE contenedores SET ubicacion = 'VEHICULO' WHERE codigo = ? AND ubicacion = 'FUERA'",
                        (manifiesto["contenedor"],))
        eventos.registrar("TURNO_CREADO", "Garita autoriza el ingreso; turno creado", turno_id=tid,
                          datos={"vehiculo": vehiculo["placa"], "contenedor": manifiesto["contenedor"],
                                 "tipo": manifiesto["tipo"], "manifiesto": manifiesto["codigo"]})
        t = obtener(tid)
        mqtt_bus.publicar(C.TOPICO_SRV_TURNO, "TURNO_CREADO", t)
    return t


def transicionar(turno_id, nuevo, origen=C.ORIGEN_SERVIDOR, usuario_id=None, descripcion=None,
                 datos=None, estacion=None, extra=None):
    """Cambia el estado validando la tabla de transiciones. `extra` = columnas adicionales a actualizar."""
    with db.transaccion():
        t = obtener_o_error(turno_id)
        actual = t["estado"]
        if nuevo not in C.TRANSICIONES_TURNO[actual]:
            raise Conflicto(f"Transición no permitida: {actual} -> {nuevo} (turno {t['codigo']}).")
        cambios = {"estado": nuevo, "actualizado_en": db.ahora()}
        if nuevo == C.T_RETENIDO:
            cambios["estado_previo"] = actual
        if nuevo in C.ESTADOS_TURNO_FINALES:
            cambios["cerrado_en"] = db.ahora()
        if estacion:
            cambios["estacion"] = estacion
        cambios.update(extra or {})
        db.actualizar("turnos", cambios, "id = ?", (turno_id,))
        eventos.registrar("CAMBIO_ESTADO", descripcion or f"Estado {actual} -> {nuevo}", origen=origen,
                          turno_id=turno_id, usuario_id=usuario_id,
                          datos={"de": actual, "a": nuevo, **(datos or {})})
        nuevo_t = obtener(turno_id)
        mqtt_bus.publicar(C.TOPICO_SRV_TURNO, "TURNO_ESTADO", nuevo_t)
    return nuevo_t


def anular(turno_id, motivo, origen=C.ORIGEN_USUARIO, usuario_id=None, desde_retencion=False):
    """Anula el turno y autoriza la salida sin completar la operación.
    El inventario NO se toca: refleja siempre la posición física real (regla 7.4)."""
    with db.transaccion():
        t = obtener_o_error(turno_id)
        if t["estado"] == C.T_RETENIDO and not desde_retencion:
            raise Conflicto("El turno está retenido: debe resolverse con 'Rechazar' desde Retenciones "
                            "por el rol facultado.")
        if not (motivo or "").strip():
            raise ErrorPortus("Debe indicar el motivo de la anulación.")
        t = transicionar(turno_id, C.T_ANULADO, origen=origen, usuario_id=usuario_id,
                         descripcion=f"Turno anulado: {motivo}", datos={"motivo": motivo},
                         extra={"motivo_anulacion": motivo})
        db.ejecutar("UPDATE posiciones_patio SET reservada_turno_id = NULL WHERE reservada_turno_id = ?", (turno_id,))
        db.ejecutar("UPDATE trabajos_grua SET estado = 'ABORTADO' WHERE turno_id = ? AND estado = 'ENVIADO'", (turno_id,))
        db.actualizar("manifiestos", {"estado_operativo": C.OP_ANULADO, "actualizado_en": db.ahora()},
                      "id = ?", (t["manifiesto_id"],))
        mqtt_bus.publicar(C.TOPICO_SRV_DECISION, "SALIDA_AUTORIZADA",
                          {"turno": t["codigo"], "rfid": t["rfid_uid"], "motivo": "ANULADO",
                           "cancelar_trabajos": True})
        notificaciones.notificar(t["transportista_id"], C.NOTIF_TURNO_ANULADO,
                                 {"vehiculo": t["vehiculo"], "contenedor": t["contenedor"], "motivo": motivo,
                                  "turno": t["codigo"]})
    return obtener(turno_id)


def cerrar(turno_id, origen=C.ORIGEN_CONTROLADOR):
    with db.transaccion():
        t = transicionar(turno_id, C.T_CERRADO, origen=origen, descripcion="Vehículo salió; turno cerrado",
                         estacion="FUERA")
        db.actualizar("manifiestos", {"estado_operativo": C.OP_COMPLETADO, "actualizado_en": db.ahora()},
                      "id = ?", (t["manifiesto_id"],))
        if t["tipo"] == C.TIPO_RETIRO:
            db.ejecutar("UPDATE contenedores SET ubicacion = 'FUERA', ingreso_en = NULL WHERE codigo = ?",
                        (t["contenedor"],))
        notificaciones.notificar(t["transportista_id"], C.NOTIF_TURNO_CERRADO, {
            "vehiculo": t["vehiculo"], "contenedor": t["contenedor"], "tipo": t["tipo"],
            "tiempo_total": t["tiempo_en_terminal"], "turno": t["codigo"]})
    return t
