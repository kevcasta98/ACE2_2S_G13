#!/usr/bin/env python3
# ============================================================
# PORTUS - Consulta rapida de la base de datos
# ============================================================

import json
from db_portus import DB_PATH, conectar, inicializar_bd

inicializar_bd()
conn = conectar()

print(f"=== PORTUS DB ===")
print(f"{DB_PATH}\n")

for tabla in ("eventos", "telemetria", "pesajes", "alarmas"):
    n = conn.execute(f"SELECT COUNT(*) AS n FROM {tabla}").fetchone()["n"]
    print(f"{tabla:<12}: {n}")

print("\nUltimos 15 eventos:")
filas = conn.execute(
    """
    SELECT timestamp, topic, tipo, secuencia, datos_json
    FROM eventos
    ORDER BY recibido_at DESC, rowid DESC
    LIMIT 15
    """
).fetchall()

if not filas:
    print("  Sin eventos almacenados.")
else:
    for fila in reversed(filas):
        try:
            datos = json.loads(fila["datos_json"])
        except json.JSONDecodeError:
            datos = fila["datos_json"]

        print(
            f"  {fila['timestamp']} | "
            f"seq={fila['secuencia']} | "
            f"{fila['topic']} | "
            f"{fila['tipo']} | "
            f"{datos}"
        )

conn.close()
