-- =============================================================================
-- PORTUS Fase 2 - Esquema de base de datos (SQLite)
-- Autor: Compañero 1 (backend + base de datos + usuarios)
--
-- Convenciones:
--   * Fechas en texto local 'YYYY-MM-DD HH:MM:SS' (precisión de segundo, 4.2.1).
--   * Pesos SIEMPRE en gramos enteros (el manifiesto declara gramos, 5.1).
--   * Los valores de estado/causa/rol son los de server/models/constantes.py.
--   * Los "codigo" legibles (MAN-0001, T-0001, RET-0001...) se generan a partir del id.
-- =============================================================================
PRAGMA foreign_keys = ON;

-- -----------------------------------------------------------------------------
-- Actores
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS navieras (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo  TEXT NOT NULL UNIQUE,            -- NAVIERA1, NAVIERA2
    nombre  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transportistas (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo       TEXT NOT NULL UNIQUE,       -- TRANS-A, TRANS-B
    nombre       TEXT NOT NULL,
    telefono     TEXT,
    chat_id      TEXT UNIQUE,                -- cuenta de mensajería vinculada (NULL = no vinculado)
    vinculado_en TEXT
);

CREATE TABLE IF NOT EXISTS usuarios (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    username         TEXT NOT NULL UNIQUE,
    password_hash    TEXT NOT NULL,          -- nunca texto plano (2.2.2)
    nombre           TEXT NOT NULL,
    rol              TEXT NOT NULL CHECK (rol IN ('TERMINAL','NAVIERA','AGENTE','AUTORIDAD','TRANSPORTISTA')),
    naviera_id       INTEGER REFERENCES navieras(id),
    transportista_id INTEGER REFERENCES transportistas(id),
    activo           INTEGER NOT NULL DEFAULT 1,
    creado_en        TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    ultimo_acceso    TEXT,
    CHECK (rol <> 'NAVIERA' OR naviera_id IS NOT NULL),
    CHECK (rol <> 'TRANSPORTISTA' OR transportista_id IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS codigos_vinculacion (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo           TEXT NOT NULL UNIQUE CHECK (length(codigo) = 6),
    transportista_id INTEGER NOT NULL REFERENCES transportistas(id),
    generado_por     INTEGER NOT NULL REFERENCES usuarios(id),
    creado_en        TEXT NOT NULL,
    expira_en        TEXT NOT NULL,          -- creado_en + 60 min (6.1.4)
    usado_en         TEXT,                   -- un solo uso
    usado_por_chat   TEXT
);

CREATE TABLE IF NOT EXISTS vehiculos (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    rfid_uid         TEXT NOT NULL UNIQUE,   -- UID en HEX mayúsculas, igual que garita.cpp (ej. EA225305)
    placa            TEXT NOT NULL UNIQUE,   -- C-101, C-202, C-303 (firmware Fase 1)
    transportista_id INTEGER NOT NULL REFERENCES transportistas(id),
    tara_g           INTEGER NOT NULL DEFAULT 0,
    activo           INTEGER NOT NULL DEFAULT 1
);

-- -----------------------------------------------------------------------------
-- Contenedores y patio
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS contenedores (
    codigo      TEXT PRIMARY KEY,            -- catálogo de contenedores de la maqueta (CONT-001...)
    naviera_id  INTEGER REFERENCES navieras(id),
    descripcion TEXT,
    ubicacion   TEXT NOT NULL DEFAULT 'FUERA' CHECK (ubicacion IN ('FUERA','VEHICULO','PATIO','GRUA')),
    posicion    INTEGER,                     -- 1..6 cuando ubicacion = PATIO
    nivel       INTEGER CHECK (nivel IS NULL OR nivel IN (1,2)),
    ingreso_en  TEXT,                        -- ingreso a la terminal (reloj de permanencia)
    remociones  INTEGER NOT NULL DEFAULT 0   -- veces movido por remociones
);

CREATE TABLE IF NOT EXISTS posiciones_patio (
    numero             INTEGER PRIMARY KEY,  -- 1..POSICIONES_PATIO
    contenedor_n1      TEXT REFERENCES contenedores(codigo),
    contenedor_n2      TEXT REFERENCES contenedores(codigo),
    bloqueada          INTEGER NOT NULL DEFAULT 0,
    motivo_bloqueo     TEXT,
    reservada_turno_id INTEGER REFERENCES turnos(id),
    actualizado_en     TEXT
);

-- Estado de cada posición tal como lo pide el sinóptico (4.1)
CREATE VIEW IF NOT EXISTS v_patio AS
SELECT p.*,
       CASE
         WHEN p.bloqueada = 1              THEN 'BLOQUEADA'
         WHEN p.contenedor_n2 IS NOT NULL  THEN 'OCUPADA_N2'
         WHEN p.contenedor_n1 IS NOT NULL  THEN 'OCUPADA_N1'
         WHEN p.reservada_turno_id IS NOT NULL THEN 'RESERVADA'
         ELSE 'LIBRE'
       END AS estado
FROM posiciones_patio p;

-- -----------------------------------------------------------------------------
-- Cadena documental
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS manifiestos (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo            TEXT UNIQUE,           -- MAN-0001
    contenedor        TEXT NOT NULL REFERENCES contenedores(codigo),
    naviera_id        INTEGER NOT NULL REFERENCES navieras(id),
    tipo              TEXT NOT NULL CHECK (tipo IN ('DEPOSITO','RETIRO')),
    peso_declarado_g  INTEGER NOT NULL CHECK (peso_declarado_g > 0),
    tolerancia_pct    REAL NOT NULL DEFAULT 5.0 CHECK (tolerancia_pct >= 0),
    transportista_id  INTEGER NOT NULL REFERENCES transportistas(id),
    observaciones     TEXT,
    estado_documental TEXT NOT NULL DEFAULT 'PENDIENTE_DECLARACION'
                      CHECK (estado_documental IN ('PENDIENTE_DECLARACION','DECLARACION_PRESENTADA',
                             'LEVANTE_SOLICITADO','LEVANTE_OTORGADO','LEVANTE_RETENIDO','ANULADO')),
    canal             TEXT CHECK (canal IS NULL OR canal IN ('VERDE','ROJO')),
    motivo_retencion  TEXT,                  -- motivo cuando la autoridad retiene el levante
    estado_operativo  TEXT NOT NULL DEFAULT 'SIN_CITA'
                      CHECK (estado_operativo IN ('SIN_CITA','CITA_PROGRAMADA','EN_TERMINAL','COMPLETADO','ANULADO')),
    creado_por        INTEGER REFERENCES usuarios(id),
    creado_en         TEXT NOT NULL,
    actualizado_en    TEXT NOT NULL
);
-- Regla 5.1: un contenedor no puede tener dos manifiestos pendientes al mismo tiempo
CREATE UNIQUE INDEX IF NOT EXISTS ux_manifiesto_pendiente_contenedor ON manifiestos(contenedor)
    WHERE estado_documental <> 'ANULADO' AND estado_operativo NOT IN ('COMPLETADO','ANULADO');

-- Historial del manifiesto (Corregir conserva el valor anterior, 4.3 / 8.3)
CREATE TABLE IF NOT EXISTS manifiesto_historial (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    manifiesto_id  INTEGER NOT NULL REFERENCES manifiestos(id),
    accion         TEXT NOT NULL,            -- CREADO, CORREGIR_PESO, ANULADO, DECLARACION, LEVANTE...
    campo          TEXT,
    valor_anterior TEXT,
    valor_nuevo    TEXT,
    usuario_id     INTEGER REFERENCES usuarios(id),
    comentario     TEXT,
    creado_en      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS declaraciones (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    manifiesto_id       INTEGER NOT NULL UNIQUE REFERENCES manifiestos(id),
    numero_declaracion  TEXT NOT NULL UNIQUE,
    regimen             TEXT NOT NULL CHECK (regimen IN ('IMPORTACION_DEFINITIVA','DEPOSITO_TEMPORAL')),
    descripcion         TEXT NOT NULL CHECK (length(descripcion) >= 10),
    valor_declarado     REAL NOT NULL CHECK (valor_declarado > 0),
    agente_id           INTEGER NOT NULL REFERENCES usuarios(id),
    presentada_en       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS solicitudes_levante (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    manifiesto_id INTEGER NOT NULL REFERENCES manifiestos(id),
    agente_id     INTEGER NOT NULL REFERENCES usuarios(id),
    estado        TEXT NOT NULL DEFAULT 'PENDIENTE' CHECK (estado IN ('PENDIENTE','OTORGADO','RETENIDO')),
    canal         TEXT CHECK (canal IS NULL OR canal IN ('VERDE','ROJO')),
    motivo        TEXT,                      -- causa de retención
    resuelto_por  INTEGER REFERENCES usuarios(id),
    solicitado_en TEXT NOT NULL,
    resuelto_en   TEXT
);

CREATE TABLE IF NOT EXISTS observaciones_documentales (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    manifiesto_id INTEGER NOT NULL REFERENCES manifiestos(id),
    usuario_id    INTEGER NOT NULL REFERENCES usuarios(id),
    texto         TEXT NOT NULL,
    creado_en     TEXT NOT NULL
);

-- -----------------------------------------------------------------------------
-- Citas (franjas de 15 minutos, capacidad 2)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS franjas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha       TEXT NOT NULL,               -- YYYY-MM-DD
    hora_inicio TEXT NOT NULL,               -- HH:MM
    hora_fin    TEXT NOT NULL,
    inicio      TEXT NOT NULL,               -- YYYY-MM-DD HH:MM:SS
    fin         TEXT NOT NULL,
    capacidad   INTEGER NOT NULL DEFAULT 2,
    bloqueada   INTEGER NOT NULL DEFAULT 0,
    UNIQUE (fecha, hora_inicio)
);

CREATE TABLE IF NOT EXISTS citas (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo               TEXT UNIQUE,        -- CITA-0001
    manifiesto_id        INTEGER NOT NULL REFERENCES manifiestos(id),
    contenedor           TEXT NOT NULL REFERENCES contenedores(codigo),
    transportista_id     INTEGER NOT NULL REFERENCES transportistas(id),
    franja_id            INTEGER NOT NULL REFERENCES franjas(id),
    estado               TEXT NOT NULL DEFAULT 'PROGRAMADA'
                         CHECK (estado IN ('PROGRAMADA','CUMPLIDA','VENCIDA','CANCELADA')),
    llegada_en           TEXT,
    dentro_ventana       INTEGER,            -- 1/0 al presentarse (alimenta la métrica)
    recordatorio_enviado INTEGER NOT NULL DEFAULT 0,
    motivo_cancelacion   TEXT,
    creado_en            TEXT NOT NULL,
    actualizado_en       TEXT NOT NULL
);
-- Regla 9.4: un contenedor no puede tener dos citas vigentes
CREATE UNIQUE INDEX IF NOT EXISTS ux_cita_vigente_contenedor ON citas(contenedor) WHERE estado = 'PROGRAMADA';

-- -----------------------------------------------------------------------------
-- Operación física
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS turnos (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo             TEXT UNIQUE,          -- T-0001
    manifiesto_id      INTEGER NOT NULL REFERENCES manifiestos(id),
    cita_id            INTEGER REFERENCES citas(id),
    vehiculo_id        INTEGER NOT NULL REFERENCES vehiculos(id),
    transportista_id   INTEGER NOT NULL REFERENCES transportistas(id),
    contenedor         TEXT NOT NULL REFERENCES contenedores(codigo),
    tipo               TEXT NOT NULL CHECK (tipo IN ('DEPOSITO','RETIRO')),
    estado             TEXT NOT NULL CHECK (estado IN ('Programado','EnGarita','EnPesajeEntrada','EnRuta',
                              'EnTransferencia','EnPesajeSalida','EnSalida','Retenido','Cerrado','Anulado')),
    estado_previo      TEXT,                 -- estado antes de Retenido (para volver al resolver)
    estacion           TEXT,
    peso_declarado_g   INTEGER NOT NULL,
    tolerancia_pct     REAL NOT NULL,
    peso_entrada_g     INTEGER,              -- bruto medido al ingreso
    peso_salida_g      INTEGER,              -- bruto medido a la salida
    posicion_asignada  INTEGER,
    nivel_asignado     INTEGER,
    motivo_anulacion   TEXT,
    creado_en          TEXT NOT NULL,        -- = momento en que la garita autoriza (7.1)
    cerrado_en         TEXT,                 -- Cerrado o Anulado
    actualizado_en     TEXT NOT NULL
);
-- Un vehículo no puede tener dos turnos activos
CREATE UNIQUE INDEX IF NOT EXISTS ux_turno_activo_vehiculo ON turnos(vehiculo_id)
    WHERE estado NOT IN ('Cerrado','Anulado');
CREATE INDEX IF NOT EXISTS ix_turnos_estado ON turnos(estado);

-- Intentos de ingreso rechazados (7.1: no crean turno pero sí registro)
CREATE TABLE IF NOT EXISTS intentos_ingreso (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    rfid_uid         TEXT,
    vehiculo_id      INTEGER REFERENCES vehiculos(id),
    transportista_id INTEGER REFERENCES transportistas(id),
    manifiesto_id    INTEGER REFERENCES manifiestos(id),
    causa            TEXT NOT NULL,
    creado_en        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pesajes (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    turno_id          INTEGER NOT NULL REFERENCES turnos(id),
    etapa             TEXT NOT NULL CHECK (etapa IN ('ENTRADA','SALIDA')),
    peso_bruto_g      INTEGER NOT NULL,
    tara_g            INTEGER NOT NULL,
    peso_neto_g       INTEGER NOT NULL,      -- bruto - tara = carga medida
    esperado_g        INTEGER NOT NULL,      -- carga que debería llevar
    diferencia_g      INTEGER NOT NULL,
    diferencia_pct    REAL NOT NULL,
    muestras          INTEGER,               -- muestras de la meseta
    dentro_tolerancia INTEGER NOT NULL,
    creado_en         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plazas_parqueo (
    numero               INTEGER PRIMARY KEY CHECK (numero BETWEEN 1 AND 3),
    turno_id             INTEGER UNIQUE REFERENCES turnos(id),
    retencion_id         INTEGER REFERENCES retenciones(id),
    ocupada_desde        TEXT,
    liberacion_pendiente INTEGER NOT NULL DEFAULT 0  -- 1 = retención resuelta, esperando que el controlador acepte AgujaLiberar
);

CREATE TABLE IF NOT EXISTS retenciones (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo             TEXT UNIQUE,          -- RET-0001 (consecutivo único)
    turno_id           INTEGER NOT NULL REFERENCES turnos(id),
    causa              TEXT NOT NULL CHECK (causa IN ('RT01','RT02','RT03','RT04','RT05','RT06')),
    rol_facultado      TEXT NOT NULL CHECK (rol_facultado IN ('TERMINAL','AUTORIDAD')),
    estacion           TEXT,
    estado_turno_previo TEXT,
    plaza              INTEGER,
    estado             TEXT NOT NULL DEFAULT 'ABIERTA' CHECK (estado IN ('ABIERTA','RESUELTA')),
    peso_declarado_g   INTEGER,              -- evidencia de peso (solo RT01/RT02)
    peso_medido_g      INTEGER,              -- carga neta medida
    diferencia_g       INTEGER,
    diferencia_pct     REAL,
    observacion_origen TEXT,
    creada_por         INTEGER REFERENCES usuarios(id),
    creada_en          TEXT NOT NULL,
    resolucion         TEXT CHECK (resolucion IS NULL OR resolucion IN ('ACLARAR','CORREGIR','RECHAZAR')),
    motivo             TEXT,                 -- obligatorio en RECHAZAR
    observacion        TEXT,                 -- opcional en ACLARAR/CORREGIR
    resuelta_por       INTEGER REFERENCES usuarios(id),
    resuelta_en        TEXT,
    CHECK (resolucion <> 'RECHAZAR' OR (motivo IS NOT NULL AND length(trim(motivo)) > 0))
);
CREATE INDEX IF NOT EXISTS ix_retenciones_estado ON retenciones(estado);

-- -----------------------------------------------------------------------------
-- Grúa
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trabajos_grua (
    id            TEXT PRIMARY KEY,          -- J-0001 (lo genera el servidor y lo usa el controlador)
    turno_id      INTEGER REFERENCES turnos(id),
    orden         INTEGER NOT NULL DEFAULT 1,
    tipo          TEXT NOT NULL CHECK (tipo IN ('DEPOSITO','RETIRO','REMOCION')),
    contenedor    TEXT,
    origen_pos    INTEGER,                   -- NULL = vehículo
    origen_nivel  INTEGER,
    destino_pos   INTEGER,                   -- NULL = vehículo
    destino_nivel INTEGER,
    estado        TEXT NOT NULL DEFAULT 'ENVIADO' CHECK (estado IN ('ENVIADO','EN_CURSO','COMPLETADO','ABORTADO')),
    creado_en     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ciclos_grua (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    trabajo_id   TEXT,
    turno_id     INTEGER REFERENCES turnos(id),
    tipo         TEXT NOT NULL CHECK (tipo IN ('DEPOSITO','RETIRO','REMOCION','REFERENCIADO')),
    contenedor   TEXT,
    origen       TEXT,
    destino      TEXT,
    inicio_en    TEXT NOT NULL,
    fin_en       TEXT,
    duracion_ms  INTEGER,
    distancia_mm INTEGER,                    -- distancia de traslación del ciclo (métrica 3)
    resultado    TEXT CHECK (resultado IS NULL OR resultado IN ('OK','ABORTADO','FALLA'))
);

CREATE TABLE IF NOT EXISTS fallas_grua (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo       TEXT NOT NULL CHECK (tipo IN ('PERDIDA_REFERENCIA','AGARRE_NO_CONFIRMADO','MOVIMIENTO_ABORTADO','PERDIDA_CARGA')),
    trabajo_id TEXT,
    turno_id   INTEGER REFERENCES turnos(id),
    detalle    TEXT,
    creado_en  TEXT NOT NULL
);

-- -----------------------------------------------------------------------------
-- Alarmas, comandos, eventos, telemetría
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alarmas_catalogo (
    codigo      TEXT PRIMARY KEY,            -- AL01..AL14
    descripcion TEXT NOT NULL,
    severidad   TEXT NOT NULL CHECK (severidad IN ('CRITICA','ALTA','MEDIA','BAJA'))
);

CREATE TABLE IF NOT EXISTS alarmas (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo           TEXT NOT NULL REFERENCES alarmas_catalogo(codigo),
    severidad        TEXT NOT NULL,
    origen           TEXT NOT NULL,          -- controlador / servidor / usuario
    descripcion      TEXT NOT NULL,
    clave            TEXT,                   -- evita duplicar la misma alarma activa (ej. id de retención)
    datos_json       TEXT,
    turno_id         INTEGER REFERENCES turnos(id),
    condicion_activa INTEGER NOT NULL DEFAULT 1,  -- 0 cuando la condición cesa (la alarma NO desaparece sola)
    creada_en        TEXT NOT NULL,
    reconocida       INTEGER NOT NULL DEFAULT 0,
    reconocida_por   INTEGER REFERENCES usuarios(id),
    reconocida_en    TEXT,
    comentario       TEXT
);
CREATE INDEX IF NOT EXISTS ix_alarmas_activas ON alarmas(reconocida, codigo);

CREATE TABLE IF NOT EXISTS comandos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    mensaje_id     TEXT NOT NULL UNIQUE,     -- id del mensaje MQTT; el controlador lo devuelve en la respuesta
    comando        TEXT NOT NULL CHECK (comando IN ('AbrirTalanquera','CerrarTalanquera','AbrirPuertaSalida',
                          'AgujaRecta','AgujaParqueo','AgujaLiberar','GruaReferenciar','GruaSuspender',
                          'GruaReanudar','PosicionBloquear','PosicionLiberar','ModoMantenimiento','AlarmaSilenciar')),
    parametros_json TEXT,
    usuario_id     INTEGER REFERENCES usuarios(id),   -- NULL = lo emitió el servidor automáticamente
    estado         TEXT NOT NULL DEFAULT 'ENVIADO' CHECK (estado IN ('ENVIADO','ACEPTADO','RECHAZADO')),
    causa_rechazo  TEXT,
    enviado_en     TEXT NOT NULL,
    respondido_en  TEXT
);

-- Todos los eventos (línea de tiempo del turno, 4.2.1)
CREATE TABLE IF NOT EXISTS eventos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    mensaje_id  TEXT UNIQUE,                 -- id del mensaje MQTT (evita duplicados al reconciliar)
    turno_id    INTEGER REFERENCES turnos(id),
    origen      TEXT NOT NULL CHECK (origen IN ('controlador','servidor','usuario')),
    tipo        TEXT NOT NULL,
    descripcion TEXT NOT NULL,
    datos_json  TEXT,
    usuario_id  INTEGER REFERENCES usuarios(id),
    topico      TEXT,
    seq         INTEGER,                     -- número de secuencia del controlador
    creado_en   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_eventos_turno ON eventos(turno_id, creado_en);

CREATE TABLE IF NOT EXISTS telemetria (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    seq         INTEGER,
    modo        TEXT,
    cola_espera INTEGER,                     -- vehículos en espera (métrica "longitud máxima de fila")
    datos_json  TEXT,
    creado_en   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_telemetria_fecha ON telemetria(creado_en);

-- Clave/valor: enlace, modo, último latido, política de patio, último seq...
CREATE TABLE IF NOT EXISTS estado_sistema (
    clave          TEXT PRIMARY KEY,
    valor          TEXT,
    actualizado_en TEXT
);

-- -----------------------------------------------------------------------------
-- Bot y reportes
-- -----------------------------------------------------------------------------
-- Bandeja de salida de notificaciones: el servidor escribe, el bot envía y marca.
CREATE TABLE IF NOT EXISTS notificaciones (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    transportista_id INTEGER NOT NULL REFERENCES transportistas(id),
    tipo             TEXT NOT NULL CHECK (tipo IN ('LEVANTE_OTORGADO','LEVANTE_RETENIDO','CITA_ASIGNADA',
                            'CITA_RECORDATORIO','VEHICULO_RETENIDO','RETENCION_RESUELTA','CITA_MODIFICADA',
                            'TURNO_CERRADO','TURNO_ANULADO')),
    mensaje          TEXT NOT NULL,          -- texto listo para enviar
    datos_json       TEXT,
    estado           TEXT NOT NULL DEFAULT 'PENDIENTE' CHECK (estado IN ('PENDIENTE','ENVIADA','ERROR')),
    intentos         INTEGER NOT NULL DEFAULT 0,
    error            TEXT,
    creado_en        TEXT NOT NULL,
    enviado_en       TEXT
);
CREATE INDEX IF NOT EXISTS ix_notificaciones_estado ON notificaciones(estado);

CREATE TABLE IF NOT EXISTS reportes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    etiqueta      TEXT,
    desde         TEXT NOT NULL,
    hasta         TEXT NOT NULL,
    metricas_json TEXT NOT NULL,
    generado_por  INTEGER REFERENCES usuarios(id),
    generado_en   TEXT NOT NULL
);
