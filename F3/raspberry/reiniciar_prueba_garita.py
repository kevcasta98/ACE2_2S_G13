#!/usr/bin/env python3
# ============================================================
# PORTUS - Reinicio seguro de una prueba de garita antes de pesaje
# Uso: python reiniciar_prueba_garita.py T1
#
# Solo permite borrar un turno de prueba que aun esta en
# EnPesajeEntrada y que NO tiene pesajes ni retenciones.
# ============================================================

import sys
from db_portus import conectar, inicializar_bd

turno_id = (sys.argv[1] if len(sys.argv) > 1 else "T1").strip().upper()

inicializar_bd()
conn = conectar()

try:
    conn.execute("BEGIN IMMEDIATE")

    turno = conn.execute(
        """
        SELECT t.id, t.manifiesto_id, t.camion_id, t.contenedor_id,
               t.estado, c.placa
        FROM turnos t
        JOIN camiones c ON c.id = t.camion_id
        WHERE t.id = ?
        """,
        (turno_id,),
    ).fetchone()

    if turno is None:
        raise RuntimeError(f"No existe el turno {turno_id}.")

    if turno["estado"] != "EnPesajeEntrada":
        raise RuntimeError(
            f"Por seguridad no se reinicia {turno_id}: estado actual = {turno['estado']}."
        )

    pesajes = conn.execute(
        "SELECT COUNT(*) AS n FROM pesajes WHERE turno_id = ?",
        (turno_id,),
    ).fetchone()["n"]
    if pesajes:
        raise RuntimeError(
            f"Por seguridad no se reinicia {turno_id}: ya tiene {pesajes} pesaje(s)."
        )

    retenciones = conn.execute(
        "SELECT COUNT(*) AS n FROM retenciones WHERE turno_id = ?",
        (turno_id,),
    ).fetchone()["n"]
    if retenciones:
        raise RuntimeError(
            f"Por seguridad no se reinicia {turno_id}: ya tiene retenciones."
        )

    cita = conn.execute(
        """
        SELECT id, estado
        FROM citas
        WHERE manifiesto_id = ? AND camion_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (turno["manifiesto_id"], turno["camion_id"]),
    ).fetchone()

    conn.execute("DELETE FROM turnos WHERE id = ?", (turno_id,))
    conn.execute(
        """
        UPDATE manifiestos
        SET estado_operativo = 'PENDIENTE', updated_at = datetime('now')
        WHERE id = ?
        """,
        (turno["manifiesto_id"],),
    )

    if cita is not None and cita["estado"] == "CUMPLIDA":
        conn.execute(
            """
            UPDATE citas
            SET estado = 'CANCELADA', dentro_ventana = NULL
            WHERE id = ?
            """,
            (cita["id"],),
        )
        conn.execute(
            """
            INSERT INTO historial_citas(cita_id, accion, valor_anterior, valor_nuevo, detalle)
            VALUES (?, 'REINICIO_PRUEBA', 'CUMPLIDA', 'CANCELADA', ?)
            """,
            (cita["id"], f"Reinicio controlado de {turno_id} antes del pesaje"),
        )

    conn.commit()

    print("=== PORTUS - Reinicio de prueba completado ===")
    print(f"Turno eliminado: {turno_id}")
    print(f"Vehiculo: {turno['placa']}")
    print(f"Manifiesto: {turno['manifiesto_id']} -> PENDIENTE")
    print(f"Contenedor: {turno['contenedor_id']}")
    if cita is not None:
        print(f"Cita anterior: {cita['id']} -> CANCELADA")
    print("Ya puedes solicitar una cita nueva para repetir la prueba.")

except Exception as exc:
    conn.rollback()
    print(f"ERROR: {exc}")
    sys.exit(1)
finally:
    conn.close()
