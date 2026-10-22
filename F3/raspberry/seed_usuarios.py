#!/usr/bin/env python3
# ============================================================
# PORTUS - Usuarios minimos de prueba
# Las contraseñas se almacenan con hash, nunca en texto plano.
# ============================================================

from werkzeug.security import generate_password_hash

from db_portus import conectar, inicializar_bd

USUARIOS = [
    {
        "username": "terminal",
        "password": "Terminal2026!",
        "nombre": "Operador Terminal",
        "rol": "TERMINAL",
        "entidad": None,
    },
    {
        "username": "naviera1",
        "password": "Naviera12026!",
        "nombre": "Usuario Naviera Atlántico",
        "rol": "NAVIERA",
        "entidad": "Naviera Atlántico",
    },
    {
        "username": "naviera2",
        "password": "Naviera22026!",
        "nombre": "Usuario Naviera Pacífico",
        "rol": "NAVIERA",
        "entidad": "Naviera Pacífico",
    },
    {
        "username": "agente",
        "password": "Agente2026!",
        "nombre": "Agente Aduanero",
        "rol": "AGENTE",
        "entidad": None,
    },
    {
        "username": "autoridad",
        "password": "Autoridad2026!",
        "nombre": "Autoridad Aduanera",
        "rol": "AUTORIDAD",
        "entidad": None,
    },
    {
        "username": "transportista1",
        "password": "Transporte12026!",
        "nombre": "Transportista Quetzal",
        "rol": "TRANSPORTISTA",
        "entidad": "Transportes Quetzal",
    },
    {
        "username": "transportista2",
        "password": "Transporte22026!",
        "nombre": "Transportista Maya",
        "rol": "TRANSPORTISTA",
        "entidad": "Logística Maya",
    },
]


def id_naviera(conn, nombre):
    fila = conn.execute(
        "SELECT id FROM navieras WHERE nombre = ?",
        (nombre,),
    ).fetchone()
    return fila["id"] if fila else None


def id_transportista(conn, nombre):
    fila = conn.execute(
        "SELECT id FROM transportistas WHERE nombre = ?",
        (nombre,),
    ).fetchone()
    return fila["id"] if fila else None


def main():
    inicializar_bd()
    conn = conectar()

    for nombre in ("Naviera Atlántico", "Naviera Pacífico"):
        conn.execute(
            "INSERT OR IGNORE INTO navieras(nombre) VALUES (?)",
            (nombre,),
        )

    for nombre in ("Transportes Quetzal", "Logística Maya"):
        conn.execute(
            "INSERT OR IGNORE INTO transportistas(nombre) VALUES (?)",
            (nombre,),
        )

    conn.commit()

    for u in USUARIOS:
        naviera_id = None
        transportista_id = None

        if u["rol"] == "NAVIERA":
            naviera_id = id_naviera(conn, u["entidad"])

        if u["rol"] == "TRANSPORTISTA":
            transportista_id = id_transportista(conn, u["entidad"])

        existente = conn.execute(
            "SELECT id FROM usuarios WHERE username = ?",
            (u["username"],),
        ).fetchone()

        password_hash = generate_password_hash(u["password"])

        if existente:
            conn.execute(
                """
                UPDATE usuarios
                SET password_hash = ?,
                    nombre = ?,
                    rol = ?,
                    naviera_id = ?,
                    transportista_id = ?,
                    activo = 1
                WHERE username = ?
                """,
                (
                    password_hash,
                    u["nombre"],
                    u["rol"],
                    naviera_id,
                    transportista_id,
                    u["username"],
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO usuarios(
                    username, password_hash, nombre, rol,
                    naviera_id, transportista_id
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    u["username"],
                    password_hash,
                    u["nombre"],
                    u["rol"],
                    naviera_id,
                    transportista_id,
                ),
            )

    conn.commit()
    conn.close()

    print("Usuarios PORTUS creados/actualizados:\n")
    for u in USUARIOS:
        interfaz = (
            "mensajería"
            if u["rol"] == "TRANSPORTISTA"
            else "web"
        )
        print(
            f"{u['username']:<16} "
            f"{u['rol']:<15} "
            f"{u['password']:<20} "
            f"({interfaz})"
        )

    print(
        "\nEstas credenciales son únicamente para la demostración "
        "académica. Las contraseñas se almacenan con hash."
    )


if __name__ == "__main__":
    main()
