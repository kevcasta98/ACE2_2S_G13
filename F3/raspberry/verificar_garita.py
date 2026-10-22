#!/usr/bin/env python3
from datetime import timedelta

from db_portus import conectar, inicializar_bd
from citas_portus import ahora_local, desde_db

inicializar_bd()
conn = conectar()
ahora = ahora_local()

print("=== PORTUS - Verificacion GARITA v0.6 ===")
print(f"Hora Guatemala: {ahora.strftime('%d/%m/%Y %H:%M:%S')}\n")

filas = conn.execute(
    """
    SELECT c.id AS cita_id, c.inicio, c.fin, c.estado,
           cam.placa, cam.rfid_uid,
           m.id AS manifiesto_id, m.contenedor_id, m.operacion,
           m.peso_declarado_g, m.tolerancia_pct,
           d.levante_estado, d.canal,
           t.nombre AS transportista
    FROM citas c
    JOIN camiones cam ON cam.id = c.camion_id
    JOIN manifiestos m ON m.id = c.manifiesto_id
    LEFT JOIN declaraciones d ON d.manifiesto_id = m.id
    LEFT JOIN transportistas t ON t.id = c.transportista_id
    WHERE c.estado = 'PROGRAMADA'
    ORDER BY c.inicio, c.id
    """
).fetchall()

if not filas:
    print("No hay citas PROGRAMADAS. Crea/reprograma una antes de probar el RFID.")
else:
    print("Citas PROGRAMADAS:")
    for f in filas:
        inicio = desde_db(f["inicio"])
        fin = desde_db(f["fin"])
        en_ventana = bool(inicio and fin and inicio <= ahora <= fin + timedelta(minutes=5))
        estado = "EN VENTANA AHORA" if en_ventana else "FUERA DE VENTANA"
        print(
            f"- {f['placa']} | RFID {f['rfid_uid']} | {f['manifiesto_id']} | "
            f"{f['contenedor_id']} | {f['operacion']} | levante {f['levante_estado']} | "
            f"canal {f['canal']} | {f['inicio']} a {f['fin']} | {estado}"
        )

print("\nTurnos activos en SQLite:")
activos = conn.execute(
    """
    SELECT tu.id, cam.placa, tu.manifiesto_id, tu.estado, tu.estacion
    FROM turnos tu
    JOIN camiones cam ON cam.id = tu.camion_id
    WHERE tu.estado NOT IN ('Cerrado','Anulado')
    ORDER BY tu.inicio
    """
).fetchall()
if not activos:
    print("- Ninguno")
else:
    for f in activos:
        print(f"- {f['id']} | {f['placa']} | {f['manifiesto_id']} | {f['estado']} | {f['estacion']}")

conn.close()
