# -*- coding: utf-8 -*-
"""
Matriz de permisos (sección 2.3). Se aplica en el SERVIDOR con el decorador
@requiere("ACCION"). Ocultar un botón no es control de permisos.

Valores:  S        = puede ejecutar la acción sobre cualquier registro
          PROPIOS  = solo sobre sus propios registros ("Solo los propios")
          None     = no puede (el servidor responde 403 con mensaje explícito)
"""
from functools import wraps

from flask import g

from models.constantes import ROLES
from models.errores import ErrorPermiso
from auth.sesion import usuario_actual

S = "S"
PROPIOS = "PROPIOS"
N = None

# Columnas en el orden del enunciado: TERMINAL, NAVIERA, AGENTE, AUTORIDAD, TRANSPORTISTA
MATRIZ = {
    # ----- Acciones literales de la matriz 2.3 -----
    "CREAR_MANIFIESTO":                (N, S, N, N, N),
    "VER_MANIFIESTO":                  (S, PROPIOS, S, S, N),
    "PRESENTAR_DECLARACION":           (N, N, S, N, N),   # "Presentar declaración y solicitar levante"
    "OTORGAR_RETENER_LEVANTE":         (N, N, N, S, N),
    "ASIGNAR_CANAL":                   (N, N, N, S, N),
    "SOLICITAR_CITA":                  (N, N, N, N, S),
    "VER_AGENDA_CITAS":                (S, N, N, N, N),
    "VER_SINOPTICO":                   (S, N, N, N, N),
    "EMITIR_COMANDOS":                 (S, N, N, N, N),
    "RECONOCER_ALARMAS":               (S, N, N, N, N),
    "RESOLVER_RETENCION_OPERATIVA":    (S, N, N, N, N),
    "RESOLVER_RETENCION_ADUANERA":     (N, N, N, S, N),
    "CORREGIR_PESO":                   (S, N, N, N, N),
    "CONSULTAR_CONTENEDOR":            (S, PROPIOS, S, S, PROPIOS),
    "GENERAR_REPORTE":                 (S, N, N, N, N),
    "GENERAR_CODIGO_VINCULACION":      (S, N, N, N, N),
    # ----- Acciones complementarias que se derivan de las pestañas del enunciado -----
    "ANULAR_MANIFIESTO":               (N, PROPIOS, N, N, N),  # 5.1 Botón Anular manifiesto
    "GESTIONAR_TURNOS":                (S, N, N, N, N),        # 4.2 Turnos: ver, retener, anular
    "VER_RETENCIONES":                 (S, N, N, S, N),        # AUTORIDAD solo ve las aduaneras (se filtra en la ruta)
    "ORDENAR_RETENCION_DOCUMENTAL":    (N, N, N, S, N),        # RT05 la ordena la autoridad
    "GESTIONAR_CITAS":                 (S, N, N, N, N),        # 4.7 cancelar, reprogramar, bloquear franja
    "VER_ALARMAS":                     (S, N, N, N, N),
    "VER_SEGUIMIENTO_AGENTE":          (N, N, S, N, N),        # 5.4
}

_INDICE = {rol: i for i, rol in enumerate(ROLES)}


def alcance(rol, accion):
    """Devuelve 'S', 'PROPIOS' o None."""
    fila = MATRIZ.get(accion)
    if fila is None or rol not in _INDICE:
        return None
    return fila[_INDICE[rol]]


def puede(rol, accion):
    return alcance(rol, accion) is not None


def verificar(accion, usuario=None):
    usuario = usuario or usuario_actual()
    valor = alcance(usuario["rol"], accion)
    if valor is None:
        raise ErrorPermiso(f"Acción no permitida: el rol {usuario['rol']} no puede ejecutar '{accion}'.")
    return valor


def requiere(accion):
    """Decorador de ruta. Deja en g.alcance el valor 'S' o 'PROPIOS'."""
    def decorador(f):
        @wraps(f)
        def envoltura(*args, **kwargs):
            g.alcance = verificar(accion)
            return f(*args, **kwargs)
        return envoltura
    return decorador


def matriz_para(rol):
    """Permisos efectivos de un rol (lo usa la interfaz para decidir qué mostrar)."""
    return {accion: alcance(rol, accion) for accion in MATRIZ if alcance(rol, accion)}
