#!/usr/bin/env python3
from db_portus import conectar, inicializar_bd

inicializar_bd()
conn = conectar()

print("=== PORTUS - Verificación del módulo Citas ===\n")

version = conn.execute("SELECT version FROM schema_info ORDER BY rowid DESC LIMIT 1").fetchone()
print(f"Esquema DB: v{version['version'] if version else '?'}")

print("\nTransportistas y vehículos activos:")
for t in conn.execute("SELECT id, nombre FROM transportistas WHERE activo = 1 ORDER BY nombre"):
    camiones = conn.execute(
        "SELECT placa, rfid_uid FROM camiones WHERE transportista_id = ? AND activo = 1 ORDER BY placa",
        (t["id"],),
    ).fetchall()
    print(f"- {t['nombre']}: {len(camiones)} vehículo(s)")
    for c in camiones:
        print(f"    {c['placa']} | RFID {c['rfid_uid']}")

print("\nCargas con levante otorgado disponibles para cita:")
filas = conn.execute(
    """
    SELECT t.nombre AS transportista, m.id AS manifiesto, m.contenedor_id,
           d.numero, d.canal
    FROM manifiestos m
    JOIN transportistas t ON t.id = m.transportista_id
    JOIN declaraciones d ON d.manifiesto_id = m.id
    WHERE m.anulado = 0
      AND m.estado_operativo = 'PENDIENTE'
      AND d.levante_estado = 'OTORGADO'
      AND NOT EXISTS (
          SELECT 1 FROM citas c
          WHERE c.contenedor_id = m.contenedor_id AND c.estado = 'PROGRAMADA'
      )
    ORDER BY t.nombre, m.contenedor_id
    """
).fetchall()
if not filas:
    print("- Ninguna")
else:
    for f in filas:
        print(
            f"- {f['transportista']} | {f['contenedor_id']} | "
            f"{f['manifiesto']} | declaración {f['numero']} | canal {f['canal']}"
        )

print("\nCitas PROGRAMADAS:")
citas = conn.execute(
    """
    SELECT c.id, c.contenedor_id, c.inicio, c.fin, t.nombre, cam.placa
    FROM citas c
    JOIN transportistas t ON t.id = c.transportista_id
    LEFT JOIN camiones cam ON cam.id = c.camion_id
    WHERE c.estado = 'PROGRAMADA'
    ORDER BY c.inicio
    """
).fetchall()
if not citas:
    print("- Ninguna")
else:
    for c in citas:
        print(f"- #{c['id']} {c['contenedor_id']} | {c['inicio']} - {c['fin']} | {c['nombre']} | {c['placa'] or '-'}")

print("\nVinculaciones de mensajería:")
vinculos = conn.execute(
    """
    SELECT mv.canal, mv.cuenta_id, t.nombre
    FROM mensajeria_vinculos mv
    JOIN transportistas t ON t.id = mv.transportista_id
    ORDER BY t.nombre
    """
).fetchall()
if not vinculos:
    print("- Ninguna")
else:
    for v in vinculos:
        print(f"- {v['nombre']} | {v['canal']} | cuenta {v['cuenta_id']}")

conn.close()
