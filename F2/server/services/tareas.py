# -*- coding: utf-8 -*-
"""
Tareas periódicas del servidor (hilo en segundo plano):
  * Enlace perdido: sin latido durante 3 periodos -> AL01 y modo DEGRADADO.
  * AL12: retención abierta por más de 30 minutos.
  * AL13: contenedor en patio por más de 2 horas.
  * Citas vencidas y recordatorio una hora antes de la ventana.
"""
import logging
import threading
import time

from models import db
from models import constantes as C
from services import alarmas, citas, operacion

log = logging.getLogger("portus.tareas")


def revisar_tiempos():
    with db.transaccion():
        for r in db.todos(f"""SELECT id, codigo, turno_id FROM retenciones WHERE estado = 'ABIERTA'
                              AND (julianday('now','localtime') - julianday(creada_en)) * 1440 > {C.RETENCION_ALERTA_MIN}"""):
            alarmas.generar("AL12", clave=r["codigo"], turno_id=r["turno_id"], detalle=r["codigo"])
        for c in db.todos(f"""SELECT codigo FROM contenedores WHERE ubicacion = 'PATIO' AND ingreso_en IS NOT NULL
                              AND (julianday('now','localtime') - julianday(ingreso_en)) * 1440 > {C.PERMANENCIA_ALERTA_MIN}"""):
            alarmas.generar("AL13", clave=c["codigo"], detalle=c["codigo"])


def ejecutar_una_vez():
    operacion.verificar_enlace()
    revisar_tiempos()
    citas.vencer_citas()
    citas.enviar_recordatorios()


def iniciar(intervalo_s=2):
    def bucle():
        ciclo = 0
        while True:
            try:
                operacion.verificar_enlace()
                if ciclo % 15 == 0:   # cada ~30 s
                    revisar_tiempos()
                    citas.vencer_citas()
                    citas.enviar_recordatorios()
            except Exception:
                log.exception("Error en tareas periódicas")
            ciclo += 1
            time.sleep(intervalo_s)

    hilo = threading.Thread(target=bucle, name="portus-tareas", daemon=True)
    hilo.start()
    return hilo
