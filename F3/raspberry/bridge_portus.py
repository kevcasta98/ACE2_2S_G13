#!/usr/bin/env python3
# ============================================================
# PORTUS - Bridge Serial <-> MQTT
# Raspberry Pi / Fase 2
# ============================================================

import json
import os
import threading
import time
import uuid
from datetime import datetime

import paho.mqtt.client as mqtt
import serial

from protocolo_portus import analizar_trama, construir_trama

SERIAL_PORT = os.environ.get("PORTUS_SERIAL_PORT", "/dev/ttyACM0")
SERIAL_BAUD = int(os.environ.get("PORTUS_SERIAL_BAUD", "9600"))
SERIAL_TIMEOUT = 0.20

MQTT_HOST = "localhost"
MQTT_PORT = 1883
MQTT_KEEPALIVE = 60

TOPIC_CMD_SOLICITUD = "portus/cmd/solicitud"
TOPIC_CMD_RESPUESTA = "portus/cmd/respuesta"
TOPIC_DEBUG = "portus/debug/serial"

TOPICOS_EVENTO = {
    "GARITA": "portus/evt/garita",
    "PESAJE": "portus/evt/pesaje",
    "AGUJA": "portus/evt/aguja",
    "TRANSFERENCIA": "portus/evt/transferencia",
    "GRUA": "portus/evt/grua",
    "PATIO": "portus/evt/patio",
    "SALIDA": "portus/evt/salida",
    "ALARMA": "portus/evt/alarma",
    "ESTADO": "portus/evt/estado",
}

serial_link = None
serial_lock = threading.Lock()
secuencia_servidor = 1
ultimo_seq_controlador = None
pendientes = {}


def timestamp_actual():
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def nuevo_id(prefijo="evt"):
    return f"{prefijo}-{uuid.uuid4()}"


def convertir_valor(valor):
    texto = valor.strip()

    if texto.lower() == "true":
        return True
    if texto.lower() == "false":
        return False

    try:
        if "." in texto:
            return float(texto)
        return int(texto)
    except ValueError:
        return texto


def parsear_datos(texto):
    if not texto:
        return {}

    resultado = {}

    for elemento in texto.split(";"):
        if not elemento:
            continue

        if "=" not in elemento:
            resultado.setdefault("valores", []).append(elemento)
            continue

        clave, valor = elemento.split("=", 1)
        resultado[clave] = convertir_valor(valor)

    return resultado


def params_a_texto(params):
    if params is None:
        return ""

    if isinstance(params, str):
        return params

    if not isinstance(params, dict):
        return str(params)

    partes = []
    for clave, valor in params.items():
        if isinstance(valor, bool):
            valor = "true" if valor else "false"
        partes.append(f"{clave}={valor}")

    return ";".join(partes)


def publicar_json(cliente, topic, payload):
    cliente.publish(
        topic,
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        qos=0,
        retain=False,
    )


def verificar_secuencia_controlador(seq):
    global ultimo_seq_controlador

    if ultimo_seq_controlador is not None:
        esperado = ultimo_seq_controlador + 1
        if esperado > 0xFFFFFFFF:
            esperado = 1

        if seq != esperado:
            print(
                f"[WARN] Secuencia controlador: esperado={esperado}, recibido={seq}"
            )

    ultimo_seq_controlador = seq


def procesar_mensaje_portus(cliente, trama_texto):
    resultado = analizar_trama(trama_texto)

    if not resultado.get("valida"):
        print(f"[PROTOCOLO INVALIDO] {resultado}")
        return

    if resultado["origen"] != "C":
        print(f"[WARN] Se ignora trama con origen {resultado['origen']}")
        return

    seq = resultado["secuencia"]
    tipo = resultado["tipo"].upper()
    nombre = resultado["nombre"].upper()
    datos = parsear_datos(resultado["datos"])

    verificar_secuencia_controlador(seq)

    if tipo == "EVT":
        topic = TOPICOS_EVENTO.get(nombre)

        if topic is None:
            print(f"[WARN] Evento sin topico definido: {nombre}")
            return

        payload = {
            "id": nuevo_id("evt"),
            "timestamp": timestamp_actual(),
            "origin": "controller",
            "type": nombre,
            "data": datos,
            "sequence": seq,
        }

        publicar_json(cliente, topic, payload)
        print(f"[MQTT -> {topic}] {payload}")
        return

    if tipo in ("ACK", "NACK"):
        ref = datos.get("ref")
        request_id = None

        if isinstance(ref, int):
            request_id = pendientes.pop(ref, None)
        elif isinstance(ref, str) and ref.isdigit():
            request_id = pendientes.pop(int(ref), None)

        payload = {
            "id": nuevo_id("rsp"),
            "timestamp": timestamp_actual(),
            "origin": "controller",
            "type": tipo,
            "data": {
                "command": nombre,
                "request_id": request_id,
                **datos,
            },
            "sequence": seq,
        }

        publicar_json(cliente, TOPIC_CMD_RESPUESTA, payload)
        print(f"[MQTT -> {TOPIC_CMD_RESPUESTA}] {payload}")
        return

    print(f"[WARN] Tipo PORTUS no manejado: {tipo}")


def siguiente_secuencia_servidor():
    global secuencia_servidor

    actual = secuencia_servidor
    secuencia_servidor += 1

    if secuencia_servidor > 0xFFFFFFFF:
        secuencia_servidor = 1

    return actual


def enviar_comando_serial(command, params, request_id):
    if serial_link is None or not serial_link.is_open:
        raise RuntimeError("PUERTO_SERIAL_NO_DISPONIBLE")

    seq = siguiente_secuencia_servidor()
    datos = params_a_texto(params)
    trama = construir_trama("S", seq, "CMD", command.upper(), datos)

    pendientes[seq] = request_id

    with serial_lock:
        serial_link.write(trama.encode("utf-8"))
        serial_link.flush()

    print(f"[SERIAL ->] {trama.strip()}")


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("[MQTT] Conectado a Mosquitto")
        client.subscribe(TOPIC_CMD_SOLICITUD)
        print(f"[MQTT] Suscrito a {TOPIC_CMD_SOLICITUD}")
    else:
        print(f"[MQTT] Error de conexion: {reason_code}")


def on_message(client, userdata, msg):
    try:
        contenido = msg.payload.decode("utf-8")
        mensaje = json.loads(contenido)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"[MQTT] Comando invalido: {exc}")
        return

    # Formato final recomendado:
    # {
    #   "id": "cmd-...",
    #   "timestamp": "...",
    #   "origin": "server",
    #   "type": "CMD",
    #   "data": {"command": "PING", "params": {}}
    # }
    request_id = mensaje.get("id") or nuevo_id("cmd")
    data = mensaje.get("data", {})

    if isinstance(data, dict):
        command = data.get("command") or mensaje.get("command")
        params = data.get("params", mensaje.get("params", {}))
    else:
        command = mensaje.get("command")
        params = mensaje.get("params", {})

    if not command:
        print("[MQTT] Solicitud sin comando")
        return

    try:
        enviar_comando_serial(command, params, request_id)
    except Exception as exc:
        print(f"[SERIAL] No se pudo enviar el comando: {exc}")


def main():
    global serial_link

    print("=== PORTUS Bridge Serial <-> MQTT ===")
    print(f"Serial: {SERIAL_PORT} @ {SERIAL_BAUD}")
    print(f"MQTT:   {MQTT_HOST}:{MQTT_PORT}")

    serial_link = serial.Serial(
        SERIAL_PORT,
        SERIAL_BAUD,
        timeout=SERIAL_TIMEOUT,
    )

    # El Mega suele reiniciarse al abrir USB CDC.
    print("Esperando arranque del Arduino...")
    time.sleep(3)

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="portus-serial-mqtt-bridge",
    )
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE)
    client.loop_start()

    print("Bridge activo. Ctrl+C para salir.\n")

    try:
        while True:
            raw = serial_link.readline()

            if not raw:
                continue

            texto = raw.decode("utf-8", errors="replace").strip()
            if not texto:
                continue

            if texto.startswith("$PORTUS|"):
                print(f"[SERIAL <-] {texto}")
                procesar_mensaje_portus(client, texto)
            else:
                print(f"[DEBUG] {texto}")
                publicar_json(
                    client,
                    TOPIC_DEBUG,
                    {
                        "id": nuevo_id("dbg"),
                        "timestamp": timestamp_actual(),
                        "origin": "controller",
                        "type": "DEBUG",
                        "data": {"message": texto},
                    },
                )

    except KeyboardInterrupt:
        print("\nCerrando bridge...")

    finally:
        client.loop_stop()
        client.disconnect()

        if serial_link is not None and serial_link.is_open:
            serial_link.close()


if __name__ == "__main__":
    main()
