#!/usr/bin/env python3
# ============================================================
# PORTUS - Base de datos SQLite
# Fase 2
# ============================================================

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "portus.db"

TURN_STATES = (
    "Programado",
    "EnGarita",
    "EnPesajeEntrada",
    "EnRuta",
    "EnTransferencia",
    "EnPesajeSalida",
    "EnSalida",
    "Retenido",
    "Cerrado",
    "Anulado",
)

ROLES = ("TERMINAL", "NAVIERA", "AGENTE", "AUTORIDAD", "TRANSPORTISTA")


def conectar(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


def inicializar_bd(db_path: Path = DB_PATH) -> None:
    conn = conectar(db_path)

    schema = r"""
    CREATE TABLE IF NOT EXISTS schema_info (
        version INTEGER NOT NULL,
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS navieras (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL UNIQUE,
        activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0,1)),
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS transportistas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL UNIQUE,
        activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0,1)),
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        nombre TEXT NOT NULL,
        rol TEXT NOT NULL CHECK (
            rol IN ('TERMINAL','NAVIERA','AGENTE','AUTORIDAD','TRANSPORTISTA')
        ),
        naviera_id INTEGER,
        transportista_id INTEGER,
        activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0,1)),
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (naviera_id) REFERENCES navieras(id),
        FOREIGN KEY (transportista_id) REFERENCES transportistas(id)
    );

    CREATE TABLE IF NOT EXISTS camiones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        placa TEXT NOT NULL UNIQUE,
        rfid_uid TEXT NOT NULL UNIQUE,
        transportista_id INTEGER,
        tara_g REAL,
        activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0,1)),
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (transportista_id) REFERENCES transportistas(id)
    );

    CREATE TABLE IF NOT EXISTS contenedores (
        id TEXT PRIMARY KEY,
        naviera_id INTEGER,
        estado TEXT NOT NULL DEFAULT 'DISPONIBLE',
        ubicacion TEXT,
        nivel INTEGER,
        permanencia_inicio TEXT,
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (naviera_id) REFERENCES navieras(id)
    );

    CREATE TABLE IF NOT EXISTS manifiestos (
        id TEXT PRIMARY KEY,
        naviera_id INTEGER NOT NULL,
        contenedor_id TEXT NOT NULL,
        operacion TEXT NOT NULL CHECK (operacion IN ('DEPOSITO','RETIRO')),
        peso_declarado_g INTEGER NOT NULL CHECK (peso_declarado_g > 0),
        tolerancia_pct REAL NOT NULL DEFAULT 5.0 CHECK (tolerancia_pct >= 0),
        transportista_id INTEGER NOT NULL,
        observaciones TEXT,
        estado_documental TEXT NOT NULL DEFAULT 'DECLARADO',
        estado_operativo TEXT NOT NULL DEFAULT 'PENDIENTE',
        anulado INTEGER NOT NULL DEFAULT 0 CHECK (anulado IN (0,1)),
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (naviera_id) REFERENCES navieras(id),
        FOREIGN KEY (contenedor_id) REFERENCES contenedores(id),
        FOREIGN KEY (transportista_id) REFERENCES transportistas(id)
    );

    CREATE UNIQUE INDEX IF NOT EXISTS ux_manifiesto_pendiente_contenedor
    ON manifiestos(contenedor_id)
    WHERE estado_operativo = 'PENDIENTE' AND anulado = 0;

    CREATE TABLE IF NOT EXISTS historial_manifiesto (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        manifiesto_id TEXT NOT NULL,
        campo TEXT NOT NULL,
        valor_anterior TEXT,
        valor_nuevo TEXT,
        motivo TEXT,
        usuario_id INTEGER,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (manifiesto_id) REFERENCES manifiestos(id),
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
    );

    CREATE TABLE IF NOT EXISTS declaraciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        numero TEXT NOT NULL UNIQUE,
        manifiesto_id TEXT NOT NULL UNIQUE,
        agente_usuario_id INTEGER,
        regimen TEXT NOT NULL CHECK (
            regimen IN ('IMPORTACION_DEFINITIVA','DEPOSITO_TEMPORAL')
        ),
        descripcion TEXT NOT NULL,
        valor_declarado REAL NOT NULL CHECK (valor_declarado > 0),
        estado TEXT NOT NULL DEFAULT 'PRESENTADA',
        levante_estado TEXT NOT NULL DEFAULT 'NO_SOLICITADO',
        canal TEXT CHECK (canal IN ('VERDE','ROJO') OR canal IS NULL),
        motivo_retencion TEXT,
        observacion TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (manifiesto_id) REFERENCES manifiestos(id),
        FOREIGN KEY (agente_usuario_id) REFERENCES usuarios(id)
    );

    CREATE TABLE IF NOT EXISTS notas_declaracion (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        declaracion_id INTEGER NOT NULL,
        usuario_id INTEGER NOT NULL,
        texto TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (declaracion_id) REFERENCES declaraciones(id),
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
    );

    CREATE TABLE IF NOT EXISTS citas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        manifiesto_id TEXT NOT NULL,
        contenedor_id TEXT NOT NULL,
        transportista_id INTEGER NOT NULL,
        camion_id INTEGER,
        inicio TEXT NOT NULL,
        fin TEXT NOT NULL,
        estado TEXT NOT NULL DEFAULT 'PROGRAMADA' CHECK (
            estado IN ('PROGRAMADA','CUMPLIDA','VENCIDA','CANCELADA')
        ),
        dentro_ventana INTEGER CHECK (dentro_ventana IN (0,1) OR dentro_ventana IS NULL),
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (manifiesto_id) REFERENCES manifiestos(id),
        FOREIGN KEY (contenedor_id) REFERENCES contenedores(id),
        FOREIGN KEY (transportista_id) REFERENCES transportistas(id),
        FOREIGN KEY (camion_id) REFERENCES camiones(id)
    );


    CREATE UNIQUE INDEX IF NOT EXISTS ux_cita_programada_contenedor
    ON citas(contenedor_id)
    WHERE estado = 'PROGRAMADA';

    CREATE INDEX IF NOT EXISTS ix_citas_inicio
    ON citas(inicio);

    CREATE TABLE IF NOT EXISTS franjas_citas (
        inicio TEXT PRIMARY KEY,
        fin TEXT NOT NULL,
        bloqueada INTEGER NOT NULL DEFAULT 0 CHECK (bloqueada IN (0,1)),
        motivo TEXT,
        bloqueada_por INTEGER,
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (bloqueada_por) REFERENCES usuarios(id)
    );

    CREATE TABLE IF NOT EXISTS historial_citas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cita_id INTEGER NOT NULL,
        accion TEXT NOT NULL,
        valor_anterior TEXT,
        valor_nuevo TEXT,
        usuario_id INTEGER,
        detalle TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (cita_id) REFERENCES citas(id),
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
    );

    CREATE TABLE IF NOT EXISTS mensajeria_vinculos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        canal TEXT NOT NULL,
        cuenta_id TEXT NOT NULL,
        transportista_id INTEGER NOT NULL,
        vinculada_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE (canal, cuenta_id),
        UNIQUE (canal, transportista_id),
        FOREIGN KEY (transportista_id) REFERENCES transportistas(id)
    );

    CREATE TABLE IF NOT EXISTS notificaciones_transportista (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transportista_id INTEGER NOT NULL,
        tipo TEXT NOT NULL,
        mensaje TEXT NOT NULL,
        estado TEXT NOT NULL DEFAULT 'PENDIENTE' CHECK (
            estado IN ('PENDIENTE','ENVIADA','ERROR')
        ),
        intentos INTEGER NOT NULL DEFAULT 0,
        ultimo_error TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        sent_at TEXT,
        FOREIGN KEY (transportista_id) REFERENCES transportistas(id)
    );

    CREATE TABLE IF NOT EXISTS turnos (
        id TEXT PRIMARY KEY,
        manifiesto_id TEXT NOT NULL,
        camion_id INTEGER NOT NULL,
        contenedor_id TEXT NOT NULL,
        operacion TEXT NOT NULL CHECK (operacion IN ('DEPOSITO','RETIRO')),
        estado TEXT NOT NULL CHECK (
            estado IN (
                'Programado','EnGarita','EnPesajeEntrada','EnRuta',
                'EnTransferencia','EnPesajeSalida','EnSalida',
                'Retenido','Cerrado','Anulado'
            )
        ),
        estado_previo_retencion TEXT,
        estacion TEXT,
        inicio TEXT NOT NULL DEFAULT (datetime('now')),
        cierre TEXT,
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (manifiesto_id) REFERENCES manifiestos(id),
        FOREIGN KEY (camion_id) REFERENCES camiones(id),
        FOREIGN KEY (contenedor_id) REFERENCES contenedores(id)
    );

    CREATE TABLE IF NOT EXISTS pesajes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        turno_id TEXT,
        tipo TEXT CHECK (tipo IN ('ENTRADA','SALIDA') OR tipo IS NULL),
        peso_medido_g REAL,
        peso_esperado_g REAL,
        diferencia_g REAL,
        muestras INTEGER,
        resultado TEXT,
        timestamp TEXT NOT NULL,
        datos_json TEXT NOT NULL,
        FOREIGN KEY (turno_id) REFERENCES turnos(id)
    );

    CREATE TABLE IF NOT EXISTS plazas_retencion (
        numero INTEGER PRIMARY KEY CHECK (numero BETWEEN 1 AND 3),
        turno_id TEXT UNIQUE,
        ocupada INTEGER NOT NULL DEFAULT 0 CHECK (ocupada IN (0,1)),
        ocupada_desde TEXT,
        FOREIGN KEY (turno_id) REFERENCES turnos(id)
    );

    CREATE TABLE IF NOT EXISTS retenciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        turno_id TEXT,
        causa TEXT NOT NULL CHECK (
            causa IN ('RT01','RT02','RT03','RT04','RT05','RT06')
        ),
        plaza INTEGER CHECK (plaza BETWEEN 1 AND 3 OR plaza IS NULL),
        estado TEXT NOT NULL DEFAULT 'ACTIVA' CHECK (
            estado IN ('ACTIVA','RESUELTA')
        ),
        resolucion TEXT CHECK (
            resolucion IN ('ACLARAR','CORREGIR','RECHAZAR') OR resolucion IS NULL
        ),
        rol_resolutor TEXT,
        motivo TEXT,
        peso_declarado_g REAL,
        peso_medido_g REAL,
        inicio TEXT NOT NULL DEFAULT (datetime('now')),
        fin TEXT,
        FOREIGN KEY (turno_id) REFERENCES turnos(id),
        FOREIGN KEY (plaza) REFERENCES plazas_retencion(numero)
    );

    CREATE TABLE IF NOT EXISTS inventario (
        contenedor_id TEXT PRIMARY KEY,
        ubicacion TEXT NOT NULL,
        nivel INTEGER,
        confirmado_fisicamente INTEGER NOT NULL DEFAULT 0 CHECK (
            confirmado_fisicamente IN (0,1)
        ),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (contenedor_id) REFERENCES contenedores(id)
    );

    CREATE TABLE IF NOT EXISTS alarmas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo TEXT NOT NULL,
        severidad TEXT,
        estado TEXT NOT NULL DEFAULT 'ACTIVA' CHECK (
            estado IN ('ACTIVA','RECONOCIDA','CERRADA')
        ),
        timestamp TEXT NOT NULL,
        datos_json TEXT NOT NULL,
        reconocida_por INTEGER,
        reconocida_at TEXT,
        FOREIGN KEY (reconocida_por) REFERENCES usuarios(id)
    );

    CREATE TABLE IF NOT EXISTS eventos (
        id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        topic TEXT NOT NULL,
        origen TEXT NOT NULL,
        tipo TEXT NOT NULL,
        secuencia INTEGER,
        datos_json TEXT NOT NULL,
        mensaje_json TEXT NOT NULL,
        recibido_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS ix_eventos_timestamp ON eventos(timestamp);
    CREATE INDEX IF NOT EXISTS ix_eventos_tipo ON eventos(tipo);
    CREATE INDEX IF NOT EXISTS ix_eventos_secuencia ON eventos(secuencia);

    CREATE TABLE IF NOT EXISTS telemetria (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        evento_id TEXT UNIQUE,
        timestamp TEXT NOT NULL,
        secuencia INTEGER,
        estado_general TEXT,
        datos_json TEXT NOT NULL,
        FOREIGN KEY (evento_id) REFERENCES eventos(id)
    );

    CREATE TABLE IF NOT EXISTS codigos_vinculacion (
        codigo TEXT PRIMARY KEY,
        transportista_id INTEGER NOT NULL,
        expira_at TEXT NOT NULL,
        usado INTEGER NOT NULL DEFAULT 0 CHECK (usado IN (0,1)),
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (transportista_id) REFERENCES transportistas(id)
    );
    """

    conn.executescript(schema)

    # Aplicación idempotente de eventos físicos en los servicios. Se conservan
    # las tablas anteriores y todos los datos operativos ya existentes.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eventos_aplicados (
            evento_id TEXT PRIMARY KEY,
            tipo TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # Migraciones incrementales seguras para instalaciones que ya vienen de v0.3.
    # SQLite no permite IF NOT EXISTS al agregar columnas, por eso se consulta
    # primero la estructura existente.
    columnas_retenciones = {
        fila["name"] for fila in conn.execute("PRAGMA table_info(retenciones)")
    }
    migraciones_retenciones = {
        "estacion_origen": "TEXT",
        "observacion_resolucion": "TEXT",
        "motivo_resolucion": "TEXT",
    }
    for columna, definicion in migraciones_retenciones.items():
        if columna not in columnas_retenciones:
            conn.execute(
                f"ALTER TABLE retenciones ADD COLUMN {columna} {definicion}"
            )


    columnas_citas = {
        fila["name"] for fila in conn.execute("PRAGMA table_info(citas)")
    }
    migraciones_citas = {
        "recordatorio_enviado": "INTEGER NOT NULL DEFAULT 0 CHECK (recordatorio_enviado IN (0,1))",
        "updated_at": "TEXT",
        "camion_id": "INTEGER",
    }
    for columna, definicion in migraciones_citas.items():
        if columna not in columnas_citas:
            conn.execute(
                f"ALTER TABLE citas ADD COLUMN {columna} {definicion}"
            )

    conn.execute(
        '''
        UPDATE citas
        SET updated_at = COALESCE(updated_at, created_at, datetime('now'))
        WHERE updated_at IS NULL
        '''
    )

    for numero in (1, 2, 3):
        conn.execute(
            """
            INSERT OR IGNORE INTO plazas_retencion(numero, ocupada)
            VALUES (?, 0)
            """,
            (numero,),
        )

    actual = conn.execute("SELECT version FROM schema_info ORDER BY rowid DESC LIMIT 1").fetchone()
    if actual is None:
        conn.execute("INSERT INTO schema_info(version) VALUES (3)")
    elif actual["version"] < 3:
        conn.execute(
            "UPDATE schema_info SET version = 3, updated_at = datetime('now')"
        )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    inicializar_bd()
    print(f"Base PORTUS inicializada: {DB_PATH}")
