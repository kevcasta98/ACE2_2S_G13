#!/usr/bin/env python3
from db_portus import DB_PATH, conectar, inicializar_bd

inicializar_bd()

conn = conectar()

tablas = [
    "usuarios",
    "navieras",
    "transportistas",
    "camiones",
    "contenedores",
    "manifiestos",
    "historial_manifiesto",
    "declaraciones",
    "notas_declaracion",
    "citas",
    "franjas_citas",
    "historial_citas",
    "mensajeria_vinculos",
    "notificaciones_transportista",
    "turnos",
    "pesajes",
    "plazas_retencion",
    "retenciones",
    "inventario",
    "alarmas",
    "eventos",
    "telemetria",
    "codigos_vinculacion",
]

print(f"\nBase de datos: {DB_PATH}")
print("Tablas creadas:")

for tabla in tablas:
    total = conn.execute(f"SELECT COUNT(*) AS n FROM {tabla}").fetchone()["n"]
    print(f"  {tabla:<20} {total}")

print("\nPlazas de retencion:")
for fila in conn.execute(
    "SELECT numero, ocupada, turno_id FROM plazas_retencion ORDER BY numero"
):
    print(
        f"  Plaza {fila['numero']}: "
        f"{'OCUPADA' if fila['ocupada'] else 'LIBRE'}"
    )

conn.close()
