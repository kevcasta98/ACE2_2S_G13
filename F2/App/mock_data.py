# -*- coding: utf-8 -*-
"""
PORTUS - Datos ficticios para la Fase 2 (Compañero 2).
"""

# ---------------------------------------------------------------------------
# USUARIOS
# ---------------------------------------------------------------------------
USUARIOS = {
    "operador1":  {"password": "1234", "rol": "TERMINAL",  "nombre": "Carlos Operador"},
    "naviera1":   {"password": "1234", "rol": "NAVIERA",   "nombre": "Naviera Pacífico S.A.", "entidad": "NAVIERA1"},
    "naviera2":   {"password": "1234", "rol": "NAVIERA",   "nombre": "Naviera Atlántico S.A.", "entidad": "NAVIERA2"},
    "agente1":    {"password": "1234", "rol": "AGENTE",    "nombre": "Lic. Ana Agente"},
    "autoridad1": {"password": "1234", "rol": "AUTORIDAD", "nombre": "SAT - Autoridad Aduanera"},
}

# ---------------------------------------------------------------------------
# TRANSPORTISTAS
# ---------------------------------------------------------------------------
TRANSPORTISTAS = [
    {"id": "TRANS-A", "nombre": "Transportes Quetzal"},
    {"id": "TRANS-B", "nombre": "Logística Maya"},
    {"id": "TRANS-C", "nombre": "Carga Rápida del Sur"},
]

# ---------------------------------------------------------------------------
# CÓDIGOS DE VINCULACIÓN (canal de mensajería)
# ---------------------------------------------------------------------------
CODIGOS_VINCULACION = []

# ---------------------------------------------------------------------------
# CONTENEDORES
# ---------------------------------------------------------------------------
CONTENEDORES = [
    {"id": "CONT-001", "naviera": "NAVIERA1", "peso_declarado": 18500, "posicion": "A1", "nivel": 1,
     "estado": "Ocupada", "autorizacion": "Vigente", "ingreso": "2026-09-24 08:15", "permanencia_h": 26, "remociones": 0},
    {"id": "CONT-002", "naviera": "NAVIERA1", "peso_declarado": 21200, "posicion": "A1", "nivel": 2,
     "estado": "Ocupada", "autorizacion": "Vigente", "ingreso": "2026-09-24 10:40", "permanencia_h": 24, "remociones": 1},
    {"id": "CONT-003", "naviera": "NAVIERA2", "peso_declarado": 15300, "posicion": "A2", "nivel": 1,
     "estado": "Ocupada", "autorizacion": "Vigente", "ingreso": "2026-09-23 14:05", "permanencia_h": 44, "remociones": 0},
    {"id": "CONT-004", "naviera": "NAVIERA2", "peso_declarado": 19800, "posicion": "A3", "nivel": 1,
     "estado": "Bloqueada", "autorizacion": "Retenida", "ingreso": "2026-09-25 06:30", "permanencia_h": 4, "remociones": 0},
]

# ---------------------------------------------------------------------------
# MANIFIESTOS
# ---------------------------------------------------------------------------
MANIFIESTOS = [
    {"id": "MAN-1001", "contenedor": "CONT-005", "naviera": "NAVIERA1", "tipo": "Deposito",
     "peso_declarado": 20000, "tolerancia": 5, "transportista": "TRANS-A", "observaciones": "",
     "estado": "Pendiente declaración", "canal": None},
    {"id": "MAN-1002", "contenedor": "CONT-006", "naviera": "NAVIERA1", "tipo": "Retiro",
     "peso_declarado": 17500, "tolerancia": 5, "transportista": "TRANS-B", "observaciones": "",
     "estado": "Declaración presentada", "canal": None},
    {"id": "MAN-1003", "contenedor": "CONT-002", "naviera": "NAVIERA1", "tipo": "Retiro",
     "peso_declarado": 21200, "tolerancia": 5, "transportista": "TRANS-A", "observaciones": "",
     "estado": "Levante solicitado", "canal": None},
    {"id": "MAN-1004", "contenedor": "CONT-003", "naviera": "NAVIERA2", "tipo": "Retiro",
     "peso_declarado": 15300, "tolerancia": 5, "transportista": "TRANS-C", "observaciones": "",
     "estado": "Levante otorgado", "canal": "Verde"},
]

# ---------------------------------------------------------------------------
# TURNOS
# ---------------------------------------------------------------------------
TURNOS = [
    {"id": "T-501", "vehiculo": "P-123ABC", "transportista": "TRANS-A", "contenedor": "CONT-001",
     "tipo": "Deposito", "estado": "Cerrado", "estacion": "-", "peso_declarado": 18500,
     "peso_ingreso": 24700, "peso_salida": 6200, "posicion_patio": "A1-1",
     "creado": "2026-09-24 08:15", "tiempo": "45 min"},
    {"id": "T-502", "vehiculo": "P-456DEF", "transportista": "TRANS-B", "contenedor": "CONT-003",
     "tipo": "Deposito", "estado": "Cerrado", "estacion": "-", "peso_declarado": 15300,
     "peso_ingreso": 21500, "peso_salida": 6200, "posicion_patio": "A2-1",
     "creado": "2026-09-23 14:05", "tiempo": "38 min"},
    {"id": "T-503", "vehiculo": "P-789GHI", "transportista": "TRANS-C", "contenedor": "CONT-004",
     "tipo": "Deposito", "estado": "Retenido", "estacion": "Parqueo retención", "peso_declarado": 19800,
     "peso_ingreso": 27100, "peso_salida": None, "posicion_patio": "Pendiente",
     "creado": "2026-09-25 06:30", "tiempo": "en curso"},
    {"id": "T-504", "vehiculo": "P-321JKL", "transportista": "TRANS-A", "contenedor": "CONT-002",
     "tipo": "Retiro", "estado": "EnTransferencia", "estacion": "Zona de transferencia", "peso_declarado": 21200,
     "peso_ingreso": 6200, "peso_salida": None, "posicion_patio": "A1-2",
     "creado": "2026-09-25 09:10", "tiempo": "en curso"},
]

# ---------------------------------------------------------------------------
# RETENCIONES
# ---------------------------------------------------------------------------
RETENCIONES = [
    {"id": "RET-01", "turno": "T-503", "vehiculo": "P-789GHI", "contenedor": "CONT-004",
     "causa": "RT01 - Discrepancia de peso al ingreso", "momento": "2026-09-25 06:35",
     "plaza": 1, "tiempo": "18 min", "peso_declarado": 19800, "peso_medido": 21400,
     "diferencia_pct": 8.1, "rol_facultado": "TERMINAL", "estado": "Abierta",
     "resolucion": None, "motivo": None, "observacion": None},
    {"id": "RET-02", "turno": "T-498", "vehiculo": "P-654MNO", "contenedor": "CONT-007",
     "causa": "RT03 - Canal rojo de selectivo", "momento": "2026-09-24 16:20",
     "plaza": 2, "tiempo": "resuelta", "peso_declarado": None, "peso_medido": None,
     "diferencia_pct": None, "rol_facultado": "AUTORIDAD", "estado": "Resuelta",
     "resolucion": "Aclarar", "motivo": None, "observacion": None},
    {"id": "RET-03", "turno": "T-499", "vehiculo": "P-111AAA", "contenedor": "CONT-008",
     "causa": "RT05 - Retención documental", "momento": "2026-09-25 10:00",
     "plaza": 3, "tiempo": "5 min", "peso_declarado": None, "peso_medido": None,
     "diferencia_pct": None, "rol_facultado": "AUTORIDAD", "estado": "Abierta",
     "resolucion": None, "motivo": None, "observacion": None},
    {"id": "RET-04", "turno": "T-500", "vehiculo": "P-222BBB", "contenedor": "CONT-009",
     "causa": "RT04 - Llegada fuera de la ventana asignada", "momento": "2026-09-25 11:00",
     "plaza": 2, "tiempo": "10 min", "peso_declarado": None, "peso_medido": None,
     "diferencia_pct": None, "rol_facultado": "TERMINAL", "estado": "Abierta",
     "resolucion": None, "motivo": None, "observacion": None},
]

# ---------------------------------------------------------------------------
# ALARMAS
# ---------------------------------------------------------------------------
ALARMAS = [
    {"id": "A-1", "codigo": "AL09", "descripcion": "Pesaje fuera de tolerancia", "severidad": "Media",
     "origen": "Controlador", "momento": "2026-09-25 06:35", "reconocida": False},
    {"id": "A-2", "codigo": "AL11", "descripcion": "Parqueo de retención lleno", "severidad": "Media",
     "origen": "Controlador", "momento": "2026-09-25 07:02", "reconocida": False},
    {"id": "A-3", "codigo": "AL13", "descripcion": "Permanencia de contenedor superior a dos horas",
     "severidad": "Baja", "origen": "Servidor", "momento": "2026-09-24 12:00", "reconocida": True},
]

# ---------------------------------------------------------------------------
# CITAS
# ---------------------------------------------------------------------------
CITAS = [
    {"franja": "08:00 - 08:15", "capacidad": 2, "citas": [
        {"transportista": "TRANS-A", "vehiculo": "P-123ABC", "contenedor": "CONT-001", "estado": "Cumplida"}]},
    {"franja": "08:15 - 08:30", "capacidad": 2, "citas": []},
    {"franja": "09:00 - 09:15", "capacidad": 2, "citas": [
        {"transportista": "TRANS-A", "vehiculo": "P-321JKL", "contenedor": "CONT-002", "estado": "Cumplida"},
        {"transportista": "TRANS-C", "vehiculo": "P-789GHI", "contenedor": "CONT-004", "estado": "Vencida"}]},
]

# ---------------------------------------------------------------------------
# MÉTRICAS
# ---------------------------------------------------------------------------
METRICAS_MOCK = {
    "remociones_por_retiro": 0.33,
    "ciclos_grua_por_operacion": 1.5,
    "distancia_total_grua_m": 142.5,
    "tiempo_promedio_camion_min": 41,
    "tiempo_promedio_retencion_min": 22,
    "longitud_maxima_fila": 3,
    "pct_citas_cumplidas": 78.5,
    "retenciones_por_causa": {"RT01": 3, "RT02": 0, "RT03": 1, "RT04": 2, "RT05": 0, "RT06": 1},
}

# ---------------------------------------------------------------------------
# GRÚA
# ---------------------------------------------------------------------------
GRUA = {
    "estado": "En reposo",
    "posicion": "A1",
    "trabajo_actual": None,
    "cola": [
        {"tipo": "Depósito", "turno": "T-503", "orden": 1},
        {"tipo": "Retiro", "turno": "T-504", "orden": 2},
    ],
    "ciclos_completados": 27,
    "tiempo_promedio_ciclo_s": 38,
    "fallas": [
        {"momento": "2026-09-24 11:12", "tipo": "Agarre no confirmado"},
    ],
}