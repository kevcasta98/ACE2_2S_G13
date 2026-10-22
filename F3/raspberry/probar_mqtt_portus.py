#!/usr/bin/env python3
import json
import time
import uuid
from datetime import datetime

import paho.mqtt.client as mqtt

HOST = "localhost"
PORT = 1883
TOPIC_SOLICITUD = "portus/cmd/solicitud"
TOPIC_RESPUESTA = "portus/cmd/respuesta"

request_id = f"cmd-{uuid.uuid4()}"
recibido = False


def ahora():
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        client.subscribe(TOPIC_RESPUESTA)
    else:
        print(f"Error MQTT: {reason_code}")


def on_message(client, userdata, msg):
    global recibido

    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception:
        return

    data = payload.get("data", {})
    if data.get("request_id") != request_id:
        return

    print("Respuesta recibida:")
    print(json.dumps(payload, indent=2, ensure_ascii=False))

    if payload.get("type") == "ACK" and data.get("command") == "PING":
        print("\nPRUEBA MQTT OK: MQTT -> Serial -> Arduino -> Serial -> MQTT")
    else:
        print("\nLa respuesta llego, pero no fue ACK/PING.")

    recibido = True


client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2,
    client_id=f"portus-test-{uuid.uuid4()}",
)
client.on_connect = on_connect
client.on_message = on_message
client.connect(HOST, PORT, 60)
client.loop_start()

time.sleep(0.5)

mensaje = {
    "id": request_id,
    "timestamp": ahora(),
    "origin": "server",
    "type": "CMD",
    "data": {
        "command": "PING",
        "params": {},
    },
}

print("Publicando PING por MQTT:")
print(json.dumps(mensaje, indent=2, ensure_ascii=False))
client.publish(TOPIC_SOLICITUD, json.dumps(mensaje), qos=0, retain=False)

limite = time.time() + 8
while time.time() < limite and not recibido:
    time.sleep(0.1)

if not recibido:
    print("\nERROR: no se recibio respuesta en 8 segundos.")

client.loop_stop()
client.disconnect()
