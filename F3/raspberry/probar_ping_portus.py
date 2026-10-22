import time
import serial

from protocolo_portus import construir_trama, analizar_trama

PUERTO = "/dev/ttyACM0"
BAUDIOS = 9600
TIMEOUT_TOTAL = 10


def es_respuesta_a_ping(resultado, secuencia_enviada):
    if not resultado.get("valida"):
        return False

    if resultado.get("origen") != "C":
        return False

    if resultado.get("tipo") not in ("ACK", "NACK"):
        return False

    if resultado.get("nombre") != "PING":
        return False

    datos = resultado.get("datos", "")
    return f"ref={secuencia_enviada}" in datos


secuencia = 1
trama = construir_trama(
    origen="S",
    secuencia=secuencia,
    tipo="CMD",
    nombre="PING",
    datos=""
)

print(f"Abriendo {PUERTO} a {BAUDIOS} baudios...")

with serial.Serial(PUERTO, BAUDIOS, timeout=0.5) as arduino:
    # El Mega normalmente se reinicia al abrir el puerto USB.
    print("Esperando arranque del Arduino...")
    time.sleep(4)

    arduino.reset_input_buffer()

    print("Enviando:")
    print(trama.strip())
    arduino.write(trama.encode("utf-8"))
    arduino.flush()

    print("\nEsperando ACK/NACK...\n")

    limite = time.monotonic() + TIMEOUT_TOTAL
    respuesta_encontrada = False

    while time.monotonic() < limite:
        linea = arduino.readline()

        if not linea:
            continue

        texto = linea.decode("utf-8", errors="replace").strip()

        if not texto:
            continue

        # Los mensajes antiguos de depuracion siguen activos.
        if not texto.startswith("$PORTUS|"):
            print(f"[DEBUG] {texto}")
            continue

        resultado = analizar_trama(texto)

        if not resultado.get("valida"):
            print("[TRAMA INVALIDA]", resultado)
            continue

        print(
            "[PORTUS]",
            f"SEQ={resultado['secuencia']}",
            f"TIPO={resultado['tipo']}",
            f"NOMBRE={resultado['nombre']}",
            f"DATOS={resultado['datos']}",
            f"CRC={resultado['crc']}"
        )

        if es_respuesta_a_ping(resultado, secuencia):
            respuesta_encontrada = True

            if resultado["tipo"] == "ACK" and "msg=PONG" in resultado["datos"]:
                print("\nPRUEBA OK: Arduino respondio ACK/PONG con CRC valido.")
            else:
                print("\nArduino respondio, pero rechazo PING:")
                print(resultado)

            break

    if not respuesta_encontrada:
        print("\nERROR: no se recibio ACK/NACK de PING dentro del tiempo limite.")
