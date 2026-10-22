#!/usr/bin/env python3
# ============================================================
# PORTUS - Persistencia MQTT -> SQLite
# ============================================================

import json
import sqlite3
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

import paho.mqtt.client as mqtt

from db_portus import DB_PATH, conectar, inicializar_bd

MQTT_HOST = "localhost"
MQTT_PORT = 1883

TOPICS = [
    ("portus/evt/#", 0),
    ("portus/cmd/respuesta", 0),
]

ultima_secuencia = None
ultimo_latido_monotono = None
alarma_enlace_local = False
lock_latido = threading.Lock()
inicio_monitoreo = time.monotonic()


def a_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def guardar_evento(topic: str, msg: dict) -> bool:
    evento_id = str(msg.get("id", "")).strip()
    timestamp = str(msg.get("timestamp", "")).strip()
    origen = str(msg.get("origin", "")).strip()
    tipo = str(msg.get("type", "")).strip()
    secuencia = msg.get("sequence")
    datos = msg.get("data", {})

    if not evento_id or not timestamp or not origen or not tipo:
        print("[DESCARTADO] Mensaje sin campos minimos obligatorios")
        return False

    conn = conectar()

    try:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO eventos(
                id, timestamp, topic, origen, tipo,
                secuencia, datos_json, mensaje_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evento_id,
                timestamp,
                topic,
                origen,
                tipo,
                secuencia,
                a_json(datos),
                a_json(msg),
            ),
        )

        nuevo = cursor.rowcount == 1

        if not nuevo:
            conn.rollback()
            print(f"[DUPLICADO] {evento_id}")
            return False

        if topic == "portus/evt/estado":
            with lock_latido:
                global ultimo_latido_monotono
                ultimo_latido_monotono = time.monotonic()
            conn.execute(
                """
                INSERT OR IGNORE INTO telemetria(
                    evento_id, timestamp, secuencia,
                    estado_general, datos_json
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    evento_id,
                    timestamp,
                    secuencia,
                    datos.get("estado"),
                    a_json(datos),
                ),
            )

        elif topic == "portus/evt/pesaje":
            conn.execute(
                """
                INSERT INTO pesajes(
                    turno_id, tipo, peso_medido_g,
                    peso_esperado_g, diferencia_g,
                    muestras, resultado, timestamp, datos_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datos.get("turno") or datos.get("turno_id"),
                    datos.get("tipo"),
                    datos.get("peso_medido_g") if datos.get("peso_medido_g") is not None else datos.get("peso"),
                    datos.get("peso_esperado_g"),
                    datos.get("diferencia_g"),
                    datos.get("muestras"),
                    datos.get("resultado"),
                    timestamp,
                    a_json(datos),
                ),
            )

        elif topic == "portus/evt/alarma":
            conn.execute(
                """
                INSERT INTO alarmas(
                    codigo, severidad, timestamp, datos_json
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    datos.get("codigo", "SIN_CODIGO"),
                    datos.get("severidad"),
                    timestamp,
                    a_json(datos),
                ),
            )

        conn.commit()
        return True

    except sqlite3.Error as exc:
        conn.rollback()
        print(f"[SQL ERROR] {exc}")
        return False

    finally:
        conn.close()


def vigilar_enlace():
    """AL01 tras 3 latidos ausentes (15 segundos); no al arrancar sin enlace."""
    global alarma_enlace_local
    while True:
        time.sleep(2)
        with lock_latido:
            ultimo = ultimo_latido_monotono
        # Incluso si el controlador nunca llegó a enviar su primer latido,
        # tres periodos sin recibir estado deben producir AL01.
        perdido = time.monotonic() - (ultimo if ultimo is not None else inicio_monitoreo) > 15.5
        if perdido == alarma_enlace_local:
            continue
        conn = conectar()
        try:
            if perdido:
                ya = conn.execute("SELECT id FROM alarmas WHERE codigo='AL01' AND estado='ACTIVA' LIMIT 1").fetchone()
                if ya is None:
                    conn.execute("""
                      INSERT INTO alarmas(codigo,severidad,timestamp,datos_json)
                      VALUES ('AL01','Alta',?,?)
                    """, (datetime.now(ZoneInfo('America/Guatemala')).isoformat(timespec='seconds'),
                          a_json({'causa':'SIN_LATIDOS_DEL_MEGA','periodos_perdidos':3})))
                print('[AL01] Enlace con Mega perdido: tres latidos consecutivos')
            else:
                conn.execute("UPDATE alarmas SET estado='CERRADA' WHERE codigo='AL01' AND estado IN ('ACTIVA','RECONOCIDA')")
                print('[AL01] Enlace con Mega restablecido')
            conn.commit()
            alarma_enlace_local=perdido
        except Exception as exc:
            conn.rollback()
            print(f'[AL01] Error al persistir: {exc}')
        finally:
            conn.close()


def revisar_secuencia(msg: dict) -> None:
    global ultima_secuencia

    sec = msg.get("sequence")
    if not isinstance(sec, int):
        return

    if ultima_secuencia is None:
        ultima_secuencia = sec
        return

    if sec == ultima_secuencia:
        return

    if sec == ultima_secuencia + 1:
        ultima_secuencia = sec
        return

    if sec < ultima_secuencia:
        print(
            f"[SECUENCIA] Reinicio o reconexion detectada: "
            f"{ultima_secuencia} -> {sec}"
        )
        ultima_secuencia = sec
        return

    print(
        f"[ADVERTENCIA] Posible perdida de mensajes: "
        f"esperado {ultima_secuencia + 1}, recibido {sec}"
    )
    ultima_secuencia = sec


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code != 0:
        print(f"[MQTT] Error de conexion: {reason_code}")
        return

    print("[MQTT] Conectado a Mosquitto")

    for topic, qos in TOPICS:
        client.subscribe(topic, qos)
        print(f"[MQTT] Suscrito a {topic}")


def on_message(client, userdata, message):
    try:
        texto = message.payload.decode("utf-8")
        msg = json.loads(texto)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"[DESCARTADO] JSON invalido en {message.topic}: {exc}")
        return

    revisar_secuencia(msg)

    if guardar_evento(message.topic, msg):
        print(
            f"[DB] {message.topic} "
            f"id={msg.get('id')} "
            f"seq={msg.get('sequence')} "
            f"type={msg.get('type')}"
        )


def main():
    inicializar_bd()

    print("=== PORTUS Persistencia MQTT -> SQLite ===")
    print(f"MQTT: {MQTT_HOST}:{MQTT_PORT}")
    print(f"DB:   {DB_PATH}")
    print("Ctrl+C para salir.\n")

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="portus-persistence",
    )

    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(MQTT_HOST, MQTT_PORT, 60)
    threading.Thread(target=vigilar_enlace, daemon=True, name='watchdog-portus').start()

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\nCerrando persistencia...")
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
