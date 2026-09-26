# -*- coding: utf-8 -*-
"""
Arranque del backend de PORTUS Fase 2.

    cd F2/server
    python -m venv .venv && source .venv/bin/activate      (fish: source .venv/bin/activate.fish)
    pip install -r requirements.txt
    python run.py init-db --demo        # crea database/portus.db con usuarios de prueba
    python run.py                        # http://0.0.0.0:5000

Comandos:
    python run.py init-db [--demo] [--reset]
    python run.py crear-usuario USERNAME PASSWORD ROL [NAVIERA|TRANSPORTISTA]
    python run.py                        # levanta el servidor
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config  # noqa: E402


def init_db(argv):
    from models import db, semilla
    if "--reset" in argv and os.path.exists(Config.DB_PATH):
        for sufijo in ("", "-wal", "-shm"):
            if os.path.exists(Config.DB_PATH + sufijo):
                os.remove(Config.DB_PATH + sufijo)
        print("Base de datos eliminada.")
    os.makedirs(os.path.dirname(Config.DB_PATH), exist_ok=True)
    db.configurar(Config.DB_PATH)
    semilla.crear_esquema(Config.SCHEMA_PATH)
    semilla.cargar_base()
    if "--demo" in argv:
        semilla.cargar_demo()
        print(f"Datos de prueba cargados. Contraseña de todos los usuarios: {semilla.PASSWORD_PRUEBA}")
    print(f"Base lista en {Config.DB_PATH}")


def crear_usuario(argv):
    from auth.sesion import hash_password
    from models import db
    from models.constantes import ROLES
    if len(argv) < 3 or argv[2] not in ROLES:
        sys.exit(f"Uso: crear-usuario USERNAME PASSWORD ROL [NAVIERA|TRANSPORTISTA]. Roles: {ROLES}")
    username, password, rol = argv[:3]
    db.configurar(Config.DB_PATH)
    nav = tra = None
    if rol == "NAVIERA":
        nav = db.valor("SELECT id FROM navieras WHERE codigo = ?", (argv[3],))
    if rol == "TRANSPORTISTA":
        tra = db.valor("SELECT id FROM transportistas WHERE codigo = ?", (argv[3],))
    db.ejecutar("""INSERT INTO usuarios (username, password_hash, nombre, rol, naviera_id, transportista_id)
                   VALUES (?, ?, ?, ?, ?, ?)""", (username, hash_password(password), username, rol, nav, tra))
    print(f"Usuario {username} creado con rol {rol}.")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "init-db":
        init_db(args[1:])
    elif args and args[0] == "crear-usuario":
        crear_usuario(args[1:])
    else:
        from app import create_app
        create_app().run(host="0.0.0.0", port=int(os.environ.get("PORTUS_PORT", "5000")),
                         debug=False, threaded=True)
