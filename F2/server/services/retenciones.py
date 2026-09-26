# -*- coding: utf-8 -*-
"""
Retenciones (secciones 4.3, 8.2 y 8.3).
  * Rol facultado por causa: RT03 y RT05 -> AUTORIDAD; RT01, RT02, RT04, RT06 -> TERMINAL.
  * Corregir: únicamente TERMINAL y solo en causas de peso.
  * Rechazar: exige motivo. Aclarar/Corregir: observación opcional.
  * Una retención resuelta no puede volver a resolverse.
  * Toda resolución notifica al transportista dueño del turno.
"""
from models import db
from models import constantes as C
from models.errores import Conflicto, ErrorPermiso, ErrorPortus, NoEncontrado
from services import eventos, mqtt_bus, notificaciones, parqueo, turnos

_SELECT = """
    SELECT r.*, t.codigo AS turno, t.contenedor, t.transportista_id, v.placa AS vehiculo,
           CAST((julianday(COALESCE(r.resuelta_en, datetime('now','localtime'))) - julianday(r.creada_en)) * 86400 AS INTEGER) AS segundos_retencion,
           uc.username AS creada_por_usuario, ur.username AS resuelta_por_usuario
    FROM retenciones r
    JOIN turnos t ON t.id = r.turno_id
    JOIN vehiculos v ON v.id = t.vehiculo_id
    LEFT JOIN usuarios uc ON uc.id = r.creada_por
    LEFT JOIN usuarios ur ON ur.id = r.resuelta_por
"""


def _decorar(r):
    if r:
        info = C.CAUSAS_RETENCION[r["causa"]]
        r["causa_descripcion"] = info["descripcion"]
        r["aduanera"] = info["aduanera"]
        r["tiempo_retencion"] = turnos.duracion(r["segundos_retencion"])
        r["evidencia_peso"] = None
        if r["causa"] in C.CAUSAS_DE_PESO:
            r["evidencia_peso"] = {"peso_declarado_g": r["peso_declarado_g"], "peso_medido_g": r["peso_medido_g"],
                                   "diferencia_g": r["diferencia_g"], "diferencia_pct": r["diferencia_pct"]}
    return r


def obtener(ret_id):
    return _decorar(db.uno(_SELECT + " WHERE r.id = ?", (ret_id,)))


def listar(estado=None, causa=None, solo_aduaneras=False, turno_id=None):
    sql, params = _SELECT + " WHERE 1 = 1", []
    if estado:
        sql += " AND r.estado = ?"
        params.append(estado.upper())
    if causa:
        sql += " AND r.causa = ?"
        params.append(causa.upper())
    if solo_aduaneras:
        sql += " AND r.causa IN ('RT03','RT05')"
    if turno_id:
        sql += " AND r.turno_id = ?"
        params.append(turno_id)
    return [_decorar(r) for r in db.todos(sql + " ORDER BY r.creada_en DESC, r.id DESC", params)]


def abierta_de_turno(turno_id):
    return db.uno("SELECT * FROM retenciones WHERE turno_id = ? AND estado = 'ABIERTA'", (turno_id,))


def crear(turno_id, causa, origen=C.ORIGEN_SERVIDOR, usuario_id=None, observacion=None, evidencia=None):
    """Retiene el turno: estado Retenido, plaza de parqueo si aún no llega a transferencia,
    comando AgujaParqueo y aviso al transportista."""
    if causa not in C.CAUSAS_RETENCION:
        raise ErrorPortus(f"Causa de retención desconocida: {causa}")
    info = C.CAUSAS_RETENCION[causa]
    with db.transaccion():
        t = turnos.obtener_o_error(turno_id)
        if abierta_de_turno(turno_id):
            raise Conflicto(f"El turno {t['codigo']} ya tiene una retención abierta.")
        if C.T_RETENIDO not in C.TRANSICIONES_TURNO[t["estado"]]:
            raise Conflicto(f"No se puede retener un turno en estado {t['estado']}.")
        ev = evidencia or {}
        rid = db.insertar("retenciones", {
            "turno_id": turno_id, "causa": causa, "rol_facultado": info["rol"], "estacion": t["estacion"],
            "estado_turno_previo": t["estado"], "peso_declarado_g": ev.get("peso_declarado_g"),
            "peso_medido_g": ev.get("peso_medido_g"), "diferencia_g": ev.get("diferencia_g"),
            "diferencia_pct": ev.get("diferencia_pct"), "observacion_origen": observacion,
            "creada_por": usuario_id, "creada_en": db.ahora(),
        })
        codigo = f"RET-{rid:04d}"
        db.ejecutar("UPDATE retenciones SET codigo = ? WHERE id = ?", (codigo, rid))
        turnos.transicionar(turno_id, C.T_RETENIDO, origen=origen, usuario_id=usuario_id,
                            descripcion=f"Retención {codigo}: {causa} - {info['descripcion']}",
                            datos={"retencion": codigo, "causa": causa, "observacion": observacion, **ev})
        plaza = None
        if t["estado"] in C.ESTADOS_ANTES_DE_TRANSFERENCIA:
            plaza = parqueo.ocupar(turno_id, rid)
            db.ejecutar("UPDATE retenciones SET plaza = ? WHERE id = ?", (plaza, rid))
            if plaza:
                db.ejecutar("UPDATE turnos SET estacion = 'PARQUEO' WHERE id = ?", (turno_id,))
        mqtt_bus.publicar(C.TOPICO_SRV_DECISION, "RUTA_PARQUEO" if plaza else "VEHICULO_RETENIDO",
                          {"turno": t["codigo"], "rfid": t["rfid_uid"], "plaza": plaza, "causa": causa})
        notificaciones.notificar(t["transportista_id"], C.NOTIF_VEHICULO_RETENIDO, {
            "vehiculo": t["vehiculo"], "contenedor": t["contenedor"], "causa": causa,
            "causa_descripcion": info["descripcion"], "turno": t["codigo"], **ev})
        r = obtener(rid)
        mqtt_bus.publicar(C.TOPICO_SRV_RETENCION, "RETENCION_CREADA", r)
    return r


def resolver(ret_id, resolucion, usuario, motivo=None, observacion=None):
    """Aplica Aclarar / Corregir / Rechazar validando el rol facultado EN EL SERVIDOR."""
    resolucion = (resolucion or "").upper()
    if resolucion not in C.RESOLUCIONES:
        raise ErrorPortus("Resolución inválida. Use ACLARAR, CORREGIR o RECHAZAR.")
    with db.transaccion():
        r = obtener(ret_id)
        if not r:
            raise NoEncontrado("La retención no existe.")
        if r["estado"] == C.RETENCION_RESUELTA:
            raise Conflicto(f"La retención {r['codigo']} ya fue resuelta y no puede volver a resolverse.")
        if usuario["rol"] != r["rol_facultado"]:
            raise ErrorPermiso(f"El rol {usuario['rol']} no está facultado para resolver la causa {r['causa']}; "
                               f"corresponde a {r['rol_facultado']}.")
        if resolucion == C.RES_CORREGIR:
            if usuario["rol"] != C.ROL_TERMINAL:
                raise ErrorPermiso("La resolución Corregir corresponde exclusivamente al rol TERMINAL.")
            if r["causa"] not in C.CAUSAS_DE_PESO or not r["peso_medido_g"]:
                raise ErrorPortus("Corregir solo aplica a retenciones por discrepancia de peso con peso medido.")
        if resolucion == C.RES_RECHAZAR and not (motivo or "").strip():
            raise ErrorPortus("La resolución Rechazar exige indicar un motivo.")

        db.actualizar("retenciones", {"estado": C.RETENCION_RESUELTA, "resolucion": resolucion,
                                      "motivo": motivo, "observacion": observacion,
                                      "resuelta_por": usuario["id"], "resuelta_en": db.ahora()},
                      "id = ?", (ret_id,))
        t = turnos.obtener(r["turno_id"])
        datos_notif = {"vehiculo": t["vehiculo"], "contenedor": t["contenedor"], "resolucion": resolucion,
                       "turno": t["codigo"], "retencion": r["codigo"]}

        if resolucion == C.RES_CORREGIR:
            anterior = t["peso_declarado_g"]
            nuevo = int(r["peso_medido_g"])
            db.actualizar("manifiestos", {"peso_declarado_g": nuevo, "actualizado_en": db.ahora()},
                          "id = ?", (t["manifiesto_id"],))
            db.insertar("manifiesto_historial", {
                "manifiesto_id": t["manifiesto_id"], "accion": "CORREGIR_PESO", "campo": "peso_declarado_g",
                "valor_anterior": str(anterior), "valor_nuevo": str(nuevo), "usuario_id": usuario["id"],
                "comentario": f"Retención {r['codigo']}. {observacion or ''}".strip(), "creado_en": db.ahora()})
            db.ejecutar("UPDATE turnos SET peso_declarado_g = ? WHERE id = ?", (nuevo, t["id"]))
            datos_notif["peso_nuevo_g"] = nuevo
        if resolucion == C.RES_RECHAZAR:
            datos_notif["motivo"] = motivo

        eventos.registrar("RETENCION_RESUELTA", f"Retención {r['codigo']} resuelta: {resolucion}",
                          origen=C.ORIGEN_USUARIO, turno_id=t["id"], usuario_id=usuario["id"],
                          datos={"resolucion": resolucion, "motivo": motivo, "observacion": observacion,
                                 "peso_nuevo_g": datos_notif.get("peso_nuevo_g")})

        plaza = parqueo.plaza_de_turno(t["id"])
        previo = r["estado_turno_previo"]
        notificaciones.notificar(t["transportista_id"], C.NOTIF_RETENCION_RESUELTA, datos_notif)

        # Retención en garita/pesaje de entrada: pueden quedar controles pendientes del pesaje
        # (ej. RT04 aclarada pero el contenedor trae canal rojo -> RT03). Como la tabla de
        # transiciones no permite EnRuta -> Retenido, la nueva retención se ENCADENA y el
        # vehículo conserva su plaza.
        pendiente = None
        if resolucion != C.RES_RECHAZAR and previo in C.ESTADOS_ANTES_DE_TRANSFERENCIA:
            from services import operacion
            pendiente = operacion.control_pendiente_entrada(t["id"])

        if pendiente:
            _encadenar(t, r, pendiente[0], pendiente[1], plaza)
        else:
            if plaza:
                parqueo.solicitar_liberacion(plaza, usuario_id=usuario["id"])
            if resolucion == C.RES_RECHAZAR:
                turnos.anular(t["id"], f"Retención {r['codigo']} rechazada: {motivo}", usuario_id=usuario["id"],
                              desde_retencion=True)
            else:
                destino = C.T_EN_RUTA if previo in C.ESTADOS_ANTES_DE_TRANSFERENCIA else C.T_EN_SALIDA
                turnos.transicionar(t["id"], destino, origen=C.ORIGEN_USUARIO, usuario_id=usuario["id"],
                                    descripcion=f"Retención {r['codigo']} resuelta ({resolucion}); el turno continúa",
                                    estacion="AGUJA" if plaza else None)
                mqtt_bus.publicar(C.TOPICO_SRV_DECISION, "RETENCION_RESUELTA",
                                  {"turno": t["codigo"], "rfid": t["rfid_uid"], "plaza": plaza, "continuar": True,
                                   "estado": destino, "peso_declarado_g": datos_notif.get("peso_nuevo_g")})

        final = obtener(ret_id)
        mqtt_bus.publicar(C.TOPICO_SRV_RETENCION, "RETENCION_RESUELTA", final)
    return final


def _encadenar(t, anterior, causa, evidencia, plaza):
    """Crea una nueva retención sobre un turno que sigue Retenido (misma plaza)."""
    info = C.CAUSAS_RETENCION[causa]
    ev = evidencia or {}
    rid = db.insertar("retenciones", {
        "turno_id": t["id"], "causa": causa, "rol_facultado": info["rol"], "estacion": anterior["estacion"],
        "estado_turno_previo": anterior["estado_turno_previo"], "plaza": plaza,
        "peso_declarado_g": ev.get("peso_declarado_g"), "peso_medido_g": ev.get("peso_medido_g"),
        "diferencia_g": ev.get("diferencia_g"), "diferencia_pct": ev.get("diferencia_pct"),
        "observacion_origen": f"Encadenada tras {anterior['codigo']}", "creada_en": db.ahora(),
    })
    codigo = f"RET-{rid:04d}"
    db.ejecutar("UPDATE retenciones SET codigo = ? WHERE id = ?", (codigo, rid))
    if plaza:
        db.ejecutar("UPDATE plazas_parqueo SET retencion_id = ? WHERE numero = ?", (rid, plaza))
    eventos.registrar("RETENCION_ENCADENADA", f"Retención {codigo}: {causa} - {info['descripcion']}",
                      turno_id=t["id"], datos={"retencion": codigo, "causa": causa, **ev})
    notificaciones.notificar(t["transportista_id"], C.NOTIF_VEHICULO_RETENIDO, {
        "vehiculo": t["vehiculo"], "contenedor": t["contenedor"], "causa": causa,
        "causa_descripcion": info["descripcion"], "turno": t["codigo"], **ev})
    mqtt_bus.publicar(C.TOPICO_SRV_RETENCION, "RETENCION_CREADA", obtener(rid))
