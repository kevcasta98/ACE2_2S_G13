#!/usr/bin/env python3
# ============================================================
# PORTUS - Verificacion de pesajes / retenciones v0.7
# ============================================================

from db_portus import conectar, inicializar_bd

inicializar_bd()
conn = conectar()

print("=== PORTUS - Verificacion PESAJE v0.7 ===\n")

print("Turnos activos:")
turnos = conn.execute(
    """
    SELECT t.id, c.placa, t.manifiesto_id, t.contenedor_id,
           t.operacion, t.estado, t.estacion
    FROM turnos t
    JOIN camiones c ON c.id = t.camion_id
    WHERE t.estado NOT IN ('Cerrado','Anulado')
    ORDER BY t.inicio, t.id
    """
).fetchall()
if not turnos:
    print("- Ninguno")
else:
    for f in turnos:
        print(
            f"- {f['id']} | {f['placa']} | {f['manifiesto_id']} | "
            f"{f['contenedor_id']} | {f['operacion']} | {f['estado']} | {f['estacion']}"
        )

print("\nUltimos pesajes persistidos:")
pesajes = conn.execute(
    """
    SELECT id, turno_id, tipo, peso_medido_g, peso_esperado_g,
           diferencia_g, muestras, resultado, timestamp
    FROM pesajes
    ORDER BY id DESC
    LIMIT 10
    """
).fetchall()
if not pesajes:
    print("- Ninguno")
else:
    for f in pesajes:
        print(
            f"- #{f['id']} | {f['turno_id']} | {f['tipo']} | "
            f"medido={f['peso_medido_g']} g | esperado={f['peso_esperado_g']} g | "
            f"dif={f['diferencia_g']} g | muestras={f['muestras']} | {f['resultado']}"
        )

print("\nRetenciones activas:")
rets = conn.execute(
    """
    SELECT id, turno_id, causa, plaza, rol_resolutor, motivo,
           peso_declarado_g, peso_medido_g
    FROM retenciones
    WHERE estado = 'ACTIVA'
    ORDER BY id
    """
).fetchall()
if not rets:
    print("- Ninguna")
else:
    for f in rets:
        print(
            f"- R{f['id']} | {f['turno_id']} | {f['causa']} | plaza={f['plaza']} | "
            f"resolver={f['rol_resolutor']} | {f['motivo']}"
        )

print("\nPlazas logicas:")
for f in conn.execute(
    "SELECT numero, ocupada, turno_id, ocupada_desde FROM plazas_retencion ORDER BY numero"
):
    print(
        f"- Plaza {f['numero']}: "
        f"{'OCUPADA' if f['ocupada'] else 'LIBRE'}"
        + (f" | {f['turno_id']}" if f['turno_id'] else "")
    )

conn.close()
