#!/usr/bin/env python3
# ============================================================
# PORTUS - Servicio de sincronizacion de pesaje / retenciones
# Fase 2 / v0.7
#
# Flujo:
#   Arduino detecta meseta y calcula peso -> EVT PESAJE -> MQTT
#   este servicio actualiza turno / retencion / plaza logica en SQLite
#
# El controlador conserva el muestreo, filtrado y la decision fisica
# inmediata de la aguja para poder completar con seguridad un turno
# ya ingresado si el servidor se desconecta.
# ============================================================

from __future__ import annotations

import json
from datetime import datetime

import paho.mqtt.client as mqtt

from db_portus import conectar, inicializar_bd
from citas_portus import ahora_local, encolar_notificacion

MQTT_HOST = "localhost"
MQTT_PORT = 1883
MQTT_KEEPALIVE = 60
TOPIC_PESAJE = "portus/evt/pesaje"


def numero(valor, default=0.0) -> float:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return float(default)


def entero(valor, default=0) -> int:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return int(default)


def ahora_db() -> str:
    return ahora_local().replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")


def obtener_turno(conn, turno_id: str):
    return conn.execute(
        """
        SELECT
            t.id,
            t.estado,
            t.estacion,
            t.manifiesto_id,
            t.camion_id,
            t.contenedor_id,
            t.operacion,
            m.peso_declarado_g,
            m.tolerancia_pct,
            m.transportista_id,
            c.placa,
            d.canal
        FROM turnos t
        JOIN manifiestos m ON m.id = t.manifiesto_id
        JOIN camiones c ON c.id = t.camion_id
        LEFT JOIN declaraciones d ON d.manifiesto_id = t.manifiesto_id
        WHERE t.id = ?
        LIMIT 1
        """,
        (turno_id,),
    ).fetchone()


def plaza_libre(conn):
    return conn.execute(
        """
        SELECT numero
        FROM plazas_retencion
        WHERE ocupada = 0
        ORDER BY numero
        LIMIT 1
        """
    ).fetchone()


def alarma_parqueo_lleno(conn, turno_id: str) -> None:
    datos = json.dumps(
        {"turno": turno_id, "causa": "SIN_PLAZA_LOGICA"},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    conn.execute(
        """
        INSERT INTO alarmas(codigo, severidad, timestamp, datos_json)
        VALUES ('AL11', 'Media', ?, ?)
        """,
        (ahora_local().isoformat(timespec="seconds"), datos),
    )


def notificar_retencion(
    conn,
    turno,
    causa: str,
    peso_medido: float,
    peso_esperado: float,
    diferencia: float,
    plaza: int | None,
) -> None:
    if not turno["transportista_id"]:
        return

    if causa == "RT03":
        mensaje = (
            f"Vehiculo {turno['placa']}, contenedor {turno['contenedor_id']}: "
            f"retenido por canal rojo de selectivo. "
            f"Plaza: {plaza if plaza is not None else 'pendiente'}."
        )
    elif causa == "RT02":
        mensaje = (
            f"Vehiculo {turno['placa']}, contenedor {turno['contenedor_id']}: "
            f"retenido por discrepancia de peso a la salida. "
            f"Esperado {peso_esperado:.1f} g, medido {peso_medido:.1f} g, "
            f"diferencia {diferencia:.1f} g."
        )
    else:
        mensaje = (
            f"Vehiculo {turno['placa']}, contenedor {turno['contenedor_id']}: "
            f"retenido por discrepancia de peso al ingreso. "
            f"Esperado {peso_esperado:.1f} g, medido {peso_medido:.1f} g, "
            f"diferencia {diferencia:.1f} g."
        )

    encolar_notificacion(conn, turno["transportista_id"], "VEHICULO_RETENIDO", mensaje)


def crear_retencion(
    conn,
    turno,
    causa: str,
    peso_medido: float,
    peso_esperado: float,
    diferencia: float,
    motivo: str,
) -> tuple[int | None, bool]:
    existente = conn.execute(
        """
        SELECT id, plaza, causa
        FROM retenciones
        WHERE turno_id = ? AND estado = 'ACTIVA'
        ORDER BY id DESC
        LIMIT 1
        """,
        (turno["id"],),
    ).fetchone()

    if existente is not None:
        return existente["plaza"], False

    libre = plaza_libre(conn)
    plaza = libre["numero"] if libre is not None else None

    estado_previo = turno["estado"]

    if plaza is not None:
        conn.execute(
            """
            UPDATE plazas_retencion
            SET ocupada = 1, turno_id = ?, ocupada_desde = ?
            WHERE numero = ?
            """,
            (turno["id"], ahora_db(), plaza),
        )
    else:
        alarma_parqueo_lleno(conn, turno["id"])

    rol = "AUTORIDAD" if causa in ("RT03", "RT05") else "TERMINAL"

    conn.execute(
        """
        INSERT INTO retenciones(
            turno_id, causa, plaza, estado, rol_resolutor,
            motivo, peso_declarado_g, peso_medido_g, inicio
        ) VALUES (?, ?, ?, 'ACTIVA', ?, ?, ?, ?, ?)
        """,
        (
            turno["id"],
            causa,
            plaza,
            rol,
            motivo,
            peso_esperado,
            peso_medido,
            ahora_db(),
        ),
    )

    conn.execute(
        """
        UPDATE turnos
        SET estado_previo_retencion = ?,
            estado = 'Retenido',
            estacion = 'PARQUEO_RETENCION',
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (estado_previo, turno["id"]),
    )

    notificar_retencion(
        conn,
        turno,
        causa,
        peso_medido,
        peso_esperado,
        diferencia,
        plaza,
    )

    return plaza, True


def procesar_pesaje(data: dict, evento_id: str | None = None) -> None:
    turno_id = str(data.get("turno") or "").strip().upper()
    tipo = str(data.get("tipo") or "").strip().upper()
    resultado = str(data.get("resultado") or "").strip().upper()
    canal = str(data.get("canal") or "").strip().upper()

    if not turno_id or tipo not in ("ENTRADA", "SALIDA"):
        print(f"[PESAJE] Evento incompleto: {data}")
        return

    peso_medido = numero(data.get("peso_medido_g"))
    peso_esperado = numero(data.get("peso_esperado_g"))
    diferencia = numero(data.get("diferencia_g"))
    muestras = entero(data.get("muestras"))

    conn = conectar()
    try:
        conn.execute("BEGIN IMMEDIATE")
        turno = obtener_turno(conn, turno_id)

        if evento_id and conn.execute(
            'SELECT 1 FROM eventos_aplicados WHERE evento_id=?', (evento_id,)
        ).fetchone():
            conn.rollback()
            print(f'[PESAJE] Evento duplicado {evento_id}, ignorado')
            return

        if turno is None:
            print(f"[PESAJE] {turno_id}: no existe en SQLite; evento ignorado")
            conn.rollback()
            return

        # La misma medición nunca debe volver a procesarse al recibir un evento
        # duplicado, ni cambiar un turno ya avanzado/resuelto/cerrado.
        estado_necesario = ('EnPesajeEntrada' if tipo == 'ENTRADA'
                            else 'EnPesajeSalida')
        if turno['estado'] != estado_necesario:
            conn.rollback()
            print(f"[PESAJE] {turno_id} está en {turno['estado']}; esperaba {estado_necesario}. Ignorado")
            return
        if evento_id:
            conn.execute('INSERT INTO eventos_aplicados(evento_id,tipo) VALUES (?,?)',
                         (evento_id, 'PESAJE'))

        # El canal de la declaracion es la fuente persistente. El valor del
        # evento se conserva solo como diagnostico.
        canal_db = str(turno["canal"] or canal or "").upper()

        if tipo == "ENTRADA":
            if resultado == "APROBADO" and canal_db != "ROJO":
                if turno["estado"] != "Retenido":
                    conn.execute(
                        """
                        UPDATE turnos
                        SET estado = 'EnRuta', estacion = 'RUTA', updated_at = datetime('now')
                        WHERE id = ?
                        """,
                        (turno_id,),
                    )
                conn.commit()
                print(
                    f"[PESAJE] {turno_id} ENTRADA APROBADA | "
                    f"{peso_medido:.1f}/{peso_esperado:.1f} g | {muestras} muestras -> EnRuta"
                )
                return

            if resultado == "CANAL_ROJO" or (resultado == "APROBADO" and canal_db == "ROJO"):
                plaza, nueva = crear_retencion(
                    conn,
                    turno,
                    "RT03",
                    peso_medido,
                    peso_esperado,
                    diferencia,
                    "Canal rojo de selectivo",
                )
                conn.commit()
                estado = "CREADA" if nueva else "YA EXISTIA"
                print(
                    f"[PESAJE] {turno_id} -> RT03 CANAL ROJO | plaza={plaza} | {estado}"
                )
                return

            if resultado in ("FUERA_TOLERANCIA", "INVALIDO"):
                motivo = (
                    "Pesaje de entrada sin meseta estable"
                    if resultado == "INVALIDO"
                    else "Discrepancia de peso al ingreso"
                )
                plaza, nueva = crear_retencion(
                    conn,
                    turno,
                    "RT01",
                    peso_medido,
                    peso_esperado,
                    diferencia,
                    motivo,
                )
                conn.commit()
                estado = "CREADA" if nueva else "YA EXISTIA"
                print(
                    f"[PESAJE] {turno_id} -> RT01 | plaza={plaza} | {estado} | "
                    f"medido={peso_medido:.1f} esperado={peso_esperado:.1f}"
                )
                return

        if tipo == "SALIDA":
            if resultado == "APROBADO":
                if turno["estado"] != "Retenido":
                    conn.execute(
                        """
                        UPDATE turnos
                        SET estado = 'EnSalida', estacion = 'SALIDA', updated_at = datetime('now')
                        WHERE id = ?
                        """,
                        (turno_id,),
                    )
                conn.commit()
                print(
                    f"[PESAJE] {turno_id} SALIDA APROBADA | "
                    f"{peso_medido:.1f}/{peso_esperado:.1f} g -> EnSalida"
                )
                return

            if resultado in ("FUERA_TOLERANCIA", "INVALIDO"):
                motivo = (
                    "Pesaje de salida sin meseta estable"
                    if resultado == "INVALIDO"
                    else "Discrepancia de peso a la salida"
                )
                plaza, nueva = crear_retencion(
                    conn,
                    turno,
                    "RT02",
                    peso_medido,
                    peso_esperado,
                    diferencia,
                    motivo,
                )
                conn.commit()
                estado = "CREADA" if nueva else "YA EXISTIA"
                print(f"[PESAJE] {turno_id} -> RT02 | plaza={plaza} | {estado}")
                return

        conn.rollback()
        print(f"[PESAJE] {turno_id}: resultado no manejado: tipo={tipo} resultado={resultado}")

    except Exception as exc:
        conn.rollback()
        print(f"[PESAJE ERROR] {turno_id}: {exc}")
    finally:
        conn.close()


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code != 0:
        print(f"[MQTT] Error de conexion: {reason_code}")
        return
    client.subscribe(TOPIC_PESAJE)
    print("[MQTT] Servicio PESAJE conectado")
    print(f"[MQTT] Suscrito a {TOPIC_PESAJE}")


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception as exc:
        print(f"[MQTT] JSON invalido: {exc}")
        return

    data = payload.get("data", {})
    if not isinstance(data, dict):
        return

    procesar_pesaje(data, str(payload.get('id') or '') or None)


def main():
    inicializar_bd()
    print("=== PORTUS - Servicio PESAJE v0.7 ===")
    print("Pesaje fisico: Arduino Mega")
    print("Turnos/retenciones/plazas logicas: Raspberry/SQLite")
    print("Ctrl+C para salir.\n")

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="portus-pesaje-service",
    )
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE)

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\nCerrando servicio PESAJE...")
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
