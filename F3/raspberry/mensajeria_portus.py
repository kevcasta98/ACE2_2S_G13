#!/usr/bin/env python3
# ============================================================
# PORTUS - Canal de mensajería del transportista (Telegram)
# Fase 2 / v0.5
# ============================================================

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from citas_portus import (
    ErrorCita,
    actualizar_citas_vencidas,
    camiones_transportista,
    crear_cita,
    listar_franjas_disponibles,
    manifiestos_elegibles_transportista,
    programar_recordatorios_una_hora,
    transportista_por_cuenta,
    vincular_cuenta,
)
from db_portus import conectar, inicializar_bd

def cargar_env_local():
    ruta = Path(__file__).resolve().parent / ".env"
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        clave = clave.strip()
        valor = valor.strip().strip('"').strip("'")
        if clave:
            os.environ.setdefault(clave, valor)


cargar_env_local()
TOKEN = os.environ.get("PORTUS_TELEGRAM_TOKEN", "").strip()
API_BASE = f"https://api.telegram.org/bot{TOKEN}" if TOKEN else ""
CANAL = "TELEGRAM"


def telegram(method: str, params: dict | None = None, timeout: int = 35):
    if not TOKEN:
        raise RuntimeError("PORTUS_TELEGRAM_TOKEN no está configurado.")
    data = urllib.parse.urlencode(params or {}).encode("utf-8")
    req = urllib.request.Request(f"{API_BASE}/{method}", data=data)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram rechazó {method}: {payload}")
    return payload.get("result")


def enviar(chat_id, texto: str):
    return telegram("sendMessage", {"chat_id": str(chat_id), "text": texto})


def ayuda() -> str:
    return (
        "PORTUS - Terminal portuaria\n\n"
        "/inicio - Presenta el servicio y los comandos.\n"
        "/vincular CODIGO - Vincula esta cuenta con tu transportista.\n"
        "/cita - Inicia la solicitud de una cita.\n"
        "/miscitas - Lista tus citas.\n"
        "/estado CONTENEDOR - Consulta tu carga.\n"
        "/misturnos - Lista tus operaciones en curso.\n"
        "/ayuda - Muestra esta ayuda."
    )


def respuesta_no_vinculado() -> str:
    return (
        "Esta cuenta todavía no está vinculada a un transportista de PORTUS. "
        "Solicita al operador un código y escribe /vincular CODIGO."
    )


def _transportista(chat_id):
    return transportista_por_cuenta(CANAL, str(chat_id))


def comando_vincular(chat_id, partes):
    if len(partes) != 2:
        return "Uso correcto: /vincular CODIGO"
    try:
        nombre = vincular_cuenta(CANAL, str(chat_id), partes[1])
    except ErrorCita as exc:
        return str(exc)
    return f"Vinculación correcta. Transportista: {nombre}.\n\n{ayuda()}"


def comando_cita(transportista: dict, partes: list[str]) -> str:
    conn = conectar()
    try:
        elegibles = manifiestos_elegibles_transportista(conn, transportista["id"])
        camiones = camiones_transportista(conn, transportista["id"])

        if len(partes) == 1:
            if not elegibles:
                return "No tienes contenedores con levante otorgado y sin cita vigente."
            lineas = ["Contenedores disponibles para cita:"]
            for item in elegibles:
                lineas.append(
                    f"- {item['contenedor_id']} | manifiesto {item['manifiesto_id']} | "
                    f"{item['operacion']} | canal {item['canal']}"
                )
            lineas.append("\nElige uno con: /cita CONTENEDOR")
            return "\n".join(lineas)

        contenedor = partes[1].upper()
        manifiesto = next((m for m in elegibles if m["contenedor_id"].upper() == contenedor), None)
        if manifiesto is None:
            return "Ese contenedor no está disponible para solicitar cita. Usa /cita para ver los disponibles."

        if len(partes) == 2:
            if not camiones:
                return "No tienes vehículos activos registrados. Solicita al operador que revise el catálogo."
            lineas = [f"Vehículos registrados para {contenedor}:"]
            for cam in camiones:
                lineas.append(f"- {cam['placa']}")
            lineas.append(f"\nElige uno con: /cita {contenedor} PLACA")
            return "\n".join(lineas)

        placa = partes[2].upper()
        camion = next((c for c in camiones if c["placa"].upper() == placa), None)
        if camion is None:
            return "El vehículo indicado no pertenece a tu transportista o está inactivo."

        franjas = listar_franjas_disponibles(conn, limite=8)
        if not franjas:
            return "No hay franjas disponibles en los próximos días."

        if len(partes) == 3:
            lineas = [f"Próximas franjas para {contenedor} con vehículo {camion['placa']}:"]
            for i, franja in enumerate(franjas, start=1):
                lineas.append(f"{i}. {franja['etiqueta']} ({franja['disponibles']} cupo(s))")
            lineas.append(f"\nElige una con: /cita {contenedor} {camion['placa']} NUMERO")
            return "\n".join(lineas)

        try:
            indice = int(partes[3])
        except ValueError:
            return "El número de franja no es válido."
        if indice < 1 or indice > len(franjas):
            return "El número de franja no está en la lista ofrecida."
        elegida = franjas[indice - 1]
    finally:
        conn.close()

    try:
        cita = crear_cita(
            transportista["id"],
            contenedor,
            elegida["inicio"],
            camion_id=camion["id"],
        )
    except ErrorCita as exc:
        return f"No se pudo asignar la cita: {exc}"

    return (
        f"Cita confirmada.\n"
        f"Contenedor: {cita['contenedor_id']}\n"
        f"Vehículo: {cita['placa']}\n"
        f"Fecha y hora: {elegida['etiqueta']}\n"
        f"Canal aduanero: {cita['canal']}"
    )


def comando_miscitas(transportista: dict) -> str:
    actualizar_citas_vencidas()
    conn = conectar()
    try:
        filas = conn.execute(
            """
            SELECT c.id, c.contenedor_id, c.inicio, c.fin, c.estado,
                   cam.placa AS vehiculo
            FROM citas c
            LEFT JOIN camiones cam ON cam.id = c.camion_id
            WHERE c.transportista_id = ?
            ORDER BY c.inicio DESC, c.id DESC
            LIMIT 20
            """,
            (transportista["id"],),
        ).fetchall()
    finally:
        conn.close()
    if not filas:
        return "No tienes citas registradas."
    lineas = ["Tus citas:"]
    for c in filas:
        lineas.append(
            f"- {c['contenedor_id']} | {c['inicio']} a {c['fin'][11:16]} | "
            f"{c['estado']} | vehículo {c['vehiculo'] or '-'}"
        )
    return "\n".join(lineas)


def comando_estado(transportista: dict, partes: list[str]) -> str:
    if len(partes) != 2:
        return "Uso correcto: /estado CONTENEDOR"
    contenedor = partes[1].upper()
    conn = conectar()
    try:
        fila = conn.execute(
            """
            SELECT c.id, c.estado, c.ubicacion, c.nivel, c.permanencia_inicio,
                   m.id AS manifiesto_id, d.levante_estado, d.canal
            FROM contenedores c
            JOIN manifiestos m ON m.id = (
                SELECT m2.id FROM manifiestos m2
                WHERE m2.contenedor_id = c.id
                  AND m2.transportista_id = ?
                  AND m2.anulado = 0
                ORDER BY m2.updated_at DESC, m2.rowid DESC
                LIMIT 1
            )
            LEFT JOIN declaraciones d ON d.manifiesto_id = m.id
            WHERE c.id = ?
            """,
            (transportista["id"], contenedor),
        ).fetchone()
    finally:
        conn.close()
    if fila is None:
        return "No tienes carga asociada a ese identificador."
    ubicacion = fila["ubicacion"] or "Sin ubicación registrada"
    if fila["nivel"] is not None:
        ubicacion += f" / nivel {fila['nivel']}"
    return (
        f"Contenedor: {fila['id']}\n"
        f"Estado: {fila['estado']}\n"
        f"Ubicación: {ubicacion}\n"
        f"Permanencia desde: {fila['permanencia_inicio'] or 'No aplica'}\n"
        f"Autorización: {fila['levante_estado'] or 'SIN DECLARACIÓN'}\n"
        f"Canal: {fila['canal'] or '-'}"
    )


def comando_misturnos(transportista: dict) -> str:
    conn = conectar()
    try:
        filas = conn.execute(
            """
            SELECT tu.id, cam.placa AS vehiculo, tu.contenedor_id,
                   tu.operacion, tu.estado, tu.estacion
            FROM turnos tu
            JOIN camiones cam ON cam.id = tu.camion_id
            WHERE cam.transportista_id = ?
              AND tu.estado NOT IN ('Cerrado','Anulado')
            ORDER BY tu.inicio ASC
            """,
            (transportista["id"],),
        ).fetchall()
    finally:
        conn.close()
    if not filas:
        return "No tienes operaciones en curso."
    lineas = ["Operaciones en curso:"]
    for t in filas:
        lineas.append(
            f"- Turno {t['id']} | vehículo {t['vehiculo']} | contenedor {t['contenedor_id']} | "
            f"{t['operacion']} | {t['estado']} | estación {t['estacion'] or '-'}"
        )
    return "\n".join(lineas)


def procesar_texto(chat_id, texto: str) -> str:
    texto = (texto or "").strip()
    partes = texto.split()
    comando = partes[0].lower() if partes else ""

    if comando == "/vincular":
        return comando_vincular(chat_id, partes)

    transportista = _transportista(chat_id)
    if transportista is None:
        return respuesta_no_vinculado()

    if comando in ("/inicio", "/ayuda"):
        return f"Hola, {transportista['nombre']}.\n\n{ayuda()}"
    if comando == "/cita":
        return comando_cita(transportista, partes)
    if comando == "/miscitas":
        return comando_miscitas(transportista)
    if comando == "/estado":
        return comando_estado(transportista, partes)
    if comando == "/misturnos":
        return comando_misturnos(transportista)
    return "Comando no reconocido. Usa /ayuda para ver los comandos disponibles."


def enviar_notificaciones_pendientes():
    conn = conectar()
    try:
        filas = conn.execute(
            """
            SELECT n.id, n.transportista_id, n.mensaje, mv.cuenta_id
            FROM notificaciones_transportista n
            LEFT JOIN mensajeria_vinculos mv
                   ON mv.transportista_id = n.transportista_id
                  AND mv.canal = 'TELEGRAM'
            WHERE n.estado = 'PENDIENTE'
            ORDER BY n.id ASC
            LIMIT 30
            """
        ).fetchall()
        for n in filas:
            if not n["cuenta_id"]:
                continue
            try:
                enviar(n["cuenta_id"], n["mensaje"])
                conn.execute(
                    """
                    UPDATE notificaciones_transportista
                    SET estado = 'ENVIADA', sent_at = datetime('now'),
                        intentos = intentos + 1, ultimo_error = NULL
                    WHERE id = ?
                    """,
                    (n["id"],),
                )
            except Exception as exc:
                conn.execute(
                    """
                    UPDATE notificaciones_transportista
                    SET intentos = intentos + 1, ultimo_error = ?
                    WHERE id = ?
                    """,
                    (str(exc)[:300], n["id"]),
                )
        conn.commit()
    finally:
        conn.close()


def main():
    inicializar_bd()
    if not TOKEN:
        raise SystemExit(
            "Falta PORTUS_TELEGRAM_TOKEN. Ejemplo:\n"
            "export PORTUS_TELEGRAM_TOKEN='123456:ABC...'"
        )

    print("PORTUS Mensajería v0.5 - Telegram")
    print("Esperando mensajes. Ctrl+C para salir.")
    offset = 0
    ultimo_mantenimiento = 0.0

    while True:
        try:
            ahora = time.monotonic()
            if ahora - ultimo_mantenimiento >= 30:
                actualizar_citas_vencidas()
                programar_recordatorios_una_hora()
                enviar_notificaciones_pendientes()
                ultimo_mantenimiento = ahora

            updates = telegram(
                "getUpdates",
                {"timeout": 25, "offset": offset, "allowed_updates": json.dumps(["message"])},
                timeout=35,
            )
            for upd in updates or []:
                offset = max(offset, int(upd["update_id"]) + 1)
                msg = upd.get("message") or {}
                chat = msg.get("chat") or {}
                chat_id = chat.get("id")
                texto = msg.get("text")
                if chat_id is None:
                    continue
                if not isinstance(texto, str):
                    enviar(chat_id, "Solo se admiten comandos de texto. Usa /ayuda.")
                    continue
                try:
                    respuesta = procesar_texto(chat_id, texto)
                except Exception as exc:
                    print(f"[ERROR COMANDO] {exc}")
                    respuesta = "Ocurrió un error procesando el comando. Intenta nuevamente."
                enviar(chat_id, respuesta)

        except KeyboardInterrupt:
            print("\nCerrando servicio de mensajería...")
            break
        except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            print(f"[TELEGRAM] {exc}")
            time.sleep(3)
        except Exception as exc:
            print(f"[ERROR] {exc}")
            time.sleep(2)


if __name__ == "__main__":
    main()
