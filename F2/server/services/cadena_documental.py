# -*- coding: utf-8 -*-
"""
Cadena documental NAVIERA -> AGENTE -> AUTORIDAD (secciones 5.1 a 5.5).
Base entregada por el Compañero 1; el Compañero 3 es dueño de la lógica y puede
ampliarla aquí sin tocar rutas ni esquema.

Flujo del manifiesto (estado_documental):
  PENDIENTE_DECLARACION --presentar--> DECLARACION_PRESENTADA --solicitar--> LEVANTE_SOLICITADO
  LEVANTE_SOLICITADO --otorgar(canal)--> LEVANTE_OTORGADO
  LEVANTE_SOLICITADO --retener(motivo)--> LEVANTE_RETENIDO --(agente vuelve a solicitar | autoridad otorga)-->
"""
import sqlite3

from models import db
from models import constantes as C
from models.errores import Conflicto, ErrorPermiso, ErrorPortus, NoEncontrado
from services import eventos, notificaciones

_SELECT = """
    SELECT m.*, n.codigo AS naviera, n.nombre AS naviera_nombre, t.codigo AS transportista,
           t.nombre AS transportista_nombre,
           d.numero_declaracion, d.regimen, d.descripcion AS descripcion_mercancia, d.valor_declarado,
           (SELECT COUNT(*) FROM turnos WHERE manifiesto_id = m.id) AS turnos_asociados
    FROM manifiestos m
    JOIN navieras n ON n.id = m.naviera_id
    JOIN transportistas t ON t.id = m.transportista_id
    LEFT JOIN declaraciones d ON d.manifiesto_id = m.id
"""


def _historial(manifiesto_id, accion, usuario_id, campo=None, anterior=None, nuevo=None, comentario=None):
    db.insertar("manifiesto_historial", {
        "manifiesto_id": manifiesto_id, "accion": accion, "campo": campo,
        "valor_anterior": None if anterior is None else str(anterior),
        "valor_nuevo": None if nuevo is None else str(nuevo),
        "usuario_id": usuario_id, "comentario": comentario, "creado_en": db.ahora()})


def _entero_positivo(valor, nombre):
    try:
        v = int(str(valor).strip())
    except (TypeError, ValueError):
        raise ErrorPortus(f"{nombre} debe ser un número entero.")
    if v <= 0:
        raise ErrorPortus(f"{nombre} debe ser mayor que cero.")
    return v


# ---------------------------------------------------------------------------
# Consultas con alcance por rol
# ---------------------------------------------------------------------------
def obtener(manifiesto_id, usuario=None, alcance="S"):
    m = db.uno(_SELECT + " WHERE m.id = ?", (manifiesto_id,))
    if not m:
        raise NoEncontrado("El manifiesto no existe.")
    if alcance == "PROPIOS" and m["naviera_id"] != usuario["naviera_id"]:
        # Mismo mensaje que "no existe": no se revela información de otra naviera
        raise NoEncontrado("El manifiesto no existe.")
    return m


def detalle(manifiesto_id, usuario, alcance):
    m = obtener(manifiesto_id, usuario, alcance)
    m["historial"] = db.todos("""SELECT h.*, u.username AS usuario FROM manifiesto_historial h
                                 LEFT JOIN usuarios u ON u.id = h.usuario_id
                                 WHERE h.manifiesto_id = ? ORDER BY h.id""", (manifiesto_id,))
    m["solicitudes_levante"] = db.todos("SELECT * FROM solicitudes_levante WHERE manifiesto_id = ? ORDER BY id",
                                        (manifiesto_id,))
    m["observaciones_documentales"] = db.todos("""SELECT o.*, u.username AS usuario FROM observaciones_documentales o
                                                  JOIN usuarios u ON u.id = o.usuario_id
                                                  WHERE o.manifiesto_id = ? ORDER BY o.id""", (manifiesto_id,))
    return m


def listar(usuario, alcance, estado=None, contenedor=None):
    sql, params = _SELECT + " WHERE 1 = 1", []
    if alcance == "PROPIOS":
        sql += " AND m.naviera_id = ?"
        params.append(usuario["naviera_id"])
    if estado:
        sql += " AND m.estado_documental = ?"
        params.append(estado.upper())
    if contenedor:
        sql += " AND m.contenedor LIKE ?"
        params.append(f"%{contenedor}%")
    return db.todos(sql + " ORDER BY m.id DESC", params)


# ---------------------------------------------------------------------------
# NAVIERA
# ---------------------------------------------------------------------------
def crear_manifiesto(usuario, datos):
    contenedor = (datos.get("contenedor") or "").strip().upper()
    tipo = (datos.get("tipo") or "").strip().upper()
    if not contenedor:
        raise ErrorPortus("El identificador del contenedor es obligatorio.")
    cont = db.uno("SELECT * FROM contenedores WHERE codigo = ?", (contenedor,))
    if not cont:
        raise ErrorPortus(f"El contenedor {contenedor} no existe en el catálogo de contenedores de la maqueta.")
    if cont["naviera_id"] and cont["naviera_id"] != usuario["naviera_id"]:
        raise ErrorPermiso(f"El contenedor {contenedor} pertenece a otra naviera.")
    if tipo not in C.TIPOS_OPERACION:
        raise ErrorPortus("El tipo de operación es obligatorio: DEPOSITO o RETIRO.")
    peso = _entero_positivo(datos.get("peso_declarado_g", datos.get("peso_declarado")), "El peso declarado")
    tol = datos.get("tolerancia_pct", datos.get("tolerancia"))
    if tol in (None, ""):
        tol = C.TOLERANCIA_DEFECTO_PCT
    try:
        tol = float(tol)
    except (TypeError, ValueError):
        raise ErrorPortus("La tolerancia debe ser un número (porcentaje).")
    if tol < 0:
        raise ErrorPortus("La tolerancia no puede ser negativa.")
    tr = datos.get("transportista_id") or datos.get("transportista")
    transportista = db.uno("SELECT * FROM transportistas WHERE id = ? OR codigo = ?", (tr, str(tr or "")))
    if not transportista:
        raise ErrorPortus("El transportista asignado es obligatorio y debe ser uno de los registrados.")
    if tipo == C.TIPO_RETIRO and cont["ubicacion"] != "PATIO":
        raise ErrorPortus(f"No se puede declarar un retiro: el contenedor {contenedor} no está en el patio.")
    if tipo == C.TIPO_DEPOSITO and cont["ubicacion"] == "PATIO":
        raise ErrorPortus(f"No se puede declarar un depósito: el contenedor {contenedor} ya está en el patio.")

    pendiente = db.uno("""SELECT codigo FROM manifiestos WHERE contenedor = ? AND estado_documental <> 'ANULADO'
                          AND estado_operativo NOT IN ('COMPLETADO','ANULADO')""", (contenedor,))
    if pendiente:
        raise Conflicto(f"El contenedor {contenedor} ya tiene un manifiesto pendiente ({pendiente['codigo']}). "
                        "Un contenedor no puede tener dos manifiestos pendientes al mismo tiempo.")
    with db.transaccion():
        ahora = db.ahora()
        try:
            mid = db.insertar("manifiestos", {
                "contenedor": contenedor, "naviera_id": usuario["naviera_id"], "tipo": tipo,
                "peso_declarado_g": peso, "tolerancia_pct": tol, "transportista_id": transportista["id"],
                "observaciones": (datos.get("observaciones") or "").strip() or None,
                "creado_por": usuario["id"], "creado_en": ahora, "actualizado_en": ahora})
        except sqlite3.IntegrityError:
            raise Conflicto(f"El contenedor {contenedor} ya tiene un manifiesto pendiente.")
        db.ejecutar("UPDATE manifiestos SET codigo = ? WHERE id = ?", (f"MAN-{mid:04d}", mid))
        if not cont["naviera_id"]:
            db.ejecutar("UPDATE contenedores SET naviera_id = ? WHERE codigo = ?", (usuario["naviera_id"], contenedor))
        _historial(mid, "CREADO", usuario["id"], comentario=f"{tipo} {peso} g, tolerancia {tol}%")
    return obtener(mid)


def anular_manifiesto(usuario, manifiesto_id, motivo=None):
    with db.transaccion():
        m = obtener(manifiesto_id, usuario, "PROPIOS")
        if m["turnos_asociados"]:
            raise Conflicto("No se puede anular: el manifiesto ya tiene un turno asociado.")
        if m["estado_documental"] == C.DOC_ANULADO:
            raise Conflicto("El manifiesto ya está anulado.")
        db.actualizar("manifiestos", {"estado_documental": C.DOC_ANULADO, "estado_operativo": C.OP_ANULADO,
                                      "actualizado_en": db.ahora()}, "id = ?", (manifiesto_id,))
        citas = db.todos("SELECT * FROM citas WHERE manifiesto_id = ? AND estado = 'PROGRAMADA'", (manifiesto_id,))
        for c in citas:
            from services import citas as svc_citas
            svc_citas.cancelar(c["id"], usuario_id=usuario["id"], motivo="Manifiesto anulado por la naviera")
        _historial(manifiesto_id, "ANULADO", usuario["id"], comentario=motivo)
    return obtener(manifiesto_id)


# ---------------------------------------------------------------------------
# AGENTE
# ---------------------------------------------------------------------------
def pendientes_de_levante():
    """Pestaña Declaraciones: manifiestos de cualquier naviera que aún no cuentan con levante."""
    return db.todos(_SELECT + """ WHERE m.estado_documental IN
        ('PENDIENTE_DECLARACION','DECLARACION_PRESENTADA','LEVANTE_SOLICITADO','LEVANTE_RETENIDO')
        ORDER BY m.id DESC""")


def presentar_declaracion(usuario, manifiesto_id, datos):
    numero = (datos.get("numero_declaracion") or "").strip()
    regimen = (datos.get("regimen") or "").strip().upper()
    descripcion = (datos.get("descripcion") or "").strip()
    if not numero:
        raise ErrorPortus("El número de declaración es obligatorio.")
    if regimen not in C.REGIMENES:
        raise ErrorPortus("El régimen es obligatorio: IMPORTACION_DEFINITIVA o DEPOSITO_TEMPORAL.")
    if len(descripcion) < C.DESCRIPCION_MERCANCIA_MIN:
        raise ErrorPortus("La descripción de la mercancía debe tener al menos diez caracteres.")
    try:
        valor = float(datos.get("valor_declarado"))
    except (TypeError, ValueError):
        raise ErrorPortus("El valor declarado es obligatorio y numérico.")
    if valor <= 0:
        raise ErrorPortus("El valor declarado debe ser mayor que cero.")
    with db.transaccion():
        m = obtener(manifiesto_id)
        if m["estado_documental"] != C.DOC_PENDIENTE_DECLARACION:
            raise Conflicto(f"El manifiesto está en estado {m['estado_documental']}; la declaración ya fue presentada o no aplica.")
        if db.valor("SELECT 1 FROM declaraciones WHERE numero_declaracion = ?", (numero,)):
            raise Conflicto(f"El número de declaración {numero} ya existe en el sistema.")
        db.insertar("declaraciones", {"manifiesto_id": manifiesto_id, "numero_declaracion": numero,
                                      "regimen": regimen, "descripcion": descripcion, "valor_declarado": valor,
                                      "agente_id": usuario["id"], "presentada_en": db.ahora()})
        db.actualizar("manifiestos", {"estado_documental": C.DOC_DECLARACION_PRESENTADA,
                                      "actualizado_en": db.ahora()}, "id = ?", (manifiesto_id,))
        _historial(manifiesto_id, "DECLARACION_PRESENTADA", usuario["id"], comentario=numero)
    return obtener(manifiesto_id)


def solicitar_levante(usuario, manifiesto_id):
    with db.transaccion():
        m = obtener(manifiesto_id)
        if m["estado_documental"] not in (C.DOC_DECLARACION_PRESENTADA, C.DOC_LEVANTE_RETENIDO):
            raise Conflicto("Solo puede solicitarse el levante cuando la declaración ya fue presentada.")
        sid = db.insertar("solicitudes_levante", {"manifiesto_id": manifiesto_id, "agente_id": usuario["id"],
                                                  "solicitado_en": db.ahora()})
        db.actualizar("manifiestos", {"estado_documental": C.DOC_LEVANTE_SOLICITADO,
                                      "actualizado_en": db.ahora()}, "id = ?", (manifiesto_id,))
        _historial(manifiesto_id, "LEVANTE_SOLICITADO", usuario["id"], comentario=f"Solicitud {sid}")
    return obtener_solicitud(sid)


def agregar_observacion(usuario, manifiesto_id, texto):
    texto = (texto or "").strip()
    if not texto:
        raise ErrorPortus("La observación no puede estar vacía.")
    obtener(manifiesto_id)
    oid = db.insertar("observaciones_documentales", {"manifiesto_id": manifiesto_id, "usuario_id": usuario["id"],
                                                     "texto": texto, "creado_en": db.ahora()})
    return db.uno("SELECT * FROM observaciones_documentales WHERE id = ?", (oid,))


def seguimiento(usuario, estado=None, numero=None):
    """Pestaña Seguimiento del agente: sus solicitudes con estado, canal y motivo."""
    sql = """SELECT s.*, m.codigo AS manifiesto, m.contenedor, n.codigo AS naviera, d.numero_declaracion
             FROM solicitudes_levante s JOIN manifiestos m ON m.id = s.manifiesto_id
             JOIN navieras n ON n.id = m.naviera_id LEFT JOIN declaraciones d ON d.manifiesto_id = m.id
             WHERE s.agente_id = ?"""
    params = [usuario["id"]]
    if estado:
        sql += " AND s.estado = ?"
        params.append(estado.upper())
    if numero:
        sql += " AND d.numero_declaracion LIKE ?"
        params.append(f"%{numero}%")
    return db.todos(sql + " ORDER BY s.id DESC", params)


# ---------------------------------------------------------------------------
# AUTORIDAD
# ---------------------------------------------------------------------------
_SELECT_SOL = """
    SELECT s.*, m.codigo AS manifiesto, m.contenedor, m.tipo, m.peso_declarado_g, m.transportista_id,
           n.codigo AS naviera, u.nombre AS agente, d.numero_declaracion, d.regimen,
           d.descripcion AS descripcion_mercancia, d.valor_declarado
    FROM solicitudes_levante s
    JOIN manifiestos m ON m.id = s.manifiesto_id
    JOIN navieras n ON n.id = m.naviera_id
    JOIN usuarios u ON u.id = s.agente_id
    LEFT JOIN declaraciones d ON d.manifiesto_id = m.id
"""


def obtener_solicitud(sid):
    s = db.uno(_SELECT_SOL + " WHERE s.id = ?", (sid,))
    if not s:
        raise NoEncontrado("La solicitud de levante no existe.")
    return s


def solicitudes(estado=C.LEVANTE_PENDIENTE):
    if estado == "TODAS":
        return db.todos(_SELECT_SOL + " ORDER BY s.id DESC")
    return db.todos(_SELECT_SOL + " WHERE s.estado = ? ORDER BY s.id", (estado,))


def otorgar_levante(usuario, sid, canal):
    canal = (canal or "").strip().upper()
    if canal not in C.CANALES:
        raise ErrorPortus("Debe seleccionar el canal de selectivo (VERDE o ROJO) antes de otorgar el levante.")
    with db.transaccion():
        s = obtener_solicitud(sid)
        if s["estado"] == C.LEVANTE_OTORGADO:
            raise Conflicto("El levante ya fue otorgado.")
        db.actualizar("solicitudes_levante", {"estado": C.LEVANTE_OTORGADO, "canal": canal,
                                              "resuelto_por": usuario["id"], "resuelto_en": db.ahora()},
                      "id = ?", (sid,))
        db.actualizar("manifiestos", {"estado_documental": C.DOC_LEVANTE_OTORGADO, "canal": canal,
                                      "motivo_retencion": None, "actualizado_en": db.ahora()},
                      "id = ?", (s["manifiesto_id"],))
        _historial(s["manifiesto_id"], "LEVANTE_OTORGADO", usuario["id"], "canal", None, canal)
        eventos.registrar("LEVANTE_OTORGADO", f"Levante otorgado a {s['manifiesto']} con canal {canal}",
                          origen=C.ORIGEN_USUARIO, usuario_id=usuario["id"],
                          datos={"manifiesto": s["manifiesto"], "canal": canal})
        notificaciones.notificar(s["transportista_id"], C.NOTIF_LEVANTE_OTORGADO,
                                 {"contenedor": s["contenedor"], "canal": canal, "manifiesto": s["manifiesto"]})
    return obtener_solicitud(sid)


def retener_levante(usuario, sid, motivo):
    motivo = (motivo or "").strip()
    if not motivo:
        raise ErrorPortus("Debe indicar la causa de la retención del levante.")
    with db.transaccion():
        s = obtener_solicitud(sid)
        if s["estado"] != C.LEVANTE_PENDIENTE:
            raise Conflicto(f"La solicitud ya fue resuelta ({s['estado']}).")
        db.actualizar("solicitudes_levante", {"estado": C.LEVANTE_RETENIDO, "motivo": motivo,
                                              "resuelto_por": usuario["id"], "resuelto_en": db.ahora()},
                      "id = ?", (sid,))
        db.actualizar("manifiestos", {"estado_documental": C.DOC_LEVANTE_RETENIDO, "canal": None,
                                      "motivo_retencion": motivo, "actualizado_en": db.ahora()},
                      "id = ?", (s["manifiesto_id"],))
        _historial(s["manifiesto_id"], "LEVANTE_RETENIDO", usuario["id"], comentario=motivo)
        notificaciones.notificar(s["transportista_id"], C.NOTIF_LEVANTE_RETENIDO,
                                 {"contenedor": s["contenedor"], "motivo": motivo, "manifiesto": s["manifiesto"]})
    return obtener_solicitud(sid)
