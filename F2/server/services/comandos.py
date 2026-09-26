# -*- coding: utf-8 -*-
"""
Comandos remotos (sección 11). El servidor solo valida permisos y parámetros;
quien decide si es seguro es el CONTROLADOR, que responde en portus/cmd/respuesta:

    publicado por el servidor en portus/cmd/solicitud:
        {"id": "<uuid>", "tipo": "GruaSuspender", "origen": "usuario", "ts": ..., "datos": {"comando": "GruaSuspender", "parametros": {}}}
    respuesta del controlador en portus/cmd/respuesta:
        {"id": "<otro uuid>", "tipo": "COMANDO_RESPUESTA", "origen": "controlador", "seq": n,
         "datos": {"comando_id": "<uuid de la solicitud>", "aceptado": false, "causa": "Hay un vehículo bajo la talanquera"}}

Un rechazo se muestra al usuario con la causa exacta y genera AL14.
"""
from models import db
from models import constantes as C
from models.errores import ErrorPortus, NoEncontrado
from services import alarmas, eventos, mqtt_bus


def _validar_parametros(comando, p):
    p = dict(p or {})
    if comando in ("PosicionBloquear", "PosicionLiberar"):
        try:
            p["posicion"] = int(p.get("posicion"))
        except (TypeError, ValueError):
            raise ErrorPortus("Debe indicar la posición del patio (1 a %d)." % C.POSICIONES_PATIO)
        if not 1 <= p["posicion"] <= C.POSICIONES_PATIO:
            raise ErrorPortus("Posición de patio fuera de rango.")
    if comando == "ModoMantenimiento":
        v = p.get("activar")
        if isinstance(v, str):
            v = v.lower() in ("1", "true", "si", "sí", "activar")
        if v is None:
            raise ErrorPortus("Debe indicar activar = true o false.")
        p["activar"] = bool(v)
    if comando == "AgujaLiberar" and p.get("plaza") is not None:
        p["plaza"] = int(p["plaza"])
        if not 1 <= p["plaza"] <= C.PLAZAS_PARQUEO:
            raise ErrorPortus("Plaza de parqueo fuera de rango.")
    return p


def emitir(comando, parametros=None, usuario_id=None, turno_id=None):
    """Registra y publica el comando. Devuelve el registro (estado ENVIADO)."""
    if comando not in C.COMANDOS:
        raise ErrorPortus(f"Comando desconocido: {comando}. Válidos: {', '.join(C.COMANDOS)}")
    parametros = _validar_parametros(comando, parametros)
    origen = C.ORIGEN_USUARIO if usuario_id else C.ORIGEN_SERVIDOR
    with db.transaccion():
        msg = mqtt_bus.publicar(C.TOPICO_CMD_SOLICITUD, comando,
                                {"comando": comando, "parametros": parametros}, origen=origen)
        cid = db.insertar("comandos", {
            "mensaje_id": msg["id"], "comando": comando, "parametros_json": db.a_json(parametros),
            "usuario_id": usuario_id, "enviado_en": db.ahora(),
        })
        eventos.registrar("COMANDO_ENVIADO", f"Comando {comando} enviado al controlador", origen=origen,
                          turno_id=turno_id, usuario_id=usuario_id,
                          datos={"comando_id": msg["id"], "parametros": parametros})
    return obtener(cid)


def obtener(cid=None, mensaje_id=None):
    if mensaje_id:
        c = db.uno("SELECT * FROM comandos WHERE mensaje_id = ?", (mensaje_id,))
    else:
        c = db.uno("SELECT * FROM comandos WHERE id = ?", (cid,))
    if c:
        c["parametros"] = db.de_json(c.pop("parametros_json")) or {}
    return c


def listar(limite=50):
    return [obtener(f["id"]) for f in db.todos("SELECT id FROM comandos ORDER BY id DESC LIMIT ?", (limite,))]


def registrar_respuesta(datos, ts=None):
    """Procesa la respuesta del controlador (llamado desde la ingesta MQTT)."""
    from services import parqueo, patio  # import diferido para evitar ciclos

    mensaje_id = datos.get("comando_id")
    aceptado = bool(datos.get("aceptado"))
    causa = datos.get("causa")
    with db.transaccion():
        c = obtener(mensaje_id=mensaje_id)
        if not c:
            raise NoEncontrado(f"Respuesta a un comando desconocido: {mensaje_id}")
        if c["estado"] != C.CMD_ENVIADO:
            return c  # respuesta duplicada
        db.actualizar("comandos", {"estado": C.CMD_ACEPTADO if aceptado else C.CMD_RECHAZADO,
                                   "causa_rechazo": None if aceptado else (causa or "Sin causa informada"),
                                   "respondido_en": ts or db.ahora()}, "id = ?", (c["id"],))
        p = c["parametros"]
        if aceptado:
            if c["comando"] == "AgujaLiberar" and p.get("plaza"):
                parqueo.confirmar_liberacion(p["plaza"])
            elif c["comando"] == "PosicionBloquear":
                patio.marcar_bloqueo(p["posicion"], True, p.get("motivo"))
            elif c["comando"] == "PosicionLiberar":
                patio.marcar_bloqueo(p["posicion"], False)
            elif c["comando"] == "ModoMantenimiento":
                db.guardar_estado("modo", C.MODO_MANTENIMIENTO if p.get("activar") else C.MODO_NORMAL)
        else:
            alarmas.generar("AL14", origen=C.ORIGEN_CONTROLADOR, clave=c["mensaje_id"],
                            detalle=f"{c['comando']} - {causa}", datos={"comando": c["comando"], "causa": causa})
        eventos.registrar("COMANDO_RESPUESTA",
                          f"Comando {c['comando']} {'ACEPTADO' if aceptado else 'RECHAZADO: ' + str(causa)}",
                          origen=C.ORIGEN_CONTROLADOR, datos={"comando_id": mensaje_id, "aceptado": aceptado, "causa": causa})
        final = obtener(c["id"])
        mqtt_bus.publicar(C.TOPICO_SRV_COMANDO, "COMANDO_RESULTADO", final)
    return final
