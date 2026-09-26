# -*- coding: utf-8 -*-
"""
Patio lineal apilable (6 posiciones x 2 niveles) e inventario.

Regla 7.2: el inventario SOLO cambia cuando el controlador confirma físicamente
el movimiento (evento portus/evt/patio). Asignar una posición solo la RESERVA.

Política FASE1 (línea base, sección 13): primera posición (menor número) con el
nivel 1 libre; si no hay, apilar en la primera con nivel 2 libre. Se omiten
posiciones bloqueadas o reservadas. Queda como modo seleccionable para Fase 3.
"""
from models import db
from models import constantes as C
from models.errores import Conflicto, ErrorPortus
from services import alarmas, eventos, mqtt_bus


def estado_posiciones():
    return db.todos("SELECT * FROM v_patio ORDER BY numero")


def inventario(naviera_id=None, contenedor=None):
    sql = """
        SELECT c.codigo AS contenedor, n.codigo AS naviera, n.nombre AS naviera_nombre, c.ubicacion,
               c.posicion, c.nivel, c.ingreso_en, c.remociones,
               m.peso_declarado_g, m.estado_documental, m.canal, m.estado_operativo, m.codigo AS manifiesto,
               CASE WHEN c.ubicacion = 'PATIO' AND c.ingreso_en IS NOT NULL
                    THEN CAST((julianday('now','localtime') - julianday(c.ingreso_en)) * 1440 AS INTEGER) END AS permanencia_min
        FROM contenedores c
        LEFT JOIN navieras n ON n.id = c.naviera_id
        LEFT JOIN manifiestos m ON m.id = (SELECT MAX(id) FROM manifiestos WHERE contenedor = c.codigo AND estado_documental <> 'ANULADO')
        WHERE 1 = 1"""
    params = []
    if naviera_id:
        sql += " AND (c.naviera_id = ? OR m.naviera_id = ?)"
        params += [naviera_id, naviera_id]
    if contenedor:
        sql += " AND c.codigo = ?"
        params.append(contenedor)
    filas = db.todos(sql + " ORDER BY permanencia_min DESC, c.codigo", params)
    for f in filas:
        pm = f["permanencia_min"]
        f["permanencia"] = None if pm is None else f"{pm // 60}h {pm % 60:02d}m"
        f["permanencia_excesiva"] = bool(pm is not None and pm > C.PERMANENCIA_ALERTA_MIN)
        f["autorizacion"] = f["estado_documental"] or "SIN_MANIFIESTO"
    return filas


def politica():
    return db.leer_estado("politica_patio", C.POLITICA_FASE1)


def cambiar_politica(nueva):
    if nueva not in C.POLITICAS_PATIO:
        raise ErrorPortus(f"Política desconocida. Válidas: {', '.join(C.POLITICAS_PATIO)}")
    db.guardar_estado("politica_patio", nueva)


def elegir_destino(excluir=()):
    """(posicion, nivel) según la política activa, o None si el patio está lleno."""
    pos = [p for p in estado_posiciones()
           if p["numero"] not in excluir and not p["bloqueada"] and p["reservada_turno_id"] is None]
    for p in pos:
        if p["contenedor_n1"] is None:
            return p["numero"], 1
    for p in pos:
        if p["contenedor_n2"] is None:
            return p["numero"], 2
    return None


def _nuevo_trabajo(turno_id, orden, tipo, contenedor, origen, destino):
    n = (db.valor("SELECT COUNT(*) FROM trabajos_grua") or 0) + 1
    jid = f"J-{n:04d}"
    db.insertar("trabajos_grua", {
        "id": jid, "turno_id": turno_id, "orden": orden, "tipo": tipo, "contenedor": contenedor,
        "origen_pos": origen[0] if origen else None, "origen_nivel": origen[1] if origen else None,
        "destino_pos": destino[0] if destino else None, "destino_nivel": destino[1] if destino else None,
        "creado_en": db.ahora(),
    })
    return {"trabajo_id": jid, "orden": orden, "tipo": tipo, "contenedor": contenedor,
            "origen": {"posicion": origen[0], "nivel": origen[1]} if origen else C.DESTINO_VEHICULO,
            "destino": {"posicion": destino[0], "nivel": destino[1]} if destino else C.DESTINO_VEHICULO}


def planificar_trabajos(turno):
    """Genera los trabajos de grúa del turno (depósito, o retiro con remociones)."""
    with db.transaccion():
        if turno["tipo"] == C.TIPO_DEPOSITO:
            destino = elegir_destino()
            if destino is None:
                raise Conflicto("No hay posición disponible en el patio para el depósito.")
            db.actualizar("posiciones_patio", {"reservada_turno_id": turno["id"], "actualizado_en": db.ahora()},
                          "numero = ?", (destino[0],))
            db.actualizar("turnos", {"posicion_asignada": destino[0], "nivel_asignado": destino[1]},
                          "id = ?", (turno["id"],))
            trabajos = [_nuevo_trabajo(turno["id"], 1, C.TRABAJO_DEPOSITO, turno["contenedor"], None, destino)]
        else:
            c = db.uno("SELECT * FROM contenedores WHERE codigo = ?", (turno["contenedor"],))
            if not c or c["ubicacion"] != "PATIO":
                raise Conflicto(f"El contenedor {turno['contenedor']} no está en el patio.")
            origen = (c["posicion"], c["nivel"])
            trabajos = []
            if c["nivel"] == 1:
                encima = db.valor("SELECT contenedor_n2 FROM posiciones_patio WHERE numero = ?", (c["posicion"],))
                if encima:
                    destino_rem = elegir_destino(excluir=(c["posicion"],))
                    if destino_rem is None:
                        raise Conflicto("No hay posición libre para la remoción previa al retiro.")
                    db.actualizar("posiciones_patio", {"reservada_turno_id": turno["id"]}, "numero = ?", (destino_rem[0],))
                    trabajos.append(_nuevo_trabajo(turno["id"], 1, C.TRABAJO_REMOCION, encima,
                                                   (c["posicion"], 2), destino_rem))
            trabajos.append(_nuevo_trabajo(turno["id"], len(trabajos) + 1, C.TRABAJO_RETIRO,
                                           turno["contenedor"], origen, None))
            db.actualizar("turnos", {"posicion_asignada": origen[0], "nivel_asignado": origen[1]},
                          "id = ?", (turno["id"],))
        eventos.registrar("TRABAJOS_GRUA_ASIGNADOS", f"{len(trabajos)} trabajo(s) de grúa asignado(s)",
                          turno_id=turno["id"], datos={"trabajos": trabajos})
    return trabajos


def aplicar_cambio(d, turno_id=None, origen=C.ORIGEN_CONTROLADOR):
    """Aplica al inventario un cambio CONFIRMADO por el controlador.
    d = {"posicion": 3, "nivel": 1, "contenedor": "CONT-001", "accion": "COLOCADO"|"RETIRADO"|"BLOQUEADA"|"LIBERADA",
         "motivo": "DEPOSITO"|"RETIRO"|"REMOCION"}"""
    pos, nivel, cont, accion = int(d["posicion"]), d.get("nivel"), d.get("contenedor"), d.get("accion")
    motivo = d.get("motivo")
    with db.transaccion():
        p = db.uno("SELECT * FROM posiciones_patio WHERE numero = ?", (pos,))
        if not p:
            raise ErrorPortus(f"Posición de patio inexistente: {pos}")
        col = f"contenedor_n{int(nivel)}" if nivel else None
        if accion == "COLOCADO":
            if int(nivel) == 2 and p["contenedor_n1"] is None:
                alarmas.generar("AL07", origen=origen, clave=f"P{pos}", detalle=f"P{pos}: nivel 2 sin nivel 1")
            if p[col] is not None and p[col] != cont:
                alarmas.generar("AL07", origen=origen, clave=f"P{pos}",
                                detalle=f"P{pos}-{nivel}: el inventario tenía {p[col]}")
            db.actualizar("posiciones_patio", {col: cont, "reservada_turno_id": None, "actualizado_en": db.ahora()},
                          "numero = ?", (pos,))
            db.ejecutar("""UPDATE contenedores SET ubicacion = 'PATIO', posicion = ?, nivel = ?,
                           ingreso_en = COALESCE(ingreso_en, ?),
                           remociones = remociones + CASE WHEN ? = 'REMOCION' THEN 1 ELSE 0 END
                           WHERE codigo = ?""", (pos, nivel, db.ahora(), motivo, cont))
        elif accion == "RETIRADO":
            if p[col] != cont:
                alarmas.generar("AL07", origen=origen, clave=f"P{pos}",
                                detalle=f"P{pos}-{nivel}: se retiró {cont} pero el inventario tenía {p[col]}")
            db.actualizar("posiciones_patio", {col: None, "actualizado_en": db.ahora()}, "numero = ?", (pos,))
            db.ejecutar("UPDATE contenedores SET ubicacion = ?, posicion = NULL, nivel = NULL WHERE codigo = ?",
                        ("VEHICULO" if motivo == C.TRABAJO_RETIRO else "GRUA", cont))
        elif accion in ("BLOQUEADA", "LIBERADA"):
            marcar_bloqueo(pos, accion == "BLOQUEADA", d.get("causa"))
        else:
            raise ErrorPortus(f"Acción de patio desconocida: {accion}")
        eventos.registrar("PATIO_" + accion, f"Posición P{pos}{'-' + str(nivel) if nivel else ''}: {accion} {cont or ''}".strip(),
                          origen=origen, turno_id=turno_id, datos=d)
        mqtt_bus.publicar(C.TOPICO_SRV_PATIO, "PATIO_ACTUALIZADO", {"posiciones": estado_posiciones()})


def marcar_bloqueo(pos, bloquear, motivo=None):
    db.actualizar("posiciones_patio", {"bloqueada": 1 if bloquear else 0,
                                       "motivo_bloqueo": motivo if bloquear else None,
                                       "actualizado_en": db.ahora()}, "numero = ?", (pos,))
    mqtt_bus.publicar(C.TOPICO_SRV_PATIO, "PATIO_ACTUALIZADO", {"posiciones": estado_posiciones()})
