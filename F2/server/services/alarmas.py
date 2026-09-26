# -*- coding: utf-8 -*-
"""
Alarmas (4.6). Regla: una alarma NO desaparece sola al cesar la condición;
queda activa hasta que un usuario la reconoce. `cesar_condicion` solo marca
condicion_activa = 0 para información.
"""
from models import db
from models import constantes as C
from models.errores import Conflicto, ErrorPortus, NoEncontrado
from services import eventos, mqtt_bus


def generar(codigo, origen=C.ORIGEN_SERVIDOR, datos=None, clave=None, turno_id=None, detalle=None):
    """Crea la alarma. Si ya hay una ACTIVA (no reconocida) con el mismo código y clave, no la duplica.
    Devuelve el id de la alarma nueva o None si se omitió."""
    if codigo not in C.ALARMAS:
        raise ErrorPortus(f"Código de alarma desconocido: {codigo}")
    clave = None if clave is None else str(clave)
    existente = db.valor("SELECT id FROM alarmas WHERE codigo = ? AND reconocida = 0 AND IFNULL(clave,'') = IFNULL(?, '')",
                         (codigo, clave))
    if existente:
        db.ejecutar("UPDATE alarmas SET condicion_activa = 1 WHERE id = ?", (existente,))
        return None
    descripcion, severidad = C.ALARMAS[codigo]
    if detalle:
        descripcion = f"{descripcion}: {detalle}"
    aid = db.insertar("alarmas", {
        "codigo": codigo, "severidad": severidad, "origen": origen, "descripcion": descripcion,
        "clave": clave, "datos_json": db.a_json(datos), "turno_id": turno_id, "creada_en": db.ahora(),
    })
    eventos.registrar("ALARMA", f"Alarma {codigo}: {descripcion}", origen=origen, turno_id=turno_id,
                      datos={"alarma_id": aid, "codigo": codigo, "severidad": severidad, **(datos or {})})
    mqtt_bus.publicar(C.TOPICO_SRV_ALARMA, "ALARMA_NUEVA", obtener(aid))
    return aid


def cesar_condicion(codigo, clave=None):
    db.ejecutar("UPDATE alarmas SET condicion_activa = 0 WHERE codigo = ? AND IFNULL(clave,'') = IFNULL(?, '')",
                (codigo, None if clave is None else str(clave)))


def obtener(alarma_id):
    a = db.uno("SELECT * FROM alarmas WHERE id = ?", (alarma_id,))
    if a:
        a["datos"] = db.de_json(a.pop("datos_json"))
        a["estado_reconocimiento"] = "RECONOCIDA" if a["reconocida"] else "SIN_RECONOCER"
    return a


def listar(estado="activas", severidad=None):
    sql = "SELECT id FROM alarmas WHERE reconocida = ?"
    params = [0 if estado == "activas" else 1]
    if severidad:
        sql += " AND severidad = ?"
        params.append(severidad.upper())
    sql += " ORDER BY creada_en DESC, id DESC"
    return [obtener(f["id"]) for f in db.todos(sql, params)]


def reconocer(alarma_id, usuario_id, comentario=None):
    with db.transaccion():
        a = obtener(alarma_id)
        if not a:
            raise NoEncontrado("La alarma no existe.")
        if a["reconocida"]:
            raise Conflicto("La alarma ya fue reconocida.")
        db.actualizar("alarmas", {"reconocida": 1, "reconocida_por": usuario_id, "reconocida_en": db.ahora(),
                                  "comentario": comentario}, "id = ?", (alarma_id,))
        eventos.registrar("ALARMA_RECONOCIDA", f"Alarma {a['codigo']} reconocida", origen=C.ORIGEN_USUARIO,
                          turno_id=a["turno_id"], usuario_id=usuario_id,
                          datos={"alarma_id": alarma_id, "comentario": comentario})
        mqtt_bus.publicar(C.TOPICO_SRV_ALARMA, "ALARMA_RECONOCIDA", obtener(alarma_id))
    return obtener(alarma_id)


def reconocer_todas(usuario_id, comentario=None):
    """Solo severidad BAJA y MEDIA. CRÍTICAS y ALTAS se reconocen una por una."""
    ids = [f["id"] for f in db.todos(
        "SELECT id FROM alarmas WHERE reconocida = 0 AND severidad IN (?, ?)", C.SEVERIDADES_RECONOCER_TODAS)]
    with db.transaccion():
        for aid in ids:
            reconocer(aid, usuario_id, comentario)
    return ids
