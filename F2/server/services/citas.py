# -*- coding: utf-8 -*-
"""
Programación de citas (sección 9).
  * Franjas de 15 minutos, máximo 2 citas por franja.
  * Solo contenedores con levante otorgado; una cita vigente por contenedor.
  * Franja llena o bloqueada no se ofrece; se ofrece la siguiente con capacidad.
  * Dentro de ventana = entre el inicio de la franja y fin + 5 minutos.
"""
import sqlite3
from datetime import datetime, timedelta

from models import db
from models import constantes as C
from models.errores import Conflicto, ErrorPortus, NoEncontrado
from services import eventos, notificaciones

_apertura_min = 0          # minutos desde medianoche en que abre la agenda
_cierre_min = 24 * 60      # minutos desde medianoche en que cierra


def configurar_horario(apertura_min, cierre_min):
    global _apertura_min, _cierre_min
    _apertura_min, _cierre_min = int(apertura_min), int(cierre_min)


def asegurar_franjas(fecha):
    """Crea (si no existen) las franjas del día. `fecha` = 'YYYY-MM-DD'."""
    if db.valor("SELECT 1 FROM franjas WHERE fecha = ? LIMIT 1", (fecha,)):
        return
    base = datetime.strptime(fecha, "%Y-%m-%d")
    with db.transaccion():
        m = _apertura_min
        while m + C.FRANJA_MINUTOS <= _cierre_min:
            ini = base + timedelta(minutes=m)
            fin = ini + timedelta(minutes=C.FRANJA_MINUTOS)
            db.ejecutar("""INSERT OR IGNORE INTO franjas (fecha, hora_inicio, hora_fin, inicio, fin, capacidad)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (fecha, ini.strftime("%H:%M"), fin.strftime("%H:%M"), db.texto_fecha(ini),
                         db.texto_fecha(fin), C.CAPACIDAD_FRANJA))
            m += C.FRANJA_MINUTOS


_SELECT_CITA = """
    SELECT c.*, f.fecha, f.hora_inicio, f.hora_fin, f.inicio, f.fin, t.codigo AS transportista,
           t.nombre AS transportista_nombre, m.codigo AS manifiesto, m.tipo,
           (SELECT v.placa FROM turnos tu JOIN vehiculos v ON v.id = tu.vehiculo_id WHERE tu.cita_id = c.id
            ORDER BY tu.id DESC LIMIT 1) AS vehiculo
    FROM citas c
    JOIN franjas f ON f.id = c.franja_id
    JOIN transportistas t ON t.id = c.transportista_id
    JOIN manifiestos m ON m.id = c.manifiesto_id
"""


def obtener(cita_id):
    c = db.uno(_SELECT_CITA + " WHERE c.id = ?", (cita_id,))
    if not c:
        raise NoEncontrado("La cita no existe.")
    return c


def _ocupadas(franja_id):
    return db.valor("SELECT COUNT(*) FROM citas WHERE franja_id = ? AND estado <> 'CANCELADA'", (franja_id,))


def agenda(fecha):
    asegurar_franjas(fecha)
    franjas = db.todos("SELECT * FROM franjas WHERE fecha = ? ORDER BY hora_inicio", (fecha,))
    citas = db.todos(_SELECT_CITA + " WHERE f.fecha = ? ORDER BY f.hora_inicio, c.id", (fecha,))
    por_franja = {}
    for c in citas:
        por_franja.setdefault(c["franja_id"], []).append(c)
    for f in franjas:
        f["citas"] = por_franja.get(f["id"], [])
        f["asignadas"] = len([c for c in f["citas"] if c["estado"] != C.CITA_CANCELADA])
        f["disponible"] = not f["bloqueada"] and f["asignadas"] < f["capacidad"]
    return {"fecha": fecha, "franjas": franjas, "cumplimiento": cumplimiento(fecha)}


def franjas_disponibles(cantidad=C.FRANJAS_A_OFRECER, desde=None, excluir_franja=None):
    """Próximas franjas con capacidad (no bloqueadas, cuyo fin aún no pasa)."""
    desde = desde or datetime.now()
    resultado = []
    for dia in range(0, 8):
        fecha = (desde + timedelta(days=dia)).strftime("%Y-%m-%d")
        asegurar_franjas(fecha)
        for f in db.todos("""SELECT f.*, (SELECT COUNT(*) FROM citas c WHERE c.franja_id = f.id AND c.estado <> 'CANCELADA') AS asignadas
                             FROM franjas f WHERE f.fecha = ? AND f.fin > ? AND f.bloqueada = 0
                             ORDER BY f.inicio""", (fecha, db.texto_fecha(desde))):
            if f["asignadas"] < f["capacidad"] and f["id"] != excluir_franja:
                resultado.append(f)
                if len(resultado) >= cantidad:
                    return resultado
    return resultado


def contenedores_para_cita(transportista_id):
    """Contenedores del transportista con levante otorgado y sin cita (comando /cita)."""
    return db.todos("""SELECT m.id AS manifiesto_id, m.codigo AS manifiesto, m.contenedor, m.tipo, m.canal
                       FROM manifiestos m
                       WHERE m.transportista_id = ? AND m.estado_documental = 'LEVANTE_OTORGADO'
                         AND m.estado_operativo = 'SIN_CITA'
                         AND NOT EXISTS (SELECT 1 FROM citas c WHERE c.manifiesto_id = m.id AND c.estado = 'PROGRAMADA')
                       ORDER BY m.id""", (transportista_id,))


def solicitar(transportista_id, contenedor, franja_id):
    contenedor = (contenedor or "").strip().upper()
    with db.transaccion():
        m = db.uno("""SELECT * FROM manifiestos WHERE contenedor = ? AND transportista_id = ?
                      AND estado_documental <> 'ANULADO' AND estado_operativo NOT IN ('COMPLETADO','ANULADO')""",
                   (contenedor, transportista_id))
        if not m:
            raise NoEncontrado("No tiene carga asociada a ese identificador.")
        if m["estado_documental"] != C.DOC_LEVANTE_OTORGADO:
            raise Conflicto(f"El contenedor {contenedor} aún no cuenta con levante otorgado.")
        if db.valor("SELECT 1 FROM citas WHERE contenedor = ? AND estado = 'PROGRAMADA'", (contenedor,)):
            raise Conflicto(f"El contenedor {contenedor} ya tiene una cita vigente.")
        f = db.uno("SELECT * FROM franjas WHERE id = ?", (franja_id,))
        if not f:
            raise NoEncontrado("La franja no existe.")
        if f["bloqueada"]:
            raise Conflicto("La franja está bloqueada.")
        if db.a_fecha(f["fin"]) <= datetime.now():
            raise Conflicto("La franja ya pasó.")
        if _ocupadas(franja_id) >= f["capacidad"]:
            raise Conflicto("La franja ya está llena; elija otra.")
        ahora = db.ahora()
        try:
            cid = db.insertar("citas", {"manifiesto_id": m["id"], "contenedor": contenedor,
                                        "transportista_id": transportista_id, "franja_id": franja_id,
                                        "creado_en": ahora, "actualizado_en": ahora})
        except sqlite3.IntegrityError:
            raise Conflicto(f"El contenedor {contenedor} ya tiene una cita vigente.")
        db.ejecutar("UPDATE citas SET codigo = ? WHERE id = ?", (f"CITA-{cid:04d}", cid))
        db.actualizar("manifiestos", {"estado_operativo": C.OP_CITA_PROGRAMADA, "actualizado_en": ahora},
                      "id = ?", (m["id"],))
        c = obtener(cid)
        eventos.registrar("CITA_ASIGNADA", f"Cita {c['codigo']} {c['fecha']} {c['hora_inicio']}-{c['hora_fin']}",
                          origen=C.ORIGEN_USUARIO, datos={"cita": c["codigo"], "contenedor": contenedor})
        notificaciones.notificar(transportista_id, C.NOTIF_CITA_ASIGNADA, {
            "contenedor": contenedor, "fecha": c["fecha"], "hora_inicio": c["hora_inicio"],
            "hora_fin": c["hora_fin"], "cita": c["codigo"]})
    return c


def de_transportista(transportista_id, dias_atras=7):
    """/miscitas: citas recientes y futuras con su estado."""
    limite = (datetime.now() - timedelta(days=dias_atras)).strftime("%Y-%m-%d")
    return db.todos(_SELECT_CITA + " WHERE c.transportista_id = ? AND f.fecha >= ? ORDER BY f.inicio",
                    (transportista_id, limite))


def cancelar(cita_id, usuario_id=None, motivo=None):
    with db.transaccion():
        c = obtener(cita_id)
        if c["estado"] != C.CITA_PROGRAMADA:
            raise Conflicto(f"Solo se puede cancelar una cita programada (estado actual: {c['estado']}).")
        db.actualizar("citas", {"estado": C.CITA_CANCELADA, "motivo_cancelacion": motivo,
                                "actualizado_en": db.ahora()}, "id = ?", (cita_id,))
        db.ejecutar("""UPDATE manifiestos SET estado_operativo = 'SIN_CITA', actualizado_en = ?
                       WHERE id = ? AND estado_operativo = 'CITA_PROGRAMADA'""", (db.ahora(), c["manifiesto_id"]))
        notificaciones.notificar(c["transportista_id"], C.NOTIF_CITA_MODIFICADA, {
            "contenedor": c["contenedor"], "situacion": "CANCELADA", "motivo": motivo, "cita": c["codigo"]})
    return obtener(cita_id)


def reprogramar(cita_id, franja_id, usuario_id=None):
    with db.transaccion():
        c = obtener(cita_id)
        if c["estado"] != C.CITA_PROGRAMADA:
            raise Conflicto("Solo se puede reprogramar una cita programada.")
        f = db.uno("SELECT * FROM franjas WHERE id = ?", (franja_id,))
        if not f:
            raise NoEncontrado("La franja destino no existe.")
        if f["bloqueada"] or _ocupadas(franja_id) >= f["capacidad"]:
            raise Conflicto("La franja destino no tiene capacidad disponible.")
        if db.a_fecha(f["fin"]) <= datetime.now():
            raise Conflicto("La franja destino ya pasó.")
        db.actualizar("citas", {"franja_id": franja_id, "recordatorio_enviado": 0, "actualizado_en": db.ahora()},
                      "id = ?", (cita_id,))
        n = obtener(cita_id)
        notificaciones.notificar(c["transportista_id"], C.NOTIF_CITA_MODIFICADA, {
            "contenedor": c["contenedor"], "situacion": "REPROGRAMADA", "fecha": n["fecha"],
            "hora_inicio": n["hora_inicio"], "hora_fin": n["hora_fin"], "cita": c["codigo"]})
    return n


def bloquear_franja(franja_id, bloquear=True):
    if not db.uno("SELECT id FROM franjas WHERE id = ?", (franja_id,)):
        raise NoEncontrado("La franja no existe.")
    db.ejecutar("UPDATE franjas SET bloqueada = ? WHERE id = ?", (1 if bloquear else 0, franja_id))
    return db.uno("SELECT * FROM franjas WHERE id = ?", (franja_id,))


def evaluar_ventana(cita, momento=None):
    """True si `momento` está entre el inicio de la franja y fin + 5 minutos."""
    momento = momento or datetime.now()
    inicio = db.a_fecha(cita["inicio"])
    limite = db.a_fecha(cita["fin"]) + timedelta(minutes=C.GRACIA_VENTANA_MIN)
    return inicio <= momento <= limite


def registrar_llegada(cita_id, dentro):
    db.actualizar("citas", {"estado": C.CITA_CUMPLIDA, "llegada_en": db.ahora(), "dentro_ventana": 1 if dentro else 0,
                            "actualizado_en": db.ahora()}, "id = ?", (cita_id,))


def cumplimiento(fecha_desde, fecha_hasta=None):
    """% de citas cumplidas dentro de su ventana sobre el total (sin contar canceladas)."""
    fecha_hasta = fecha_hasta or fecha_desde
    fila = db.uno("""SELECT COUNT(*) AS total, SUM(CASE WHEN c.dentro_ventana = 1 THEN 1 ELSE 0 END) AS en_ventana
                     FROM citas c JOIN franjas f ON f.id = c.franja_id
                     WHERE f.fecha BETWEEN ? AND ? AND c.estado <> 'CANCELADA'""",
                  (fecha_desde[:10], fecha_hasta[:10]))
    total, ok = fila["total"] or 0, fila["en_ventana"] or 0
    return {"total": total, "cumplidas_en_ventana": ok, "porcentaje": round(100.0 * ok / total, 1) if total else 0.0}


def vencer_citas():
    """Citas programadas cuya ventana (fin + 5 min) ya pasó -> VENCIDA; el manifiesto puede pedir otra cita."""
    limite = db.texto_fecha(datetime.now() - timedelta(minutes=C.GRACIA_VENTANA_MIN))
    vencidas = db.todos("""SELECT c.id, c.manifiesto_id FROM citas c JOIN franjas f ON f.id = c.franja_id
                           WHERE c.estado = 'PROGRAMADA' AND f.fin < ?""", (limite,))
    with db.transaccion():
        for v in vencidas:
            db.actualizar("citas", {"estado": C.CITA_VENCIDA, "actualizado_en": db.ahora()}, "id = ?", (v["id"],))
            db.ejecutar("""UPDATE manifiestos SET estado_operativo = 'SIN_CITA' WHERE id = ?
                           AND estado_operativo = 'CITA_PROGRAMADA'""", (v["manifiesto_id"],))
    return len(vencidas)


def enviar_recordatorios():
    """Aviso cuando falta una hora (o menos) para la ventana asignada."""
    ahora = datetime.now()
    filas = db.todos(_SELECT_CITA + """ WHERE c.estado = 'PROGRAMADA' AND c.recordatorio_enviado = 0
                                        AND f.inicio > ? AND f.inicio <= ?""",
                     (db.texto_fecha(ahora), db.texto_fecha(ahora + timedelta(minutes=C.RECORDATORIO_MIN))))
    with db.transaccion():
        for c in filas:
            notificaciones.notificar(c["transportista_id"], C.NOTIF_CITA_RECORDATORIO, {
                "contenedor": c["contenedor"], "fecha": c["fecha"], "hora_inicio": c["hora_inicio"],
                "hora_fin": c["hora_fin"], "cita": c["codigo"]})
            db.ejecutar("UPDATE citas SET recordatorio_enviado = 1 WHERE id = ?", (c["id"],))
    return len(filas)
