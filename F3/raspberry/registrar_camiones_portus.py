#!/usr/bin/env python3
# ============================================================
# PORTUS - Registro de camiones físicos en SQLite
# Compatible con PORTUS Web v0.5
# ============================================================

from db_portus import conectar, inicializar_bd

TARA_G = 23.9

CAMIONES = [
    # Los UID coinciden con PORTUS_Fase2_v03_Eventos_Garita.ino
    ("CAM-01", "322C4507", "Transportes Quetzal"),
    ("CAM-02", "EA225305", "Transportes Quetzal"),
    ("CAM-03", "409A9558", "Transportes Quetzal"),
    ("CAM-04", "E158F3B0", "Logística Maya"),
    ("CAM-05", "E116F9B0", "Logística Maya"),
    ("CAM-06", "59CF9229", "Logística Maya"),
]


def main():
    inicializar_bd()
    conn = conectar()

    try:
        transportistas = {
            fila["nombre"]: fila["id"]
            for fila in conn.execute(
                "SELECT id, nombre FROM transportistas WHERE activo = 1"
            ).fetchall()
        }

        faltantes = [
            nombre
            for _, _, nombre in CAMIONES
            if nombre not in transportistas
        ]

        if faltantes:
            print("ERROR: faltan transportistas en la base de datos:")
            for nombre in faltantes:
                print(f"  - {nombre}")
            print("\nNo se realizó ningún cambio.")
            return

        for placa, uid, nombre_transportista in CAMIONES:
            transportista_id = transportistas[nombre_transportista]

            por_placa = conn.execute(
                "SELECT id, placa, rfid_uid FROM camiones WHERE placa = ?",
                (placa,),
            ).fetchone()

            por_uid = conn.execute(
                "SELECT id, placa, rfid_uid FROM camiones WHERE rfid_uid = ?",
                (uid,),
            ).fetchone()

            if (
                por_placa is not None
                and por_uid is not None
                and por_placa["id"] != por_uid["id"]
            ):
                raise RuntimeError(
                    f"Conflicto: {placa} y UID {uid} pertenecen a filas distintas."
                )

            existente = por_placa or por_uid

            if existente is None:
                conn.execute(
                    """
                    INSERT INTO camiones(
                        placa, rfid_uid, transportista_id, tara_g, activo
                    )
                    VALUES (?, ?, ?, ?, 1)
                    """,
                    (placa, uid, transportista_id, TARA_G),
                )
                accion = "CREADO"
            else:
                conn.execute(
                    """
                    UPDATE camiones
                    SET placa = ?,
                        rfid_uid = ?,
                        transportista_id = ?,
                        tara_g = ?,
                        activo = 1
                    WHERE id = ?
                    """,
                    (placa, uid, transportista_id, TARA_G, existente["id"]),
                )
                accion = "ACTUALIZADO"

            print(
                f"[{accion}] {placa} | UID {uid} | "
                f"{nombre_transportista} | tara {TARA_G:.1f} g"
            )

        conn.commit()

        print("\n=== Catálogo final de camiones ===")
        filas = conn.execute(
            """
            SELECT c.placa, c.rfid_uid, c.tara_g, c.activo,
                   t.nombre AS transportista
            FROM camiones c
            LEFT JOIN transportistas t ON t.id = c.transportista_id
            ORDER BY c.placa
            """
        ).fetchall()

        for fila in filas:
            estado = "ACTIVO" if fila["activo"] else "INACTIVO"
            print(
                f"{fila['placa']} | RFID {fila['rfid_uid']} | "
                f"{fila['transportista'] or 'SIN TRANSPORTISTA'} | "
                f"{fila['tara_g']} g | {estado}"
            )

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
