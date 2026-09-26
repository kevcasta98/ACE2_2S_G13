# -*- coding: utf-8 -*-
"""
Notificaciones automáticas al transportista (sección 6.3).

El servidor NO envía mensajes a Telegram/WhatsApp directamente: escribe en la
tabla `notificaciones` (bandeja de salida) y publica un aviso en
portus/srv/notificacion. El bot (Compañero 4) lee las pendientes, las envía al
chat_id del transportista y las marca como ENVIADA. Cada aviso va SOLO al
transportista propietario de la carga (se guarda su transportista_id).
"""
from models import db
from models import constantes as C
from services import mqtt_bus


def _formato_peso(g):
    return "-" if g is None else f"{int(g)} g"


def _texto(tipo, d):
    cont = d.get("contenedor", "-")
    if tipo == C.NOTIF_LEVANTE_OTORGADO:
        t = f"Levante OTORGADO para el contenedor {cont}. Canal asignado: {d.get('canal')}."
        if d.get("canal") == C.CANAL_ROJO:
            t += " Canal ROJO: el vehículo será enviado a verificación (parqueo de retención) después del pesaje de entrada."
        return t
    if tipo == C.NOTIF_LEVANTE_RETENIDO:
        return f"Levante RETENIDO para el contenedor {cont}. Motivo: {d.get('motivo')}."
    if tipo == C.NOTIF_CITA_ASIGNADA:
        return f"Cita asignada. Contenedor {cont}, fecha {d.get('fecha')}, ventana {d.get('hora_inicio')} - {d.get('hora_fin')}."
    if tipo == C.NOTIF_CITA_RECORDATORIO:
        return f"Recordatorio: su ventana para el contenedor {cont} es hoy {d.get('fecha')} de {d.get('hora_inicio')} a {d.get('hora_fin')}."
    if tipo == C.NOTIF_VEHICULO_RETENIDO:
        t = f"Vehículo {d.get('vehiculo')} RETENIDO. Contenedor {cont}. Causa: {d.get('causa')} - {d.get('causa_descripcion')}."
        if d.get("causa") in C.CAUSAS_DE_PESO:
            t += (f" Peso declarado: {_formato_peso(d.get('peso_declarado_g'))}, medido: "
                  f"{_formato_peso(d.get('peso_medido_g'))}, diferencia: {_formato_peso(d.get('diferencia_g'))}"
                  f" ({d.get('diferencia_pct')}%).")
        return t
    if tipo == C.NOTIF_RETENCION_RESUELTA:
        t = f"Retención resuelta. Vehículo {d.get('vehiculo')}, contenedor {cont}. Resolución: {d.get('resolucion')}."
        if d.get("resolucion") == C.RES_CORREGIR:
            t += f" Nuevo peso declarado: {_formato_peso(d.get('peso_nuevo_g'))}."
        if d.get("resolucion") == C.RES_RECHAZAR:
            t += f" Motivo: {d.get('motivo')}."
        return t
    if tipo == C.NOTIF_CITA_MODIFICADA:
        if d.get("situacion") == "REPROGRAMADA":
            return (f"Su cita del contenedor {cont} fue REPROGRAMADA. Nueva ventana: {d.get('fecha')} "
                    f"{d.get('hora_inicio')} - {d.get('hora_fin')}.")
        return f"Su cita del contenedor {cont} fue CANCELADA." + (f" Motivo: {d['motivo']}." if d.get("motivo") else "")
    if tipo == C.NOTIF_TURNO_CERRADO:
        return (f"Turno cerrado. Vehículo {d.get('vehiculo')}, contenedor {cont}, operación {d.get('tipo')}. "
                f"Tiempo total en terminal: {d.get('tiempo_total')}.")
    if tipo == C.NOTIF_TURNO_ANULADO:
        return f"Turno ANULADO. Vehículo {d.get('vehiculo')}, contenedor {cont}." + (
            f" Causa: {d['motivo']}." if d.get("motivo") else "")
    return str(d)


def notificar(transportista_id, tipo, datos):
    """Encola una notificación para el transportista dueño de la carga."""
    if tipo not in C.NOTIFICACIONES:
        raise ValueError(f"Tipo de notificación desconocido: {tipo}")
    mensaje = _texto(tipo, datos)
    nid = db.insertar("notificaciones", {
        "transportista_id": transportista_id, "tipo": tipo, "mensaje": mensaje,
        "datos_json": db.a_json(datos), "creado_en": db.ahora(),
    })
    mqtt_bus.publicar(C.TOPICO_SRV_NOTIFICACION, "NOTIFICACION_NUEVA",
                      {"notificacion_id": nid, "transportista_id": transportista_id, "tipo": tipo})
    return nid


def pendientes(limite=50):
    """Pendientes con el chat_id destino (NULL si el transportista aún no se vinculó)."""
    filas = db.todos("""
        SELECT n.id, n.tipo, n.mensaje, n.datos_json, n.intentos, n.creado_en,
               t.id AS transportista_id, t.codigo AS transportista, t.chat_id
        FROM notificaciones n JOIN transportistas t ON t.id = n.transportista_id
        WHERE n.estado IN ('PENDIENTE','ERROR') AND n.intentos < 5
        ORDER BY n.id LIMIT ?""", (limite,))
    for f in filas:
        f["datos"] = db.de_json(f.pop("datos_json"))
    return filas


def marcar_enviada(nid):
    db.ejecutar("UPDATE notificaciones SET estado = 'ENVIADA', enviado_en = ?, intentos = intentos + 1 WHERE id = ?",
                (db.ahora(), nid))


def marcar_error(nid, error):
    db.ejecutar("UPDATE notificaciones SET estado = 'ERROR', error = ?, intentos = intentos + 1 WHERE id = ?",
                (str(error)[:500], nid))
