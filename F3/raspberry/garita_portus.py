#!/usr/bin/env python3
# ============================================================
# PORTUS - Servicio de validacion de acceso en garita
# Fase 2 / v0.6
#
# Flujo:
#   EVT GARITA RFID -> SQLite -> decision -> MQTT CMD
#   CMD -> bridge -> Arduino -> ACK/NACK
#   EVT GARITA INGRESO COMPLETO -> crea/actualiza turno en SQLite
# ============================================================

from __future__ import annotations

import json
import re
import uuid
import threading
from datetime import timedelta

import paho.mqtt.client as mqtt

from db_portus import conectar, inicializar_bd
from fase3_db import migrar, momento
from fase3_acceso import prevalidar, respuesta_manual, recibir_respuesta
from citas_portus import ahora_local, desde_db, encolar_notificacion

MQTT_HOST = "localhost"
MQTT_PORT = 1883
MQTT_KEEPALIVE = 60

TOPIC_GARITA = "portus/evt/garita"
TOPIC_CMD_SOLICITUD = "portus/cmd/solicitud"
TOPIC_CMD_RESPUESTA = "portus/cmd/respuesta"

TOLERANCIA_POSTERIOR_MIN = 5

# request_id -> informacion de la decision emitida. Solo es diagnostico;
# el turno formal se crea al recibir INGRESO COMPLETO del controlador.
pendientes: dict[str, dict] = {}


def publicar_comando(client: mqtt.Client, comando: str, params: dict) -> str:
    request_id = f"cmd-garita-{uuid.uuid4()}"
    payload = {
        "id": request_id,
        "timestamp": ahora_local().isoformat(timespec="milliseconds"),
        "origin": "server",
        "type": "CMD",
        "data": {
            "command": comando,
            "params": params,
        },
    }
    client.publish(
        TOPIC_CMD_SOLICITUD,
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        qos=0,
        retain=False,
    )
    return request_id


def normalizar_uid(valor: object) -> str:
    return re.sub(r"[^0-9A-F]", "", str(valor or "").upper())


def numero_con_prefijo(valor: str, prefijo: str) -> int | None:
    texto = str(valor or "").strip().upper()
    m = re.fullmatch(rf"{re.escape(prefijo.upper())}(\d+)", texto)
    return int(m.group(1)) if m else None


def siguiente_turno(conn) -> tuple[str, int]:
    usados = set()
    for fila in conn.execute("SELECT id FROM turnos WHERE id LIKE 'T%'").fetchall():
        numero = numero_con_prefijo(fila["id"], "T")
        if numero is not None and 1 <= numero <= 32767:
            usados.add(numero)

    candidato = max(usados, default=0) + 1
    if candidato > 32767:
        candidato = 1
        while candidato in usados and candidato <= 32767:
            candidato += 1

    if candidato > 32767:
        raise RuntimeError("No quedan identificadores de turno disponibles para el Mega")

    return f"T{candidato}", candidato


def plazas_libres(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS n FROM plazas_retencion WHERE ocupada = 0"
    ).fetchone()["n"]


def notificar_rechazo(conn, transportista_id: int | None, camion: str, causa: str) -> None:
    if not transportista_id:
        return
    mensajes = {
        "LEVANTE_RETENIDO": "El ingreso fue rechazado porque el levante se encuentra retenido.",
        "SIN_LEVANTE": "El ingreso fue rechazado porque la carga no cuenta con levante otorgado.",
        "SIN_CITA": "El ingreso fue rechazado porque la carga no tiene una cita vigente.",
        "FUERA_DE_VENTANA": "El vehiculo se presento fuera de la ventana asignada.",
        "PARQUEO_LLENO": "El ingreso fue rechazado porque el parqueo de retencion no tiene plazas disponibles.",
    }
    detalle = mensajes.get(causa, f"El ingreso del vehiculo {camion} fue rechazado: {causa}.")
    encolar_notificacion(
        conn,
        transportista_id,
        "GARITA_RECHAZADA",
        f"Vehiculo {camion}. {detalle}",
    )


def enviar_rechazo(client: mqtt.Client, causa: str, camion: str, transportista_id: int | None = None) -> None:
    conn = conectar()
    try:
        conn.execute("BEGIN IMMEDIATE")
        notificar_rechazo(conn, transportista_id, camion, causa)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    request_id = publicar_comando(
        client,
        "CerrarTalanquera",
        {"causa": causa},
    )
    pendientes[request_id] = {
        "tipo": "RECHAZO",
        "camion": camion,
        "causa": causa,
    }
    print(f"[GARITA] {camion}: RECHAZADO -> {causa}")


def obtener_citas_del_camion(conn, camion_id: int):
    return conn.execute(
        """
        SELECT
            c.id AS cita_id,
            c.inicio,
            c.fin,
            c.estado AS cita_estado,
            c.manifiesto_id,
            c.contenedor_id,
            m.operacion,
            m.peso_declarado_g,
            m.tolerancia_pct,
            m.estado_operativo,
            m.anulado,
            m.transportista_id,
            d.numero AS declaracion_numero,
            d.levante_estado,
            d.canal,
            d.motivo_retencion
        FROM citas c
        JOIN manifiestos m ON m.id = c.manifiesto_id
        LEFT JOIN declaraciones d ON d.manifiesto_id = m.id
        WHERE c.camion_id = ?
          AND c.estado = 'PROGRAMADA'
        ORDER BY c.inicio ASC, c.id ASC
        """,
        (camion_id,),
    ).fetchall()


def manifiestos_pendientes_transportista(conn, transportista_id: int):
    return conn.execute(
        """
        SELECT
            m.id AS manifiesto_id,
            m.contenedor_id,
            m.operacion,
            m.peso_declarado_g,
            m.tolerancia_pct,
            m.transportista_id,
            d.levante_estado,
            d.canal,
            d.motivo_retencion
        FROM manifiestos m
        LEFT JOIN declaraciones d ON d.manifiesto_id = m.id
        WHERE m.transportista_id = ?
          AND m.anulado = 0
          AND m.estado_operativo = 'PENDIENTE'
        ORDER BY m.created_at ASC, m.id ASC
        """,
        (transportista_id,),
    ).fetchall()


def validar_rfid(client: mqtt.Client, data: dict, skip_fase3: bool = False) -> None:
    if not skip_fase3:
        raise RuntimeError('Fase3: prohibido autorizar RFID sin prevalidación OCR/manual')
    uid = normalizar_uid(data.get("uid"))
    camion_evento = str(data.get("camion") or "").strip().upper()

    if not uid or camion_evento == "DESCONOCIDO":
        # El propio controlador ya mantiene cerrada la entrada para RFID desconocido.
        print(f"[GARITA] RFID desconocido: {uid or 'SIN_UID'}")
        return

    conn = conectar()
    try:
        camion = conn.execute(
            """
            SELECT c.id, c.placa, c.rfid_uid, c.transportista_id, c.tara_g, c.activo,
                   t.nombre AS transportista
            FROM camiones c
            LEFT JOIN transportistas t ON t.id = c.transportista_id
            WHERE UPPER(REPLACE(c.rfid_uid, ' ', '')) = ?
            LIMIT 1
            """,
            (uid,),
        ).fetchone()

        if camion is None:
            causa = "RFID_NO_REGISTRADO"
            transportista_id = None
        elif not camion["activo"]:
            causa = "CAMION_INACTIVO"
            transportista_id = camion["transportista_id"]
        elif camion_evento and camion_evento != camion["placa"].upper():
            causa = "DATOS_INVALIDOS"
            transportista_id = camion["transportista_id"]
        else:
            causa = None
            transportista_id = camion["transportista_id"]

        if causa:
            conn.close()
            enviar_rechazo(client, causa, camion_evento, transportista_id)
            return

        activo = conn.execute(
            """
            SELECT id, estado
            FROM turnos
            WHERE camion_id = ?
              AND estado NOT IN ('Cerrado','Anulado')
            ORDER BY inicio DESC
            LIMIT 1
            """,
            (camion["id"],),
        ).fetchone()
        if activo:
            conn.close()
            enviar_rechazo(client, "TURNO_ACTIVO", camion["placa"], camion["transportista_id"])
            return

        citas = obtener_citas_del_camion(conn, camion["id"])
        ahora = ahora_local()
        citas_en_ventana = []

        for cita in citas:
            inicio = desde_db(cita["inicio"])
            fin = desde_db(cita["fin"])
            if not inicio or not fin:
                continue
            limite = fin + timedelta(minutes=TOLERANCIA_POSTERIOR_MIN)
            if inicio <= ahora <= limite:
                citas_en_ventana.append(cita)

        if len(citas_en_ventana) > 1:
            conn.close()
            enviar_rechazo(client, "VARIAS_CITAS", camion["placa"], camion["transportista_id"])
            return

        if not citas_en_ventana:
            if citas:
                # En v0.6 se bloquea fisicamente el ingreso fuera de ventana.
                # La creacion de RT04 y su flujo de parqueo se incorpora en el
                # siguiente bloque de integracion.
                conn.close()
                enviar_rechazo(client, "FUERA_DE_VENTANA", camion["placa"], camion["transportista_id"])
                return

            pendientes_transportista = manifiestos_pendientes_transportista(
                conn, camion["transportista_id"]
            )
            if len(pendientes_transportista) == 1:
                unico = pendientes_transportista[0]
                if unico["levante_estado"] == "RETENIDO":
                    causa = "LEVANTE_RETENIDO"
                elif unico["levante_estado"] != "OTORGADO":
                    causa = "SIN_LEVANTE"
                else:
                    causa = "SIN_CITA"
            else:
                causa = "SIN_CITA"

            conn.close()
            enviar_rechazo(client, causa, camion["placa"], camion["transportista_id"])
            return

        cita = citas_en_ventana[0]

        if cita["anulado"] or cita["estado_operativo"] != "PENDIENTE":
            conn.close()
            enviar_rechazo(client, "MANIFIESTO_INVALIDO", camion["placa"], camion["transportista_id"])
            return

        if cita["levante_estado"] == "RETENIDO":
            conn.close()
            enviar_rechazo(client, "LEVANTE_RETENIDO", camion["placa"], camion["transportista_id"])
            return
        if cita["levante_estado"] != "OTORGADO":
            conn.close()
            enviar_rechazo(client, "SIN_LEVANTE", camion["placa"], camion["transportista_id"])
            return
        if cita["canal"] not in ("VERDE", "ROJO"):
            conn.close()
            enviar_rechazo(client, "DATOS_INVALIDOS", camion["placa"], camion["transportista_id"])
            return

        if cita["canal"] == "ROJO" and plazas_libres(conn) == 0:
            conn.execute(
                """
                INSERT INTO alarmas(codigo, severidad, timestamp, datos_json)
                VALUES ('AL11', 'Media', ?, ?)
                """,
                (
                    ahora.isoformat(timespec="seconds"),
                    json.dumps(
                        {"camion": camion["placa"], "causa": "PARQUEO_LLENO"},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                ),
            )
            conn.commit()
            conn.close()
            enviar_rechazo(client, "PARQUEO_LLENO", camion["placa"], camion["transportista_id"])
            return

        turno_id, turno_num = siguiente_turno(conn)
        conn.close()

        manifiesto_num = numero_con_prefijo(cita["manifiesto_id"], "M")
        contenedor_num = numero_con_prefijo(cita["contenedor_id"], "C")
        if manifiesto_num is None or contenedor_num is None:
            enviar_rechazo(client, "DATOS_INVALIDOS", camion["placa"], camion["transportista_id"])
            return

        tolerancia_g = float(cita["peso_declarado_g"]) * float(cita["tolerancia_pct"]) / 100.0

        # RT07/RT08 tienen prioridad sobre canal VERDE para el desvío físico.
        # El canal aduanero original permanece intacto en SQLite.
        ultimo_f3 = None
        consulta=conectar()
        try:
            ultimo_f3=consulta.execute("""SELECT resultado,causa_retencion FROM fase3_accesos
              WHERE id=? AND camion_id=? AND turno_id IS NULL LIMIT 1""",
              (data.get('_fase3_acceso_id'),camion['id'])).fetchone()
            plazas_f3=plazas_libres(consulta)
        finally:consulta.close()
        canal_fisico = ('ROJO' if ultimo_f3 is not None and
                 ultimo_f3['causa_retencion'] in ('RT07','RT08') else cita['canal'])
        if canal_fisico == 'ROJO' and plazas_f3 == 0:
            enviar_rechazo(client,'PARQUEO_LLENO',camion['placa'],camion['transportista_id'])
            return
        params = {
            "camion": camion["placa"],
            "manifiesto": cita["manifiesto_id"],
            "contenedor": cita["contenedor_id"],
            "operacion": cita["operacion"],
            "peso": float(cita["peso_declarado_g"]),
            "tolerancia": round(tolerancia_g, 3),
            "canal": canal_fisico,
            "turno": turno_id,
            "cita": cita["cita_id"],
        }

        request_id = publicar_comando(client, "AbrirTalanquera", params)
        pendientes[request_id] = {
            "tipo": "AUTORIZACION",
            "camion_id": camion["id"],
            "camion": camion["placa"],
            "transportista_id": camion["transportista_id"],
            "cita_id": cita["cita_id"],
            "manifiesto_id": cita["manifiesto_id"],
            "contenedor_id": cita["contenedor_id"],
            "operacion": cita["operacion"],
            "canal": cita["canal"],
            "turno_id": turno_id,
            "turno_num": turno_num,
        }

        print(
            f"[GARITA] {camion['placa']} AUTORIZADO | "
            f"{cita['manifiesto_id']} | {cita['contenedor_id']} | "
            f"{cita['operacion']} | canal {cita['canal']} | cita {cita['cita_id']} | {turno_id}"
        )

    finally:
        # Varias ramas cierran antes para liberar el lock antes de publicar.
        try:
            conn.close()
        except Exception:
            pass


def registrar_ingreso_completo(data: dict) -> None:
    camion_placa = str(data.get("camion") or "").strip().upper()
    manifiesto_id = str(data.get("manifiesto") or "").strip().upper()
    contenedor_id = str(data.get("contenedor") or "").strip().upper()
    turno_id = str(data.get("turno") or "").strip().upper()
    operacion = str(data.get("operacion") or "").strip().upper()

    if not all((camion_placa, manifiesto_id, contenedor_id, turno_id)):
        print(f"[GARITA] INGRESO COMPLETO con datos incompletos: {data}")
        return

    conn = conectar()
    try:
        conn.execute("BEGIN IMMEDIATE")
        camion = conn.execute(
            "SELECT id, transportista_id FROM camiones WHERE placa = ? AND activo = 1",
            (camion_placa,),
        ).fetchone()
        if camion is None:
            raise RuntimeError(f"Camion {camion_placa} no existe en SQLite")

        cita = conn.execute(
            """
            SELECT id, inicio, fin
            FROM citas
            WHERE manifiesto_id = ?
              AND contenedor_id = ?
              AND camion_id = ?
              AND estado = 'PROGRAMADA'
            ORDER BY inicio ASC
            LIMIT 1
            """,
            (manifiesto_id, contenedor_id, camion["id"]),
        ).fetchone()
        if cita is None:
            raise RuntimeError("No existe la cita PROGRAMADA asociada al ingreso")

        existente = conn.execute(
            "SELECT id FROM turnos WHERE id = ?",
            (turno_id,),
        ).fetchone()
        if existente is None:
            conn.execute(
                """
                INSERT INTO turnos(
                    id, manifiesto_id, camion_id, contenedor_id,
                    operacion, estado, estacion
                ) VALUES (?, ?, ?, ?, ?, 'EnPesajeEntrada', 'PESAJE_ENTRADA')
                """,
                (
                    turno_id,
                    manifiesto_id,
                    camion["id"],
                    contenedor_id,
                    operacion,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE turnos
                SET estado = 'EnPesajeEntrada', estacion = 'PESAJE_ENTRADA',
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (turno_id,),
            )

        conn.execute(
            """
            UPDATE citas
            SET estado = 'CUMPLIDA', dentro_ventana = 1, updated_at = datetime('now')
            WHERE id = ?
            """,
            (cita["id"],),
        )
        conn.execute(
            """
            UPDATE manifiestos
            SET estado_operativo = 'EN_CURSO', updated_at = datetime('now')
            WHERE id = ?
            """,
            (manifiesto_id,),
        )
        conn.execute(
            """
            INSERT INTO historial_citas(cita_id, accion, valor_anterior, valor_nuevo, detalle)
            VALUES (?, 'CUMPLIDA', 'PROGRAMADA', 'CUMPLIDA', 'Ingreso fisico confirmado por el controlador')
            """,
            (cita["id"],),
        )

        acceso_f3=conn.execute("""SELECT * FROM fase3_accesos WHERE camion_id=? AND turno_id IS NULL
               AND resultado IN ('VERIFICADA','NO_COINCIDE','RESTRINGIDA','APROBADA_MANUAL')
               ORDER BY id DESC LIMIT 1""",(camion['id'],)).fetchone()
        if acceso_f3:
            conn.execute('UPDATE fase3_accesos SET turno_id=? WHERE id=?',(turno_id,acceso_f3['id']))
            if acceso_f3['foto'] and camion['transportista_id']:
                from citas_portus import encolar_notificacion
                encolar_notificacion(conn,camion['transportista_id'],'INGRESO_FOTOGRAFIA',
                  f"Ingreso verificado: {camion_placa}, contenedor {contenedor_id}, {operacion}. Placa: {acceso_f3['placa_leida'] or acceso_f3['placa_esperada']}, hora {momento()}. Fotografía disponible.")
                notificacion_id=conn.execute('SELECT last_insert_rowid()').fetchone()[0]
                conn.execute('INSERT OR IGNORE INTO fase3_fotos_notificacion(notificacion_id,archivo) VALUES (?,?)',
                             (notificacion_id,acceso_f3['foto']))
        conn.commit()
        print(
            f"[GARITA] INGRESO COMPLETO -> {turno_id} | {camion_placa} | "
            f"{manifiesto_id} | estado EnPesajeEntrada"
        )
    except Exception as exc:
        conn.rollback()
        print(f"[GARITA][DB ERROR] No se pudo registrar ingreso completo: {exc}")
    finally:
        conn.close()


def procesar_evento_garita(client: mqtt.Client, payload: dict) -> None:
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        return

    accion = str(data.get("accion") or "").upper()
    resultado = str(data.get("resultado") or "").upper()

    if accion == "RFID":
        threading.Thread(target=prevalidar,args=(client,data,str(payload.get('id') or ''),validar_rfid),
                         daemon=True,name='f3-rfid').start()
        return

    if accion == "INGRESO" and resultado == "COMPLETO":
        registrar_ingreso_completo(data)
        return

    if accion == "INGRESO" and resultado == "TIEMPO_AGOTADO":
        print(f"[GARITA] Autorizacion no utilizada: {data.get('camion')} no cruzo la talanquera")
        return

    if accion == "VALIDACION":
        print(
            f"[CONTROLADOR] Validacion {data.get('resultado')} | "
            f"{data.get('camion')} | causa={data.get('causa')}"
        )


def procesar_respuesta_comando(payload: dict) -> None:
    data = payload.get("data") or {}
    request_id = data.get("request_id")
    if not request_id or request_id not in pendientes:
        return

    contexto = pendientes.pop(request_id)
    tipo = str(payload.get("type") or "").upper()
    comando = data.get("command")
    if tipo == "ACK":
        print(f"[CMD ACK] {comando} | {contexto.get('camion')} | {data.get('msg')}")
    else:
        print(
            f"[CMD NACK] {comando} | {contexto.get('camion')} | "
            f"motivo={data.get('motivo')}"
        )


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code != 0:
        print(f"[MQTT] Error de conexion: {reason_code}")
        return
    client.subscribe(TOPIC_GARITA)
    client.subscribe(TOPIC_CMD_RESPUESTA)
    client.subscribe('portus/acceso/decision')
    print("[MQTT] Servicio GARITA conectado")
    print(f"[MQTT] Suscrito a {TOPIC_GARITA}")
    print(f"[MQTT] Suscrito a {TOPIC_CMD_RESPUESTA}")


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception as exc:
        print(f"[MQTT] JSON invalido en {msg.topic}: {exc}")
        return

    if msg.topic == TOPIC_GARITA:
        procesar_evento_garita(client, payload)
    elif msg.topic == TOPIC_CMD_RESPUESTA:
        recibir_respuesta(payload)
        procesar_respuesta_comando(payload)
    elif msg.topic == 'portus/acceso/decision':
        respuesta_manual(client,payload,validar_rfid)


def main():
    inicializar_bd()
    migrar()
    print("=== PORTUS - Servicio GARITA + VISIÓN v1.0 ===")
    print("Validacion de acceso: Raspberry/SQLite")
    print("Enclavamientos fisicos: Arduino Mega")
    print("Ctrl+C para salir.\n")

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="portus-garita-service",
    )
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE)

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\nCerrando servicio GARITA...")
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
