# -*- coding: utf-8 -*-
"""Vinculación del transportista con su cuenta de mensajería (sección 6.1)."""
import secrets
import string
from datetime import datetime, timedelta

from models import db
from models import constantes as C
from models.errores import Conflicto, ErrorPortus, NoEncontrado

_ALFABETO = string.ascii_uppercase + string.digits


def generar_codigo(transportista_id, usuario_id):
    """TERMINAL genera un código de 6 caracteres, de un solo uso, que expira en 60 minutos."""
    t = db.uno("SELECT * FROM transportistas WHERE id = ? OR codigo = ?", (transportista_id, str(transportista_id)))
    if not t:
        raise NoEncontrado("El transportista no existe.")
    ahora = datetime.now()
    for _ in range(10):
        codigo = "".join(secrets.choice(_ALFABETO) for _ in range(C.CODIGO_VINCULACION_LARGO))
        if not db.valor("SELECT 1 FROM codigos_vinculacion WHERE codigo = ?", (codigo,)):
            break
    db.insertar("codigos_vinculacion", {
        "codigo": codigo, "transportista_id": t["id"], "generado_por": usuario_id,
        "creado_en": db.texto_fecha(ahora),
        "expira_en": db.texto_fecha(ahora + timedelta(minutes=C.CODIGO_VINCULACION_EXPIRA_MIN))})
    return {"codigo": codigo, "transportista": t["codigo"], "transportista_nombre": t["nombre"],
            "expira_en": db.texto_fecha(ahora + timedelta(minutes=C.CODIGO_VINCULACION_EXPIRA_MIN))}


def vincular(chat_id, codigo):
    """Lo llama el bot con /vincular CODIGO. Devuelve el transportista vinculado."""
    chat_id = str(chat_id or "").strip()
    codigo = (codigo or "").strip().upper()
    if not chat_id:
        raise ErrorPortus("Falta el identificador de la cuenta de mensajería.")
    with db.transaccion():
        c = db.uno("SELECT * FROM codigos_vinculacion WHERE codigo = ?", (codigo,))
        if not c:
            raise ErrorPortus("Código de vinculación inválido.")
        if c["usado_en"]:
            raise Conflicto("El código de vinculación ya fue utilizado.")
        if db.a_fecha(c["expira_en"]) < datetime.now():
            raise Conflicto("El código de vinculación está vencido. Solicite uno nuevo al operador de terminal.")
        # Una cuenta de mensajería solo puede estar asociada a un transportista
        db.ejecutar("UPDATE transportistas SET chat_id = NULL, vinculado_en = NULL WHERE chat_id = ?", (chat_id,))
        db.ejecutar("UPDATE transportistas SET chat_id = ?, vinculado_en = ? WHERE id = ?",
                    (chat_id, db.ahora(), c["transportista_id"]))
        db.ejecutar("UPDATE codigos_vinculacion SET usado_en = ?, usado_por_chat = ? WHERE id = ?",
                    (db.ahora(), chat_id, c["id"]))
    return transportista_por_chat(chat_id)


def transportista_por_chat(chat_id):
    return db.uno("SELECT id, codigo, nombre, telefono, chat_id, vinculado_en FROM transportistas WHERE chat_id = ?",
                  (str(chat_id),))
