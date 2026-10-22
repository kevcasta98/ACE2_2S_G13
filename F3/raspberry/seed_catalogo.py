#!/usr/bin/env python3
# ============================================================
# PORTUS - Catálogo inicial para pruebas de Fase 2
# ============================================================

from db_portus import conectar, inicializar_bd

NAVIERA_CONTENEDORES = {
    "Naviera Atlántico": ["C1", "C2", "C3"],
    "Naviera Pacífico": ["C4", "C5", "C6"],
}

TRANSPORTISTAS = [
    "Transportes Quetzal",
    "Logística Maya",
]


def main():
    inicializar_bd()
    conn = conectar()

    for nombre in NAVIERA_CONTENEDORES:
        conn.execute(
            "INSERT OR IGNORE INTO navieras(nombre) VALUES (?)",
            (nombre,),
        )

    for nombre in TRANSPORTISTAS:
        conn.execute(
            "INSERT OR IGNORE INTO transportistas(nombre) VALUES (?)",
            (nombre,),
        )

    conn.commit()

    for naviera, contenedores in NAVIERA_CONTENEDORES.items():
        naviera_id = conn.execute(
            "SELECT id FROM navieras WHERE nombre = ?",
            (naviera,),
        ).fetchone()["id"]

        for contenedor in contenedores:
            existente = conn.execute(
                "SELECT id FROM contenedores WHERE id = ?",
                (contenedor,),
            ).fetchone()

            if existente is None:
                conn.execute(
                    """
                    INSERT INTO contenedores(
                        id, naviera_id, estado, ubicacion
                    )
                    VALUES (?, ?, 'DISPONIBLE', 'FUERA_TERMINAL')
                    """,
                    (contenedor, naviera_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE contenedores
                    SET naviera_id = ?
                    WHERE id = ?
                    """,
                    (naviera_id, contenedor),
                )

    conn.commit()

    print("Catálogo PORTUS listo.\n")
    for naviera, contenedores in NAVIERA_CONTENEDORES.items():
        print(f"{naviera}: {', '.join(contenedores)}")

    print("\nTransportistas:")
    for nombre in TRANSPORTISTAS:
        print(f"- {nombre}")

    conn.close()


if __name__ == "__main__":
    main()
