# -*- coding: utf-8 -*-
"""
Ingesta de eventos del controlador (portus/evt/* y portus/cmd/respuesta) y
decisiones del servidor (validación de garita, ruta tras pesaje, trabajos de
grúa, autorización de salida), que se publican en portus/srv/decision.

Contrato con el puente/firmware: ver docs/VARIABLES_EQUIPO.md, sección MQTT.
Todo evento del controlador posterior a la garita debe incluir "turno" (el
código que el servidor devolvió en GARITA_RESULTADO) y/o "rfid".
"""
import logging
from datetime import datetime

from models import db
from models import constantes as C
from models.errores import ErrorPortus
from services import (alarmas, citas, comandos, eventos, mqtt_bus, parqueo, patio, retenciones,
                      turnos)

log = logging.getLogger("portus.operacion")

MAPA_FALLAS = {"PERDIDA_REFERENCIA": "AL03", "AGARRE_NO_CONFIRMADO": "AL05",
               "MOVIMIENTO_ABORTADO": "AL06", "PERDIDA_CARGA": "AL04"}


# ---------------------------------------------------------------------------
# Punto de entrada: lo llama el cliente MQTT (y /api/interno/eventos para pruebas)
# ---------------------------------------------------------------------------
def procesar_mensaje(topico, msg):
    datos = msg.get("datos") or {}
    tipo = msg.get("tipo", "")
    mid = msg.get("id")
    seq = msg.get("seq")
    ts = _ts(msg.get("ts"))

    if topico == C.TOPICO_EVT_ESTADO:
        return registrar_latido(tipo, datos, seq)
    if mid and db.valor("SELECT 1 FROM eventos WHERE mensaje_id = ?", (mid,)):
        return {"duplicado": True}
    _controlar_secuencia(seq)

    manejadores = {
        C.TOPICO_EVT_GARITA: _garita, C.TOPICO_EVT_PESAJE: _pesaje, C.TOPICO_EVT_AGUJA: _aguja,
        C.TOPICO_EVT_TRANSFERENCIA: _transferencia, C.TOPICO_EVT_GRUA: _grua, C.TOPICO_EVT_PATIO: _patio,
        C.TOPICO_EVT_SALIDA: _salida, C.TOPICO_EVT_ALARMA: _alarma, C.TOPICO_CMD_RESPUESTA: _respuesta,
    }
    fn = manejadores.get(topico)
    if fn is None:
        log.warning("Tópico sin manejador: %s", topico)
        return None
    try:
        with db.transaccion():
            resultado = fn(tipo, datos, {"mensaje_id": mid, "seq": seq, "ts": ts, "topico": topico})
        return resultado
    except ErrorPortus as e:
        eventos.registrar("ERROR_PROCESAMIENTO", f"{topico} {tipo}: {e.mensaje}", origen=C.ORIGEN_SERVIDOR,
                          datos={"mensaje": msg}, mensaje_id=mid, topico=topico, seq=seq)
        log.warning("No se pudo procesar %s %s: %s", topico, tipo, e.mensaje)
        return {"error": e.mensaje}


def _ts(texto):
    try:
        return db.texto_fecha(db.a_fecha(texto)) if texto else db.ahora()
    except ValueError:
        return db.ahora()


def _controlar_secuencia(seq):
    if seq is None:
        return
    ultimo = db.leer_estado("ultimo_seq")
    if ultimo is not None and int(seq) > int(ultimo) + 1:
        eventos.registrar("PERDIDA_MENSAJES", f"Se perdieron {int(seq) - int(ultimo) - 1} mensaje(s) del controlador "
                          f"(secuencia {ultimo} -> {seq})", datos={"desde": int(ultimo) + 1, "hasta": int(seq) - 1})
    if ultimo is None or int(seq) > int(ultimo):
        db.guardar_estado("ultimo_seq", int(seq))


def _ev(meta, tipo, descripcion, turno_id=None, datos=None):
    eventos.registrar(tipo, descripcion, origen=C.ORIGEN_CONTROLADOR, turno_id=turno_id, datos=datos,
                      mensaje_id=meta["mensaje_id"], topico=meta["topico"], seq=meta["seq"], ts=meta["ts"])


def _vehiculo_por_rfid(rfid):
    return db.uno("SELECT * FROM vehiculos WHERE rfid_uid = ? AND activo = 1", ((rfid or "").strip().upper(),))


def _turno_de(d):
    if d.get("turno"):
        t = turnos.obtener(codigo=d["turno"])
        if t:
            return t
    if d.get("rfid"):
        v = _vehiculo_por_rfid(d["rfid"])
        if v:
            return turnos.activo_de_vehiculo(v["id"])
    return None


def _turno_obligatorio(d):
    t = _turno_de(d)
    if not t:
        raise ErrorPortus(f"No se encontró turno activo para turno={d.get('turno')} rfid={d.get('rfid')}")
    return t


# ---------------------------------------------------------------------------
# GARITA: validación de acceso (la hace el servidor, sección 12)
# ---------------------------------------------------------------------------
def _garita(tipo, d, meta):
    if tipo == "VEHICULO_DETECTADO":
        return validar_ingreso(d.get("rfid"), meta)
    t = _turno_de(d)
    _ev(meta, "GARITA_" + tipo, f"Garita: {tipo}", t["id"] if t else None, d)
    return None


def validar_ingreso(rfid, meta=None):
    rfid = (rfid or "").strip().upper()
    meta = meta or {"mensaje_id": None, "seq": None, "ts": db.ahora(), "topico": C.TOPICO_EVT_GARITA}

    def rechazo(causa, vehiculo=None, manifiesto=None, lcd=None):
        db.insertar("intentos_ingreso", {
            "rfid_uid": rfid, "vehiculo_id": vehiculo["id"] if vehiculo else None,
            "transportista_id": vehiculo["transportista_id"] if vehiculo else None,
            "manifiesto_id": manifiesto["id"] if manifiesto else None, "causa": causa, "creado_en": db.ahora()})
        _ev(meta, "INGRESO_RECHAZADO", f"Ingreso rechazado ({rfid}): {causa}", None, {"rfid": rfid, "causa": causa})
        resp = {"rfid": rfid, "autorizado": False, "causa": causa, "mensaje_lcd": (lcd or causa)[:32]}
        mqtt_bus.publicar(C.TOPICO_SRV_DECISION, "GARITA_RESULTADO", resp)
        return resp

    if db.leer_estado("modo", C.MODO_NORMAL) == C.MODO_MANTENIMIENTO:
        return rechazo("Sistema en modo mantenimiento", lcd="MANTENIMIENTO")
    v = _vehiculo_por_rfid(rfid)
    if not v:
        return rechazo("RFID no registrado", lcd="RFID no valido")
    if turnos.activo_de_vehiculo(v["id"]):
        return rechazo("El vehículo ya tiene un turno activo", v, lcd="Turno activo")

    manifs = db.todos("""SELECT * FROM manifiestos WHERE transportista_id = ? AND estado_documental <> 'ANULADO'
                         AND estado_operativo IN ('SIN_CITA','CITA_PROGRAMADA') ORDER BY id""",
                      (v["transportista_id"],))
    candidatas = db.todos("""SELECT c.*, f.inicio, f.fin FROM citas c JOIN franjas f ON f.id = c.franja_id
                             WHERE c.transportista_id = ? AND c.estado = 'PROGRAMADA' ORDER BY f.inicio""",
                          (v["transportista_id"],))
    cita = next((c for c in candidatas if citas.evaluar_ventana(c)), None)
    if cita is None and candidatas:
        ahora = datetime.now()
        cita = min(candidatas, key=lambda c: abs((db.a_fecha(c["inicio"]) - ahora).total_seconds()))
    if cita is None:
        retenido = next((m for m in manifs if m["estado_documental"] == C.DOC_LEVANTE_RETENIDO), None)
        if retenido:
            return rechazo(f"Levante retenido: {retenido['motivo_retencion']}", v, retenido, "Levante retenido")
        if any(m["estado_documental"] != C.DOC_LEVANTE_OTORGADO for m in manifs):
            return rechazo("Sin levante otorgado", v, manifs[0], "Sin levante")
        if manifs:
            return rechazo("Sin cita asignada", v, manifs[0], "Sin cita")
        return rechazo("Sin manifiesto activo", v, lcd="Sin manifiesto")

    m = db.uno("SELECT * FROM manifiestos WHERE id = ?", (cita["manifiesto_id"],))
    if m["estado_documental"] != C.DOC_LEVANTE_OTORGADO:
        causa = (f"Levante retenido: {m['motivo_retencion']}" if m["estado_documental"] == C.DOC_LEVANTE_RETENIDO
                 else "Sin levante otorgado")
        return rechazo(causa, v, m, "Levante retenido" if "retenido" in causa else "Sin levante")

    dentro = citas.evaluar_ventana(cita)
    riesgo = m["canal"] == C.CANAL_ROJO or not dentro
    if riesgo and parqueo.lleno():
        alarmas.generar("AL11", clave="parqueo", detalle=f"ingreso rechazado a {v['placa']}")
        return rechazo("Parqueo de retención lleno", v, m, "Parqueo lleno")
    if m["tipo"] == C.TIPO_DEPOSITO and patio.elegir_destino() is None:
        return rechazo("Patio sin posiciones disponibles", v, m, "Patio lleno")

    t = turnos.crear(m, v, cita["id"])
    citas.registrar_llegada(cita["id"], dentro)
    _ev(meta, "VEHICULO_IDENTIFICADO", f"Vehículo {v['placa']} identificado en garita", t["id"],
        {"rfid": rfid, "dentro_de_ventana": dentro})
    resp = {"rfid": rfid, "autorizado": True, "turno": t["codigo"], "placa": v["placa"],
            "contenedor": m["contenedor"], "tipo": m["tipo"], "peso_declarado_g": m["peso_declarado_g"],
            "tolerancia_pct": m["tolerancia_pct"], "tara_g": v["tara_g"], "canal": m["canal"],
            "fuera_de_ventana": not dentro, "mensaje_lcd": f"Acceso {v['placa']}"[:32]}
    mqtt_bus.publicar(C.TOPICO_SRV_DECISION, "GARITA_RESULTADO", resp)
    if not dentro:
        retenciones.crear(t["id"], "RT04", observacion="Llegada fuera de la ventana asignada")
    return resp


# ---------------------------------------------------------------------------
# PESAJE dinámico
# ---------------------------------------------------------------------------
def _comparar(t, etapa, bruto):
    tara = t["tara_g"] or 0
    neto = int(bruto) - int(tara)
    lleva_carga = (etapa == "ENTRADA") == (t["tipo"] == C.TIPO_DEPOSITO)
    esperado = t["peso_declarado_g"] if lleva_carga else 0
    dif = neto - esperado
    pct = round(abs(dif) * 100.0 / t["peso_declarado_g"], 2) if t["peso_declarado_g"] else 0.0
    return {"tara_g": tara, "neto": neto, "esperado": esperado, "dif": dif, "pct": pct,
            "dentro": pct <= float(t["tolerancia_pct"])}


def _pesaje(tipo, d, meta):
    t = _turno_obligatorio(d)
    etapa = (d.get("etapa") or "ENTRADA").upper()
    if tipo == "MEDICION_INICIADA":
        _iniciar_medicion(t, etapa, meta)
        return None
    if tipo != "MEDICION_FINAL":
        _ev(meta, "PESAJE_" + tipo, f"Pesaje {etapa}: {tipo}", t["id"], d)
        return None

    t = _iniciar_medicion(t, etapa, None)
    comp = _comparar(t, etapa, d["peso_g"])
    db.insertar("pesajes", {"turno_id": t["id"], "etapa": etapa, "peso_bruto_g": int(d["peso_g"]),
                            "tara_g": comp["tara_g"], "peso_neto_g": comp["neto"], "esperado_g": comp["esperado"],
                            "diferencia_g": abs(comp["dif"]), "diferencia_pct": comp["pct"],
                            "muestras": d.get("muestras"), "dentro_tolerancia": 1 if comp["dentro"] else 0,
                            "creado_en": meta["ts"]})
    db.ejecutar(f"UPDATE turnos SET {'peso_entrada_g' if etapa == 'ENTRADA' else 'peso_salida_g'} = ? WHERE id = ?",
                (int(d["peso_g"]), t["id"]))
    _ev(meta, "PESAJE_" + etapa, f"Pesaje de {etapa.lower()}: {d['peso_g']} g "
        f"({'dentro' if comp['dentro'] else 'FUERA'} de tolerancia, dif {comp['pct']}%)", t["id"],
        {"peso_bruto_g": d["peso_g"], "peso_neto_g": comp["neto"], "esperado_g": comp["esperado"],
         "diferencia_pct": comp["pct"], "muestras": d.get("muestras")})
    if not comp["dentro"]:
        alarmas.generar("AL09", origen=C.ORIGEN_SERVIDOR, clave=f"{t['codigo']}-{etapa}", turno_id=t["id"],
                        detalle=f"{t['codigo']} {etapa.lower()} {comp['pct']}%")
    t = turnos.obtener(t["id"])

    if etapa == "ENTRADA" and t["estado"] == C.T_EN_PESAJE_ENTRADA:
        pend = control_pendiente_entrada(t["id"])
        if pend:
            retenciones.crear(t["id"], pend[0], evidencia=pend[1])
        else:
            turnos.transicionar(t["id"], C.T_EN_RUTA, descripcion="Pesaje de entrada válido; ruta a transferencia",
                                estacion="AGUJA")
            mqtt_bus.publicar(C.TOPICO_SRV_DECISION, "RUTA_TRANSFERENCIA", {"turno": t["codigo"], "rfid": t["rfid_uid"]})
    elif etapa == "SALIDA" and t["estado"] == C.T_EN_PESAJE_SALIDA:
        if comp["dentro"]:
            turnos.transicionar(t["id"], C.T_EN_SALIDA, descripcion="Pesaje de salida válido", estacion="SALIDA")
            mqtt_bus.publicar(C.TOPICO_SRV_DECISION, "PESAJE_SALIDA_OK", {"turno": t["codigo"], "rfid": t["rfid_uid"]})
        else:
            retenciones.crear(t["id"], "RT02", evidencia=_evidencia(t, comp))
    return comp


def _iniciar_medicion(t, etapa, meta):
    if etapa == "ENTRADA" and t["estado"] == C.T_EN_GARITA:
        t = turnos.transicionar(t["id"], C.T_EN_PESAJE_ENTRADA, origen=C.ORIGEN_CONTROLADOR,
                                descripcion="Vehículo en la plataforma de pesaje de entrada", estacion="PESAJE_ENTRADA")
    elif etapa == "SALIDA" and t["estado"] == C.T_EN_TRANSFERENCIA:
        t = turnos.transicionar(t["id"], C.T_EN_PESAJE_SALIDA, origen=C.ORIGEN_CONTROLADOR,
                                descripcion="Vehículo en la plataforma de pesaje de salida", estacion="PESAJE_SALIDA")
    elif meta:
        _ev(meta, "PESAJE_INICIADO", f"Inicio de pesaje {etapa.lower()}", t["id"])
    return t


def _evidencia(t, comp):
    return {"peso_declarado_g": t["peso_declarado_g"], "peso_medido_g": comp["neto"],
            "diferencia_g": abs(comp["dif"]), "diferencia_pct": comp["pct"]}


def control_pendiente_entrada(turno_id):
    """Controles posteriores al pesaje de entrada que aún no tienen retención:
    RT01 si el peso está fuera de tolerancia, luego RT03 si el canal es rojo.
    Devuelve (causa, evidencia) o None."""
    p = db.uno("SELECT * FROM pesajes WHERE turno_id = ? AND etapa = 'ENTRADA' ORDER BY id DESC LIMIT 1", (turno_id,))
    if not p:
        return None
    t = turnos.obtener(turno_id)
    causas = {r["causa"] for r in db.todos("SELECT causa FROM retenciones WHERE turno_id = ?", (turno_id,))}
    if not p["dentro_tolerancia"] and "RT01" not in causas:
        comp = _comparar(t, "ENTRADA", p["peso_bruto_g"])
        if not comp["dentro"]:   # tras un Corregir ya estaría dentro
            return "RT01", _evidencia(t, comp)
    if t["canal"] == C.CANAL_ROJO and "RT03" not in causas:
        return "RT03", None
    return None


# ---------------------------------------------------------------------------
# AGUJA, TRANSFERENCIA, GRÚA, PATIO
# ---------------------------------------------------------------------------
def _aguja(tipo, d, meta):
    if d.get("estado"):
        db.guardar_estado("aguja", d["estado"])
    t = _turno_de(d)
    _ev(meta, "AGUJA_" + tipo, f"Aguja: {d.get('estado', tipo)}", t["id"] if t else None, d)


def _transferencia(tipo, d, meta):
    t = _turno_obligatorio(d)
    if tipo == "VEHICULO_ALINEADO" and t["estado"] == C.T_EN_RUTA:
        turnos.transicionar(t["id"], C.T_EN_TRANSFERENCIA, origen=C.ORIGEN_CONTROLADOR,
                            descripcion="Vehículo alineado en la zona de transferencia", estacion="TRANSFERENCIA")
        trabajos = patio.planificar_trabajos(turnos.obtener(t["id"]))
        mqtt_bus.publicar(C.TOPICO_SRV_DECISION, "TRABAJOS_GRUA", {"turno": t["codigo"], "trabajos": trabajos})
        _ev(meta, "TRANSFERENCIA_ALINEADO", "Vehículo alineado", t["id"], d)
        return {"trabajos": trabajos}
    if tipo == "TRANSFERENCIA_ABORTO" and t["estado"] == C.T_EN_TRANSFERENCIA:
        turnos.transicionar(t["id"], C.T_EN_TRANSFERENCIA, origen=C.ORIGEN_CONTROLADOR,
                            descripcion=f"Transferencia abortada: {d.get('causa', '-')}", datos=d)
    if tipo == "VEHICULO_POSICIONANDO":
        db.ejecutar("UPDATE turnos SET estacion = 'TRANSFERENCIA' WHERE id = ?", (t["id"],))
    _ev(meta, tipo, f"Transferencia: {tipo}", t["id"], d)
    return None


def _grua(tipo, d, meta):
    trabajo = db.uno("SELECT * FROM trabajos_grua WHERE id = ?", (d.get("trabajo_id"),)) if d.get("trabajo_id") else None
    turno_id = trabajo["turno_id"] if trabajo else None
    if tipo == "GRUA_ESTADO":
        db.guardar_estado("grua", db.a_json(d))
        return None
    if tipo == "CICLO_INICIO":
        db.insertar("ciclos_grua", {"trabajo_id": d.get("trabajo_id"), "turno_id": turno_id,
                                    "tipo": (d.get("tipo") or (trabajo or {}).get("tipo") or "DEPOSITO").upper(),
                                    "contenedor": d.get("contenedor") or (trabajo or {}).get("contenedor"),
                                    "origen": str(d.get("origen")), "destino": str(d.get("destino")),
                                    "inicio_en": meta["ts"]})
        if trabajo:
            db.ejecutar("UPDATE trabajos_grua SET estado = 'EN_CURSO' WHERE id = ?", (trabajo["id"],))
        _ev(meta, "GRUA_CICLO_INICIO", f"Grúa inicia {d.get('tipo', '')} {d.get('contenedor', '')}".strip(), turno_id, d)
    elif tipo == "CICLO_FIN":
        resultado = (d.get("resultado") or "OK").upper()
        ciclo_id = db.valor("SELECT MAX(id) FROM ciclos_grua WHERE IFNULL(trabajo_id,'') = IFNULL(?, '') AND fin_en IS NULL",
                            (d.get("trabajo_id"),))
        if ciclo_id:
            db.actualizar("ciclos_grua", {"fin_en": meta["ts"], "resultado": resultado,
                                          "duracion_ms": d.get("duracion_ms"), "distancia_mm": d.get("distancia_mm")},
                          "id = ?", (ciclo_id,))
            if not d.get("duracion_ms"):
                db.ejecutar("""UPDATE ciclos_grua SET duracion_ms = CAST((julianday(fin_en) - julianday(inicio_en)) * 86400000 AS INTEGER)
                               WHERE id = ?""", (ciclo_id,))
        if trabajo:
            db.ejecutar("UPDATE trabajos_grua SET estado = ? WHERE id = ?",
                        ("COMPLETADO" if resultado == "OK" else "ABORTADO", trabajo["id"]))
        _ev(meta, "GRUA_CICLO_FIN", f"Grúa termina ciclo: {resultado}", turno_id, d)
    elif tipo == "FALLA":
        falla = (d.get("falla") or d.get("tipo_falla") or "").upper()
        if falla not in C.FALLAS_GRUA:
            raise ErrorPortus(f"Tipo de falla de grúa desconocido: {falla}")
        db.insertar("fallas_grua", {"tipo": falla, "trabajo_id": d.get("trabajo_id"), "turno_id": turno_id,
                                    "detalle": d.get("detalle"), "creado_en": meta["ts"]})
        _ev(meta, "GRUA_FALLA", f"Falla de grúa: {falla}", turno_id, d)
        alarmas.generar(MAPA_FALLAS[falla], origen=C.ORIGEN_CONTROLADOR, clave=d.get("trabajo_id") or falla,
                        turno_id=turno_id, datos=d)
    else:
        _ev(meta, "GRUA_" + tipo, f"Grúa: {tipo}", turno_id, d)
    return None


def _patio(tipo, d, meta):
    t = _turno_de(d) if (d.get("turno") or d.get("rfid")) else None
    _ev(meta, "PATIO_EVENTO", f"Patio: {d.get('accion')} P{d.get('posicion')}", t["id"] if t else None, d)
    patio.aplicar_cambio(d, t["id"] if t else None)


# ---------------------------------------------------------------------------
# SALIDA
# ---------------------------------------------------------------------------
def _salida(tipo, d, meta):
    v = _vehiculo_por_rfid(d.get("rfid")) if d.get("rfid") else None
    t = _turno_de(d)
    if t is None and v:  # turno recién anulado que aún no sale
        t = turnos.obtener(db.valor("""SELECT id FROM turnos WHERE vehiculo_id = ? AND estado = 'Anulado'
                                       AND IFNULL(estacion,'') <> 'FUERA' ORDER BY id DESC LIMIT 1""", (v["id"],)))
    if tipo == "VEHICULO_EN_SALIDA":
        valido = t is not None and t["estado"] in (C.T_EN_SALIDA, C.T_ANULADO)
        _ev(meta, "SALIDA_VERIFICACION", f"Verificación de salida: {'válida' if valido else 'INVÁLIDA'}",
            t["id"] if t else None, d)
        if valido:
            mqtt_bus.publicar(C.TOPICO_SRV_DECISION, "SALIDA_AUTORIZADA", {"turno": t["codigo"], "rfid": t["rfid_uid"]})
        else:
            alarmas.generar("AL10", clave=d.get("rfid"), turno_id=t["id"] if t else None,
                            detalle=f"RFID {d.get('rfid')} estado {t['estado'] if t else 'sin turno'}")
            mqtt_bus.publicar(C.TOPICO_SRV_DECISION, "SALIDA_DENEGADA", {"rfid": d.get("rfid"),
                              "causa": "Vehículo sin turno en espera de salida"})
        return {"valido": valido}
    if tipo == "SALIDA_VERIFICADA" and not d.get("valido", True):
        alarmas.generar("AL10", origen=C.ORIGEN_CONTROLADOR, clave=d.get("rfid"), turno_id=t["id"] if t else None)
    if tipo == "VEHICULO_SALIO" and t:
        _ev(meta, "VEHICULO_SALIO", "El vehículo salió de la terminal", t["id"], d)
        if t["estado"] == C.T_EN_SALIDA:
            turnos.cerrar(t["id"])
        elif t["estado"] not in C.ESTADOS_TURNO_FINALES:
            _forzar_anulacion(t)       # regla 7.5
        db.ejecutar("UPDATE turnos SET estacion = 'FUERA' WHERE id = ?", (t["id"],))
        if t["tipo"] == C.TIPO_DEPOSITO:  # depósito anulado antes de descargar: el contenedor se va con el camión
            db.ejecutar("UPDATE contenedores SET ubicacion = 'FUERA' WHERE codigo = ? AND ubicacion = 'VEHICULO'",
                        (t["contenedor"],))
        return None
    _ev(meta, "SALIDA_" + tipo, f"Salida: {tipo}", t["id"] if t else None, d)
    return None


def _forzar_anulacion(t):
    motivo = "El vehículo salió de la terminal sin completar la operación"
    r = retenciones.abierta_de_turno(t["id"])
    if r:
        db.actualizar("retenciones", {"estado": C.RETENCION_RESUELTA, "resolucion": C.RES_RECHAZAR,
                                      "motivo": motivo, "resuelta_en": db.ahora()}, "id = ?", (r["id"],))
        plaza = parqueo.plaza_de_turno(t["id"])
        if plaza:
            parqueo.confirmar_liberacion(plaza)
    if C.T_ANULADO in C.TRANSICIONES_TURNO[t["estado"]]:
        turnos.anular(t["id"], motivo, origen=C.ORIGEN_SERVIDOR, desde_retencion=True)
    else:  # EnSalida sin pasar por cierre: se cierra
        turnos.cerrar(t["id"])


# ---------------------------------------------------------------------------
# ALARMAS del controlador, respuestas a comandos y latido
# ---------------------------------------------------------------------------
def _alarma(tipo, d, meta):
    codigo = d.get("codigo")
    t = _turno_de(d)
    if tipo == "ALARMA_CESADA":
        alarmas.cesar_condicion(codigo, d.get("clave"))
        _ev(meta, "ALARMA_CESADA", f"Cesa la condición de {codigo}", t["id"] if t else None, d)
        return None
    alarmas.generar(codigo, origen=C.ORIGEN_CONTROLADOR, datos=d, clave=d.get("clave"),
                    turno_id=t["id"] if t else None, detalle=d.get("detalle"))
    _ev(meta, "ALARMA_CONTROLADOR", f"Alarma {codigo} reportada por el controlador", t["id"] if t else None, d)
    return None


def _respuesta(tipo, d, meta):
    _ev(meta, "COMANDO_RESPUESTA_RECIBIDA", f"Respuesta a comando: {'aceptado' if d.get('aceptado') else 'rechazado'}",
        None, d)
    return comandos.registrar_respuesta(d, ts=meta["ts"])


def registrar_latido(tipo, d, seq=None):
    """LATIDO (cada <= 5 s) o ESTADO_REAL (al reconectar). Nunca se guarda como evento de turno."""
    with db.transaccion():
        ahora = db.ahora()
        db.guardar_estado("ultimo_latido", ahora)
        db.guardar_estado("ultimo_estado", db.a_json(d))
        if d.get("modo"):
            db.guardar_estado("modo", d["modo"])
        if seq is not None:
            _controlar_secuencia(seq)
        db.insertar("telemetria", {"seq": seq, "modo": d.get("modo"), "cola_espera": d.get("cola_espera"),
                                   "datos_json": db.a_json(d), "creado_en": ahora})
        if db.leer_estado("enlace") != C.ENLACE_CONECTADO:
            db.guardar_estado("enlace", C.ENLACE_CONECTADO)
            alarmas.cesar_condicion("AL01", "enlace")
            eventos.registrar("ENLACE_RESTABLECIDO", "Enlace con el controlador restablecido",
                              origen=C.ORIGEN_SERVIDOR, datos={"seq": seq})
            mqtt_bus.publicar(C.TOPICO_SRV_SISTEMA, "ENLACE", {"enlace": C.ENLACE_CONECTADO, "ultimo_latido": ahora})
        if tipo == "ESTADO_REAL" and d.get("patio"):
            reconciliar_patio(d["patio"])
    return None


def reconciliar_patio(lista):
    """Al reconectar, el controlador informa su patio real: [{"posicion":1,"n1":"CONT-001","n2":null}, ...].
    El estado FÍSICO manda: se corrige el inventario y cada diferencia genera AL07."""
    diferencias = []
    for p in lista:
        pos = int(p["posicion"])
        actual = db.uno("SELECT * FROM posiciones_patio WHERE numero = ?", (pos,))
        for nivel in (1, 2):
            real = p.get(f"n{nivel}")
            if actual and actual[f"contenedor_n{nivel}"] != real:
                diferencias.append({"posicion": pos, "nivel": nivel, "inventario": actual[f"contenedor_n{nivel}"],
                                    "real": real})
                if actual[f"contenedor_n{nivel}"]:
                    patio.aplicar_cambio({"posicion": pos, "nivel": nivel, "contenedor": actual[f"contenedor_n{nivel}"],
                                          "accion": "RETIRADO", "motivo": "RECONCILIACION"}, origen=C.ORIGEN_SERVIDOR)
                if real:
                    patio.aplicar_cambio({"posicion": pos, "nivel": nivel, "contenedor": real,
                                          "accion": "COLOCADO", "motivo": "RECONCILIACION"}, origen=C.ORIGEN_SERVIDOR)
    for dif in diferencias:
        alarmas.generar("AL07", clave=f"reconc-P{dif['posicion']}-{dif['nivel']}", datos=dif,
                        detalle=f"Reconciliación P{dif['posicion']}-{dif['nivel']}")
    eventos.registrar("RECONCILIACION", f"Reconciliación de patio: {len(diferencias)} diferencia(s)",
                      datos={"diferencias": diferencias})
    return diferencias


def verificar_enlace(periodo_s=C.LATIDO_PERIODO_S, perdidos=C.LATIDOS_PERDIDOS_PARA_ALARMA):
    """Tarea periódica: sin latido durante 3 periodos -> enlace perdido + AL01 + modo DEGRADADO."""
    ultimo = db.leer_estado("ultimo_latido")
    referencia = db.a_fecha(ultimo) if ultimo else db.a_fecha(db.leer_estado("servidor_iniciado", db.ahora()))
    if (datetime.now() - referencia).total_seconds() <= periodo_s * perdidos:
        return False
    if db.leer_estado("enlace") == C.ENLACE_DESCONECTADO:
        return False
    with db.transaccion():
        db.guardar_estado("enlace", C.ENLACE_DESCONECTADO)
        db.guardar_estado("modo", C.MODO_DEGRADADO)
        alarmas.generar("AL01", clave="enlace", detalle=f"último latido {ultimo or 'nunca'}")
        eventos.registrar("ENLACE_PERDIDO", "Enlace con el controlador perdido", datos={"ultimo_latido": ultimo})
        mqtt_bus.publicar(C.TOPICO_SRV_SISTEMA, "ENLACE", {"enlace": C.ENLACE_DESCONECTADO, "ultimo_latido": ultimo,
                                                            "modo": C.MODO_DEGRADADO})
    return True
