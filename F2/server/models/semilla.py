# -*- coding: utf-8 -*-
"""
Creación del esquema y datos iniciales.

Usuarios mínimos exigidos (2.1). Contraseña de prueba de TODOS: 1234 (igual
que el mock del Compañero 2; se guarda con hash). Documentar en la entrega.

    operador1   TERMINAL
    naviera1    NAVIERA   (NAVIERA1)
    naviera2    NAVIERA   (NAVIERA2)
    agente1     AGENTE
    autoridad1  AUTORIDAD
    transportista1 / transportista2  TRANSPORTISTA (sin acceso web; usan el bot)

Vehículos: los 3 camiones de la Fase 1 (control_central.cpp) con su UID RFID real.
"""
from auth.sesion import hash_password
from models import db
from models import constantes as C

PASSWORD_PRUEBA = "1234"

NAVIERAS = [("NAVIERA1", "Naviera Pacífico S.A."), ("NAVIERA2", "Naviera Atlántico S.A.")]
TRANSPORTISTAS = [("TRANS-A", "Transportes Alfa", "+50200000001"),
                  ("TRANS-B", "Transportes Beta", "+50200000002")]

# (username, nombre, rol, naviera_codigo, transportista_codigo)
USUARIOS = [
    ("operador1", "Carlos Operador", C.ROL_TERMINAL, None, None),
    ("naviera1", "Naviera Pacífico S.A.", C.ROL_NAVIERA, "NAVIERA1", None),
    ("naviera2", "Naviera Atlántico S.A.", C.ROL_NAVIERA, "NAVIERA2", None),
    ("agente1", "Lic. Ana Agente", C.ROL_AGENTE, None, None),
    ("autoridad1", "SAT - Autoridad Aduanera", C.ROL_AUTORIDAD, None, None),
    ("transportista1", "Transportes Alfa", C.ROL_TRANSPORTISTA, None, "TRANS-A"),
    ("transportista2", "Transportes Beta", C.ROL_TRANSPORTISTA, None, "TRANS-B"),
]

# (rfid_uid, placa, transportista, tara_g) -> UIDs reales del firmware Fase 1.
# El 4.º vehículo es para el escenario E11 (parqueo lleno): cambiar el UID por el de una 4.ª tarjeta.
VEHICULOS = [
    ("EA225305", "C-101", "TRANS-A", 500),
    ("99A08729", "C-202", "TRANS-B", 520),
    ("E116F9B0", "C-303", "TRANS-A", 500),
    ("00000004", "C-404", "TRANS-B", 500),
]

# Catálogo de contenedores físicos de la maqueta (ajustar a los que realmente existan)
CONTENEDORES = [f"CONT-{i:03d}" for i in range(1, 11)]

# Inventario inicial del patio: DEBE coincidir con la disposición física antes de la demo.
# Formato: (posicion, nivel, contenedor, naviera). Vacío = patio vacío.
INVENTARIO_INICIAL = [
    (1, 1, "CONT-001", "NAVIERA1"),
    (1, 2, "CONT-002", "NAVIERA1"),
    (2, 1, "CONT-003", "NAVIERA2"),
]


def crear_esquema(ruta_schema):
    with open(ruta_schema, encoding="utf-8") as f:
        db.con().executescript(f.read())


def cargar_base():
    """Datos que siempre deben existir (idempotente)."""
    with db.transaccion():
        for codigo, (desc, sev) in C.ALARMAS.items():
            db.ejecutar("INSERT OR IGNORE INTO alarmas_catalogo (codigo, descripcion, severidad) VALUES (?, ?, ?)",
                        (codigo, desc, sev))
        for n in range(1, C.POSICIONES_PATIO + 1):
            db.ejecutar("INSERT OR IGNORE INTO posiciones_patio (numero) VALUES (?)", (n,))
        for n in range(1, C.PLAZAS_PARQUEO + 1):
            db.ejecutar("INSERT OR IGNORE INTO plazas_parqueo (numero) VALUES (?)", (n,))
        if db.leer_estado("politica_patio") is None:
            db.guardar_estado("politica_patio", C.POLITICA_FASE1)
        if db.leer_estado("modo") is None:
            db.guardar_estado("modo", C.MODO_NORMAL)


def cargar_demo():
    """Usuarios, vehículos, contenedores e inventario de prueba (idempotente)."""
    with db.transaccion():
        for codigo, nombre in NAVIERAS:
            db.ejecutar("INSERT OR IGNORE INTO navieras (codigo, nombre) VALUES (?, ?)", (codigo, nombre))
        for codigo, nombre, tel in TRANSPORTISTAS:
            db.ejecutar("INSERT OR IGNORE INTO transportistas (codigo, nombre, telefono) VALUES (?, ?, ?)",
                        (codigo, nombre, tel))
        nav = {r["codigo"]: r["id"] for r in db.todos("SELECT id, codigo FROM navieras")}
        tra = {r["codigo"]: r["id"] for r in db.todos("SELECT id, codigo FROM transportistas")}
        for username, nombre, rol, n, t in USUARIOS:
            db.ejecutar("""INSERT OR IGNORE INTO usuarios (username, password_hash, nombre, rol, naviera_id, transportista_id)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (username, hash_password(PASSWORD_PRUEBA), nombre, rol, nav.get(n), tra.get(t)))
        for rfid, placa, t, tara in VEHICULOS:
            db.ejecutar("INSERT OR IGNORE INTO vehiculos (rfid_uid, placa, transportista_id, tara_g) VALUES (?, ?, ?, ?)",
                        (rfid, placa, tra[t], tara))
        for codigo in CONTENEDORES:
            db.ejecutar("INSERT OR IGNORE INTO contenedores (codigo) VALUES (?)", (codigo,))
        for pos, nivel, cont, n in INVENTARIO_INICIAL:
            db.ejecutar(f"UPDATE posiciones_patio SET contenedor_n{nivel} = ? WHERE numero = ? AND contenedor_n{nivel} IS NULL",
                        (cont, pos))
            db.ejecutar("""UPDATE contenedores SET ubicacion = 'PATIO', posicion = ?, nivel = ?, naviera_id = ?,
                           ingreso_en = COALESCE(ingreso_en, ?) WHERE codigo = ?""",
                        (pos, nivel, nav[n], db.ahora(), cont))
