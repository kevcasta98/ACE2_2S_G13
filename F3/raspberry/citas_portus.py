#!/usr/bin/env python3
# ============================================================
# PORTUS - Lógica compartida de citas y mensajería
# Fase 2 / v0.5
# ============================================================

from __future__ import annotations

import secrets
import string
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from db_portus import conectar

TZ_LOCAL = ZoneInfo("America/Guatemala")
FORMATO_DB = "%Y-%m-%d %H:%M:%S"
CAPACIDAD_FRANJA = 2
MINUTOS_FRANJA = 15
TOLERANCIA_POSTERIOR_MIN = 5


class ErrorCita(ValueError):
    pass


def ahora_local() -> datetime:
    return datetime.now(TZ_LOCAL)


def a_db(dt: datetime) -> str:
    if dt.tzinfo is not None:
        dt = dt.astimezone(TZ_LOCAL).replace(tzinfo=None)
    return dt.strftime(FORMATO_DB)


def desde_db(valor: str | None) -> datetime | None:
    if not valor:
        return None
    candidatos = (
        FORMATO_DB,
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    )
    for formato in candidatos:
        try:
            return datetime.strptime(valor, formato).replace(tzinfo=TZ_LOCAL)
        except ValueError:
            continue
    return None


def parsear_franja(valor: str) -> datetime:
    texto = (valor or "").strip()
    candidatos = (
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    )
    for formato in candidatos:
        try:
            dt = datetime.strptime(texto, formato).replace(tzinfo=TZ_LOCAL)
            break
        except ValueError:
            dt = None
    if dt is None:
        raise ErrorCita("La fecha y hora de la franja no son válidas.")
    if dt.minute % MINUTOS_FRANJA != 0 or dt.second != 0:
        raise ErrorCita("La franja debe iniciar en un múltiplo de 15 minutos.")
    return dt


def siguiente_cuarto(dt: datetime | None = None) -> datetime:
    dt = (dt or ahora_local()).astimezone(TZ_LOCAL).replace(second=0, microsecond=0)
    resto = dt.minute % MINUTOS_FRANJA
    if resto == 0:
        return dt + timedelta(minutes=MINUTOS_FRANJA)
    return dt + timedelta(minutes=MINUTOS_FRANJA - resto)


def _ocupacion(conn, inicio_db: str, excluir_cita_id: int | None = None) -> int:
    sql = "SELECT COUNT(*) AS n FROM citas WHERE inicio = ? AND estado = 'PROGRAMADA'"
    params: list[object] = [inicio_db]
    if excluir_cita_id is not None:
        sql += " AND id <> ?"
        params.append(excluir_cita_id)
    return conn.execute(sql, params).fetchone()["n"]


def _esta_bloqueada(conn, inicio_db: str) -> bool:
    fila = conn.execute(
        "SELECT bloqueada FROM franjas_citas WHERE inicio = ?",
        (inicio_db,),
    ).fetchone()
    return bool(fila and fila["bloqueada"])


def validar_franja_disponible(conn, inicio: datetime, excluir_cita_id: int | None = None) -> None:
    if inicio <= ahora_local():
        raise ErrorCita("La cita debe asignarse en una franja futura.")
    inicio_db = a_db(inicio)
    if _esta_bloqueada(conn, inicio_db):
        raise ErrorCita("La franja seleccionada está bloqueada.")
    if _ocupacion(conn, inicio_db, excluir_cita_id) >= CAPACIDAD_FRANJA:
        raise ErrorCita("La franja seleccionada ya alcanzó su capacidad máxima de 2 citas.")


def listar_franjas_disponibles(conn, limite: int = 8, desde: datetime | None = None,
                               excluir_cita_id: int | None = None) -> list[dict]:
    inicio = siguiente_cuarto(desde)
    resultado = []
    # Se recorren como máximo 14 días. El enunciado no fija horario de atención,
    # por lo que se usan franjas continuas de 15 minutos y solo se aplica capacidad.
    for _ in range(14 * 24 * 4):
        inicio_db = a_db(inicio)
        if not _esta_bloqueada(conn, inicio_db):
            ocupadas = _ocupacion(conn, inicio_db, excluir_cita_id)
            if ocupadas < CAPACIDAD_FRANJA:
                fin = inicio + timedelta(minutes=MINUTOS_FRANJA)
                resultado.append({
                    "inicio": inicio_db,
                    "fin": a_db(fin),
                    "ocupadas": ocupadas,
                    "disponibles": CAPACIDAD_FRANJA - ocupadas,
                    "etiqueta": f"{inicio.strftime('%d/%m/%Y %H:%M')} - {fin.strftime('%H:%M')}",
                })
                if len(resultado) >= limite:
                    break
        inicio += timedelta(minutes=MINUTOS_FRANJA)
    return resultado


def camiones_transportista(conn, transportista_id: int) -> list[dict]:
    filas = conn.execute(
        """
        SELECT id, placa, rfid_uid
        FROM camiones
        WHERE transportista_id = ? AND activo = 1
        ORDER BY placa
        """,
        (transportista_id,),
    ).fetchall()
    return [dict(f) for f in filas]


def manifiestos_elegibles_transportista(conn, transportista_id: int) -> list[dict]:
    filas = conn.execute(
        """
        SELECT m.id AS manifiesto_id, m.contenedor_id, m.operacion,
               d.numero AS declaracion_numero, d.canal
        FROM manifiestos m
        JOIN declaraciones d ON d.manifiesto_id = m.id
        WHERE m.transportista_id = ?
          AND m.anulado = 0
          AND m.estado_operativo = 'PENDIENTE'
          AND d.levante_estado = 'OTORGADO'
          AND NOT EXISTS (
              SELECT 1 FROM citas c
              WHERE c.contenedor_id = m.contenedor_id
                AND c.estado = 'PROGRAMADA'
          )
        ORDER BY m.created_at ASC, m.id ASC
        """,
        (transportista_id,),
    ).fetchall()
    return [dict(f) for f in filas]


def _manifiesto_elegible(conn, transportista_id: int, contenedor_id: str):
    return conn.execute(
        """
        SELECT m.id AS manifiesto_id, m.contenedor_id, m.operacion,
               d.numero AS declaracion_numero, d.canal
        FROM manifiestos m
        JOIN declaraciones d ON d.manifiesto_id = m.id
        WHERE m.transportista_id = ?
          AND m.contenedor_id = ?
          AND m.anulado = 0
          AND m.estado_operativo = 'PENDIENTE'
          AND d.levante_estado = 'OTORGADO'
        ORDER BY m.created_at DESC
        LIMIT 1
        """,
        (transportista_id, contenedor_id),
    ).fetchone()


def encolar_notificacion(conn, transportista_id: int, tipo: str, mensaje: str) -> int:
    cur = conn.execute(
        """
        INSERT INTO notificaciones_transportista(transportista_id, tipo, mensaje)
        VALUES (?, ?, ?)
        """,
        (transportista_id, tipo, mensaje),
    )
    return cur.lastrowid


def crear_cita(transportista_id: int, contenedor_id: str, inicio_valor: str, camion_id: int | None = None) -> dict:
    inicio = parsear_franja(inicio_valor)
    fin = inicio + timedelta(minutes=MINUTOS_FRANJA)
    conn = conectar()
    try:
        conn.execute("BEGIN IMMEDIATE")
        manifiesto = _manifiesto_elegible(conn, transportista_id, contenedor_id)
        if manifiesto is None:
            raise ErrorCita(
                "El contenedor no pertenece al transportista, no tiene levante otorgado o no tiene un manifiesto pendiente."
            )

        existente = conn.execute(
            "SELECT id FROM citas WHERE contenedor_id = ? AND estado = 'PROGRAMADA' LIMIT 1",
            (contenedor_id,),
        ).fetchone()
        if existente:
            raise ErrorCita("El contenedor ya tiene una cita vigente.")

        if camion_id is None:
            camiones = camiones_transportista(conn, transportista_id)
            if len(camiones) == 1:
                camion_id = camiones[0]["id"]
            elif len(camiones) == 0:
                raise ErrorCita("El transportista no tiene vehículos activos registrados.")
            else:
                raise ErrorCita("Debe seleccionar uno de los vehículos registrados del transportista.")

        camion = conn.execute(
            "SELECT id, placa FROM camiones WHERE id = ? AND transportista_id = ? AND activo = 1",
            (camion_id, transportista_id),
        ).fetchone()
        if camion is None:
            raise ErrorCita("El vehículo seleccionado no pertenece al transportista o está inactivo.")

        validar_franja_disponible(conn, inicio)

        cur = conn.execute(
            """
            INSERT INTO citas(
                manifiesto_id, contenedor_id, transportista_id, camion_id,
                inicio, fin, estado, dentro_ventana, recordatorio_enviado, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'PROGRAMADA', NULL, 0, datetime('now'))
            """,
            (
                manifiesto["manifiesto_id"], contenedor_id, transportista_id, camion_id,
                a_db(inicio), a_db(fin),
            ),
        )
        cita_id = cur.lastrowid
        conn.execute(
            """
            INSERT INTO historial_citas(cita_id, accion, valor_nuevo, detalle)
            VALUES (?, 'ASIGNADA', ?, 'Cita solicitada por el transportista')
            """,
            (cita_id, a_db(inicio)),
        )
        mensaje = (
            f"Cita asignada para {contenedor_id}: "
            f"{inicio.strftime('%d/%m/%Y')} de {inicio.strftime('%H:%M')} a {fin.strftime('%H:%M')}."
        )
        encolar_notificacion(conn, transportista_id, "CITA_ASIGNADA", mensaje)
        conn.commit()
        return {
            "id": cita_id,
            "manifiesto_id": manifiesto["manifiesto_id"],
            "contenedor_id": contenedor_id,
            "inicio": a_db(inicio),
            "fin": a_db(fin),
            "canal": manifiesto["canal"],
            "camion_id": camion_id,
            "placa": camion["placa"],
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cancelar_cita(cita_id: int, usuario_id: int | None = None) -> dict:
    conn = conectar()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cita = conn.execute(
            "SELECT * FROM citas WHERE id = ?",
            (cita_id,),
        ).fetchone()
        if cita is None:
            raise ErrorCita("La cita no existe.")
        if cita["estado"] != "PROGRAMADA":
            raise ErrorCita("Solo puede cancelarse una cita PROGRAMADA.")

        conn.execute(
            """
            UPDATE citas
            SET estado = 'CANCELADA', updated_at = datetime('now')
            WHERE id = ?
            """,
            (cita_id,),
        )
        conn.execute(
            """
            INSERT INTO historial_citas(cita_id, accion, valor_anterior, valor_nuevo, usuario_id, detalle)
            VALUES (?, 'CANCELADA', 'PROGRAMADA', 'CANCELADA', ?, 'Cancelada por TERMINAL')
            """,
            (cita_id, usuario_id),
        )
        encolar_notificacion(
            conn,
            cita["transportista_id"],
            "CITA_CANCELADA",
            f"La cita del contenedor {cita['contenedor_id']} fue cancelada.",
        )
        conn.commit()
        return dict(cita)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def reprogramar_cita(cita_id: int, nuevo_inicio_valor: str, usuario_id: int | None = None) -> dict:
    nuevo_inicio = parsear_franja(nuevo_inicio_valor)
    nuevo_fin = nuevo_inicio + timedelta(minutes=MINUTOS_FRANJA)
    conn = conectar()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cita = conn.execute("SELECT * FROM citas WHERE id = ?", (cita_id,)).fetchone()
        if cita is None:
            raise ErrorCita("La cita no existe.")
        if cita["estado"] != "PROGRAMADA":
            raise ErrorCita("Solo puede reprogramarse una cita PROGRAMADA.")
        validar_franja_disponible(conn, nuevo_inicio, excluir_cita_id=cita_id)

        anterior = cita["inicio"]
        conn.execute(
            """
            UPDATE citas
            SET inicio = ?, fin = ?, recordatorio_enviado = 0,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (a_db(nuevo_inicio), a_db(nuevo_fin), cita_id),
        )
        conn.execute(
            """
            INSERT INTO historial_citas(cita_id, accion, valor_anterior, valor_nuevo, usuario_id, detalle)
            VALUES (?, 'REPROGRAMADA', ?, ?, ?, 'Reprogramada por TERMINAL')
            """,
            (cita_id, anterior, a_db(nuevo_inicio), usuario_id),
        )
        encolar_notificacion(
            conn,
            cita["transportista_id"],
            "CITA_REPROGRAMADA",
            (
                f"La cita del contenedor {cita['contenedor_id']} fue reprogramada para "
                f"{nuevo_inicio.strftime('%d/%m/%Y')} de {nuevo_inicio.strftime('%H:%M')} "
                f"a {nuevo_fin.strftime('%H:%M')}."
            ),
        )
        conn.commit()
        return {
            **dict(cita),
            "inicio": a_db(nuevo_inicio),
            "fin": a_db(nuevo_fin),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def bloquear_franja(inicio_valor: str, usuario_id: int | None = None, motivo: str = "") -> dict:
    inicio = parsear_franja(inicio_valor)
    if inicio <= ahora_local():
        raise ErrorCita("Solo pueden bloquearse franjas futuras.")
    fin = inicio + timedelta(minutes=MINUTOS_FRANJA)
    conn = conectar()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO franjas_citas(inicio, fin, bloqueada, motivo, bloqueada_por, updated_at)
            VALUES (?, ?, 1, ?, ?, datetime('now'))
            ON CONFLICT(inicio) DO UPDATE SET
                fin = excluded.fin,
                bloqueada = 1,
                motivo = excluded.motivo,
                bloqueada_por = excluded.bloqueada_por,
                updated_at = datetime('now')
            """,
            (a_db(inicio), a_db(fin), motivo or None, usuario_id),
        )
        conn.commit()
        return {"inicio": a_db(inicio), "fin": a_db(fin)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def desbloquear_franja(inicio_valor: str, usuario_id: int | None = None) -> None:
    inicio = parsear_franja(inicio_valor)
    conn = conectar()
    try:
        conn.execute(
            """
            UPDATE franjas_citas
            SET bloqueada = 0, bloqueada_por = ?, updated_at = datetime('now')
            WHERE inicio = ?
            """,
            (usuario_id, a_db(inicio)),
        )
        conn.commit()
    finally:
        conn.close()


def generar_codigo_vinculacion(transportista_id: int) -> tuple[str, str]:
    alfabeto = string.ascii_uppercase + string.digits
    expira = datetime.now(timezone.utc) + timedelta(minutes=60)
    expira_db = expira.strftime(FORMATO_DB)
    conn = conectar()
    try:
        for _ in range(30):
            codigo = "".join(secrets.choice(alfabeto) for _ in range(6))
            try:
                conn.execute(
                    """
                    INSERT INTO codigos_vinculacion(codigo, transportista_id, expira_at, usado)
                    VALUES (?, ?, ?, 0)
                    """,
                    (codigo, transportista_id, expira_db),
                )
                conn.commit()
                return codigo, expira_db
            except Exception as exc:
                conn.rollback()
                if "UNIQUE" not in str(exc).upper():
                    raise
        raise RuntimeError("No se pudo generar un código de vinculación único.")
    finally:
        conn.close()


def vincular_cuenta(canal: str, cuenta_id: str, codigo: str) -> str:
    canal = canal.strip().upper()
    cuenta_id = str(cuenta_id).strip()
    codigo = codigo.strip().upper()
    conn = conectar()
    try:
        conn.execute("BEGIN IMMEDIATE")
        fila = conn.execute(
            """
            SELECT cv.codigo, cv.transportista_id, cv.expira_at, cv.usado, t.nombre
            FROM codigos_vinculacion cv
            JOIN transportistas t ON t.id = cv.transportista_id
            WHERE cv.codigo = ?
            """,
            (codigo,),
        ).fetchone()
        if fila is None or fila["usado"]:
            raise ErrorCita("Código de vinculación inválido o ya utilizado.")
        ahora_utc = datetime.now(timezone.utc).strftime(FORMATO_DB)
        if fila["expira_at"] < ahora_utc:
            raise ErrorCita("Código de vinculación inválido o vencido.")

        conn.execute("DELETE FROM mensajeria_vinculos WHERE canal = ? AND cuenta_id = ?", (canal, cuenta_id))
        conn.execute("DELETE FROM mensajeria_vinculos WHERE canal = ? AND transportista_id = ?", (canal, fila["transportista_id"]))
        conn.execute(
            """
            INSERT INTO mensajeria_vinculos(canal, cuenta_id, transportista_id)
            VALUES (?, ?, ?)
            """,
            (canal, cuenta_id, fila["transportista_id"]),
        )
        conn.execute("UPDATE codigos_vinculacion SET usado = 1 WHERE codigo = ?", (codigo,))
        conn.commit()
        return fila["nombre"]
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def transportista_por_cuenta(canal: str, cuenta_id: str) -> dict | None:
    conn = conectar()
    try:
        fila = conn.execute(
            """
            SELECT t.id, t.nombre
            FROM mensajeria_vinculos mv
            JOIN transportistas t ON t.id = mv.transportista_id
            WHERE mv.canal = ? AND mv.cuenta_id = ? AND t.activo = 1
            """,
            (canal.upper(), str(cuenta_id)),
        ).fetchone()
        return dict(fila) if fila else None
    finally:
        conn.close()


def actualizar_citas_vencidas() -> int:
    limite = ahora_local() - timedelta(minutes=TOLERANCIA_POSTERIOR_MIN)
    conn = conectar()
    try:
        cur = conn.execute(
            """
            UPDATE citas
            SET estado = 'VENCIDA', updated_at = datetime('now')
            WHERE estado = 'PROGRAMADA' AND fin < ?
            """,
            (a_db(limite),),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def programar_recordatorios_una_hora() -> int:
    ahora = ahora_local()
    maximo = ahora + timedelta(hours=1)
    conn = conectar()
    try:
        filas = conn.execute(
            """
            SELECT id, contenedor_id, transportista_id, inicio, fin
            FROM citas
            WHERE estado = 'PROGRAMADA'
              AND COALESCE(recordatorio_enviado, 0) = 0
              AND inicio > ? AND inicio <= ?
            ORDER BY inicio
            """,
            (a_db(ahora), a_db(maximo)),
        ).fetchall()
        for c in filas:
            inicio = desde_db(c["inicio"])
            fin = desde_db(c["fin"])
            if not inicio or not fin:
                continue
            encolar_notificacion(
                conn,
                c["transportista_id"],
                "RECORDATORIO_CITA",
                (
                    f"Recordatorio: falta aproximadamente una hora para la cita del contenedor "
                    f"{c['contenedor_id']}, ventana {inicio.strftime('%d/%m/%Y %H:%M')} - {fin.strftime('%H:%M')}."
                ),
            )
            conn.execute("UPDATE citas SET recordatorio_enviado = 1 WHERE id = ?", (c["id"],))
        conn.commit()
        return len(filas)
    finally:
        conn.close()


def validar_ventana_cita(cita: dict, momento: datetime | None = None) -> bool:
    momento = (momento or ahora_local()).astimezone(TZ_LOCAL)
    inicio = desde_db(cita.get("inicio"))
    fin = desde_db(cita.get("fin"))
    if not inicio or not fin:
        return False
    return inicio <= momento <= fin + timedelta(minutes=TOLERANCIA_POSTERIOR_MIN)
