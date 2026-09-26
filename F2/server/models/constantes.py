# -*- coding: utf-8 -*-
"""
PORTUS Fase 2 - Constantes compartidas por TODO el equipo.

Este archivo es la fuente única de nombres. Si el puente serial, el bot, las
interfaces o el simulador necesitan un nombre de estado, causa, alarma,
comando o tópico, deben importarlo de aquí (o copiar el valor EXACTO).
Los valores que el enunciado define de forma literal se respetan tal cual.
"""

# ---------------------------------------------------------------------------
# Roles (sección 2 del enunciado) - cinco roles y ningún otro
# ---------------------------------------------------------------------------
ROL_TERMINAL = "TERMINAL"
ROL_NAVIERA = "NAVIERA"
ROL_AGENTE = "AGENTE"
ROL_AUTORIDAD = "AUTORIDAD"
ROL_TRANSPORTISTA = "TRANSPORTISTA"

ROLES = (ROL_TERMINAL, ROL_NAVIERA, ROL_AGENTE, ROL_AUTORIDAD, ROL_TRANSPORTISTA)
ROLES_WEB = (ROL_TERMINAL, ROL_NAVIERA, ROL_AGENTE, ROL_AUTORIDAD)  # TRANSPORTISTA solo usa el bot

# Pestañas obligatorias por rol (nombre exacto y orden del enunciado, sección 3)
PESTANAS = {
    ROL_TERMINAL: ["Operación", "Turnos", "Retenciones", "Patio", "Grúa", "Alarmas", "Citas", "Reportes"],
    ROL_NAVIERA: ["Manifiestos", "Mis contenedores"],
    ROL_AGENTE: ["Declaraciones", "Seguimiento"],
    ROL_AUTORIDAD: ["Solicitudes de levante", "Retenciones aduaneras", "Consulta de carga"],
    ROL_TRANSPORTISTA: [],
}

# ---------------------------------------------------------------------------
# Estados del turno (sección 7) - EXACTAMENTE estos diez
# ---------------------------------------------------------------------------
T_PROGRAMADO = "Programado"
T_EN_GARITA = "EnGarita"
T_EN_PESAJE_ENTRADA = "EnPesajeEntrada"
T_EN_RUTA = "EnRuta"
T_EN_TRANSFERENCIA = "EnTransferencia"
T_EN_PESAJE_SALIDA = "EnPesajeSalida"
T_EN_SALIDA = "EnSalida"
T_RETENIDO = "Retenido"
T_CERRADO = "Cerrado"
T_ANULADO = "Anulado"

ESTADOS_TURNO = (T_PROGRAMADO, T_EN_GARITA, T_EN_PESAJE_ENTRADA, T_EN_RUTA, T_EN_TRANSFERENCIA,
                 T_EN_PESAJE_SALIDA, T_EN_SALIDA, T_RETENIDO, T_CERRADO, T_ANULADO)
ESTADOS_TURNO_FINALES = (T_CERRADO, T_ANULADO)

# Transiciones permitidas (columna "Transiciones posibles" de la sección 7)
TRANSICIONES_TURNO = {
    T_PROGRAMADO: (T_EN_GARITA, T_ANULADO),
    T_EN_GARITA: (T_EN_PESAJE_ENTRADA, T_RETENIDO, T_ANULADO),
    T_EN_PESAJE_ENTRADA: (T_EN_RUTA, T_RETENIDO, T_ANULADO),
    T_EN_RUTA: (T_EN_TRANSFERENCIA, T_ANULADO),
    T_EN_TRANSFERENCIA: (T_EN_PESAJE_SALIDA, T_EN_TRANSFERENCIA, T_ANULADO),
    T_EN_PESAJE_SALIDA: (T_EN_SALIDA, T_RETENIDO, T_ANULADO),
    T_EN_SALIDA: (T_CERRADO, T_RETENIDO),
    T_RETENIDO: (T_EN_RUTA, T_EN_SALIDA, T_ANULADO),
    T_CERRADO: (),
    T_ANULADO: (),
}

# Estados en los que el vehículo aún no llega a transferencia: si se retiene,
# se le asigna plaza y la aguja lo desvía físicamente al parqueo.
ESTADOS_ANTES_DE_TRANSFERENCIA = (T_EN_GARITA, T_EN_PESAJE_ENTRADA)

# Estaciones físicas (columna "Estación actual" de la pestaña Turnos)
ESTACIONES = ("ZONA_ESPERA", "GARITA", "PESAJE_ENTRADA", "AGUJA", "PARQUEO", "TRANSFERENCIA",
              "PESAJE_SALIDA", "SALIDA", "FUERA")

# ---------------------------------------------------------------------------
# Cadena documental (secciones 5.1 a 5.5)
# ---------------------------------------------------------------------------
TIPO_DEPOSITO = "DEPOSITO"
TIPO_RETIRO = "RETIRO"
TIPOS_OPERACION = (TIPO_DEPOSITO, TIPO_RETIRO)

DOC_PENDIENTE_DECLARACION = "PENDIENTE_DECLARACION"
DOC_DECLARACION_PRESENTADA = "DECLARACION_PRESENTADA"
DOC_LEVANTE_SOLICITADO = "LEVANTE_SOLICITADO"
DOC_LEVANTE_OTORGADO = "LEVANTE_OTORGADO"
DOC_LEVANTE_RETENIDO = "LEVANTE_RETENIDO"
DOC_ANULADO = "ANULADO"
ESTADOS_DOCUMENTALES = (DOC_PENDIENTE_DECLARACION, DOC_DECLARACION_PRESENTADA, DOC_LEVANTE_SOLICITADO,
                        DOC_LEVANTE_OTORGADO, DOC_LEVANTE_RETENIDO, DOC_ANULADO)

OP_SIN_CITA = "SIN_CITA"
OP_CITA_PROGRAMADA = "CITA_PROGRAMADA"
OP_EN_TERMINAL = "EN_TERMINAL"
OP_COMPLETADO = "COMPLETADO"
OP_ANULADO = "ANULADO"
ESTADOS_OPERATIVOS = (OP_SIN_CITA, OP_CITA_PROGRAMADA, OP_EN_TERMINAL, OP_COMPLETADO, OP_ANULADO)

CANAL_VERDE = "VERDE"
CANAL_ROJO = "ROJO"
CANALES = (CANAL_VERDE, CANAL_ROJO)

REGIMENES = ("IMPORTACION_DEFINITIVA", "DEPOSITO_TEMPORAL")

LEVANTE_PENDIENTE = "PENDIENTE"
LEVANTE_OTORGADO = "OTORGADO"
LEVANTE_RETENIDO = "RETENIDO"
ESTADOS_SOLICITUD_LEVANTE = (LEVANTE_PENDIENTE, LEVANTE_OTORGADO, LEVANTE_RETENIDO)

TOLERANCIA_DEFECTO_PCT = 5.0
DESCRIPCION_MERCANCIA_MIN = 10

# ---------------------------------------------------------------------------
# Retenciones (sección 8)
# ---------------------------------------------------------------------------
PLAZAS_PARQUEO = 3

CAUSAS_RETENCION = {
    "RT01": {"descripcion": "Discrepancia de peso al ingreso", "rol": ROL_TERMINAL, "aduanera": False},
    "RT02": {"descripcion": "Discrepancia de peso a la salida", "rol": ROL_TERMINAL, "aduanera": False},
    "RT03": {"descripcion": "Canal rojo de selectivo", "rol": ROL_AUTORIDAD, "aduanera": True},
    "RT04": {"descripcion": "Llegada fuera de la ventana asignada", "rol": ROL_TERMINAL, "aduanera": False},
    "RT05": {"descripcion": "Retención documental", "rol": ROL_AUTORIDAD, "aduanera": True},
    "RT06": {"descripcion": "Retención manual operativa", "rol": ROL_TERMINAL, "aduanera": False},
}
CAUSAS_DE_PESO = ("RT01", "RT02")

RES_ACLARAR = "ACLARAR"
RES_CORREGIR = "CORREGIR"
RES_RECHAZAR = "RECHAZAR"
RESOLUCIONES = (RES_ACLARAR, RES_CORREGIR, RES_RECHAZAR)

RETENCION_ABIERTA = "ABIERTA"
RETENCION_RESUELTA = "RESUELTA"

# ---------------------------------------------------------------------------
# Alarmas (sección 4.6)
# ---------------------------------------------------------------------------
SEV_CRITICA = "CRITICA"
SEV_ALTA = "ALTA"
SEV_MEDIA = "MEDIA"
SEV_BAJA = "BAJA"
SEVERIDADES = (SEV_CRITICA, SEV_ALTA, SEV_MEDIA, SEV_BAJA)
SEVERIDADES_RECONOCER_TODAS = (SEV_MEDIA, SEV_BAJA)

ALARMAS = {
    "AL01": ("Enlace con el controlador perdido", SEV_CRITICA),
    "AL02": ("Paro de emergencia accionado", SEV_CRITICA),
    "AL03": ("Pérdida de referencia de posición de la grúa", SEV_CRITICA),
    "AL04": ("Pérdida de carga durante el traslado", SEV_CRITICA),
    "AL05": ("Agarre de contenedor no confirmado", SEV_ALTA),
    "AL06": ("Trabajo de grúa abortado", SEV_ALTA),
    "AL07": ("Inconsistencia entre altura física e inventario", SEV_ALTA),
    "AL08": ("Movimiento del vehículo durante la transferencia", SEV_ALTA),
    "AL09": ("Pesaje fuera de tolerancia", SEV_MEDIA),
    "AL10": ("Vehículo incorrecto en la salida", SEV_MEDIA),
    "AL11": ("Parqueo de retención lleno", SEV_MEDIA),
    "AL12": ("Retención que supera treinta minutos", SEV_MEDIA),
    "AL13": ("Permanencia de contenedor superior a dos horas", SEV_BAJA),
    "AL14": ("Comando remoto rechazado por el controlador", SEV_BAJA),
}

# ---------------------------------------------------------------------------
# Comandos remotos (sección 11) - EXACTAMENTE estos trece
# ---------------------------------------------------------------------------
COMANDOS = (
    "AbrirTalanquera", "CerrarTalanquera", "AbrirPuertaSalida",
    "AgujaRecta", "AgujaParqueo", "AgujaLiberar",
    "GruaReferenciar", "GruaSuspender", "GruaReanudar",
    "PosicionBloquear", "PosicionLiberar",
    "ModoMantenimiento", "AlarmaSilenciar",
)
CMD_ENVIADO = "ENVIADO"
CMD_ACEPTADO = "ACEPTADO"
CMD_RECHAZADO = "RECHAZADO"

# ---------------------------------------------------------------------------
# Patio, grúa y sistema
# ---------------------------------------------------------------------------
POSICIONES_PATIO = 6          # igual a TOTAL_POSICIONES_PATIO del firmware (config.h)
NIVELES_PATIO = 2
PATIO_LIBRE = "LIBRE"
PATIO_RESERVADA = "RESERVADA"
PATIO_OCUPADA_N1 = "OCUPADA_N1"
PATIO_OCUPADA_N2 = "OCUPADA_N2"
PATIO_BLOQUEADA = "BLOQUEADA"

TRABAJO_DEPOSITO = "DEPOSITO"
TRABAJO_RETIRO = "RETIRO"
TRABAJO_REMOCION = "REMOCION"
TRABAJO_REFERENCIADO = "REFERENCIADO"
DESTINO_VEHICULO = "VEHICULO"   # origen/destino de un trabajo cuando es el camión

FALLAS_GRUA = ("PERDIDA_REFERENCIA", "AGARRE_NO_CONFIRMADO", "MOVIMIENTO_ABORTADO", "PERDIDA_CARGA")

POLITICA_FASE1 = "FASE1"       # política original: debe conservarse como línea base (sección 13)
POLITICAS_PATIO = (POLITICA_FASE1,)

MODO_NORMAL = "NORMAL"
MODO_MANTENIMIENTO = "MANTENIMIENTO"
MODO_DEGRADADO = "DEGRADADO"
ENLACE_CONECTADO = "CONECTADO"
ENLACE_DESCONECTADO = "DESCONECTADO"

LATIDO_PERIODO_S = 5
LATIDOS_PERDIDOS_PARA_ALARMA = 3
RETENCION_ALERTA_MIN = 30
PERMANENCIA_ALERTA_MIN = 120

# ---------------------------------------------------------------------------
# Citas (sección 9)
# ---------------------------------------------------------------------------
FRANJA_MINUTOS = 15
CAPACIDAD_FRANJA = 2
GRACIA_VENTANA_MIN = 5
RECORDATORIO_MIN = 60
FRANJAS_A_OFRECER = 6

CITA_PROGRAMADA = "PROGRAMADA"
CITA_CUMPLIDA = "CUMPLIDA"
CITA_VENCIDA = "VENCIDA"
CITA_CANCELADA = "CANCELADA"
ESTADOS_CITA = (CITA_PROGRAMADA, CITA_CUMPLIDA, CITA_VENCIDA, CITA_CANCELADA)

# ---------------------------------------------------------------------------
# Bot del transportista (sección 6)
# ---------------------------------------------------------------------------
NOMBRE_TERMINAL = "PORTUS - Terminal Puerto Quetzal"
CODIGO_VINCULACION_LARGO = 6
CODIGO_VINCULACION_EXPIRA_MIN = 60

NOTIF_LEVANTE_OTORGADO = "LEVANTE_OTORGADO"
NOTIF_LEVANTE_RETENIDO = "LEVANTE_RETENIDO"
NOTIF_CITA_ASIGNADA = "CITA_ASIGNADA"
NOTIF_CITA_RECORDATORIO = "CITA_RECORDATORIO"
NOTIF_VEHICULO_RETENIDO = "VEHICULO_RETENIDO"
NOTIF_RETENCION_RESUELTA = "RETENCION_RESUELTA"
NOTIF_CITA_MODIFICADA = "CITA_MODIFICADA"
NOTIF_TURNO_CERRADO = "TURNO_CERRADO"
NOTIF_TURNO_ANULADO = "TURNO_ANULADO"
NOTIFICACIONES = (NOTIF_LEVANTE_OTORGADO, NOTIF_LEVANTE_RETENIDO, NOTIF_CITA_ASIGNADA,
                  NOTIF_CITA_RECORDATORIO, NOTIF_VEHICULO_RETENIDO, NOTIF_RETENCION_RESUELTA,
                  NOTIF_CITA_MODIFICADA, NOTIF_TURNO_CERRADO, NOTIF_TURNO_ANULADO)

# ---------------------------------------------------------------------------
# Tópicos MQTT (sección 10.2). El prefijo "portus" es obligatorio.
# ---------------------------------------------------------------------------
TOPICO_EVT_GARITA = "portus/evt/garita"
TOPICO_EVT_PESAJE = "portus/evt/pesaje"
TOPICO_EVT_AGUJA = "portus/evt/aguja"
TOPICO_EVT_TRANSFERENCIA = "portus/evt/transferencia"
TOPICO_EVT_GRUA = "portus/evt/grua"
TOPICO_EVT_PATIO = "portus/evt/patio"
TOPICO_EVT_SALIDA = "portus/evt/salida"
TOPICO_EVT_ALARMA = "portus/evt/alarma"
TOPICO_EVT_ESTADO = "portus/evt/estado"
TOPICO_CMD_SOLICITUD = "portus/cmd/solicitud"
TOPICO_CMD_RESPUESTA = "portus/cmd/respuesta"

# Tópicos adicionales publicados por el SERVIDOR (extensión permitida, mismo formato):
TOPICO_SRV_DECISION = "portus/srv/decision"          # respuestas del servidor al controlador (garita, ruta, trabajos)
TOPICO_SRV_TURNO = "portus/srv/turno"                # cambios de estado de turno (para el sinóptico)
TOPICO_SRV_RETENCION = "portus/srv/retencion"        # retenciones creadas/resueltas
TOPICO_SRV_PARQUEO = "portus/srv/parqueo"            # plazas del parqueo
TOPICO_SRV_PATIO = "portus/srv/patio"                # inventario ya consolidado
TOPICO_SRV_ALARMA = "portus/srv/alarma"              # alarmas creadas/reconocidas
TOPICO_SRV_COMANDO = "portus/srv/comando"            # resultado de comandos (para mostrarlo al usuario)
TOPICO_SRV_SISTEMA = "portus/srv/sistema"            # enlace conectado/desconectado, modo
TOPICO_SRV_NOTIFICACION = "portus/srv/notificacion"  # aviso al bot de que hay notificación nueva

ORIGEN_CONTROLADOR = "controlador"
ORIGEN_SERVIDOR = "servidor"
ORIGEN_USUARIO = "usuario"
ORIGENES = (ORIGEN_CONTROLADOR, ORIGEN_SERVIDOR, ORIGEN_USUARIO)
