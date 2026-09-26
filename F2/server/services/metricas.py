# -*- coding: utf-8 -*-
"""Las ocho métricas de operación (sección 13) para un rango [desde, hasta]."""
import csv
import io

from models import db
from services import citas


def _rango(desde, hasta):
    desde = db.texto_fecha(db.a_fecha(desde))
    h = db.a_fecha(hasta)
    if len(str(hasta).strip()) <= 10:  # solo fecha -> fin del día
        h = h.replace(hour=23, minute=59, second=59)
    return desde, db.texto_fecha(h)


def _div(a, b, dec=2):
    return round(a / b, dec) if b else 0.0


def calcular(desde, hasta):
    d, h = _rango(desde, hasta)
    remociones = db.valor("""SELECT COUNT(*) FROM ciclos_grua WHERE tipo = 'REMOCION' AND resultado = 'OK'
                             AND inicio_en BETWEEN ? AND ?""", (d, h)) or 0
    retiros = db.valor("""SELECT COUNT(*) FROM turnos WHERE tipo = 'RETIRO' AND estado = 'Cerrado'
                          AND cerrado_en BETWEEN ? AND ?""", (d, h)) or 0
    ciclos = db.valor("""SELECT COUNT(*) FROM ciclos_grua WHERE resultado = 'OK' AND tipo <> 'REFERENCIADO'
                         AND inicio_en BETWEEN ? AND ?""", (d, h)) or 0
    cerrados = db.valor("SELECT COUNT(*) FROM turnos WHERE estado = 'Cerrado' AND cerrado_en BETWEEN ? AND ?", (d, h)) or 0
    distancia = db.valor("SELECT COALESCE(SUM(distancia_mm), 0) FROM ciclos_grua WHERE inicio_en BETWEEN ? AND ?", (d, h))
    t_camion = db.valor("""SELECT AVG((julianday(cerrado_en) - julianday(creado_en)) * 1440) FROM turnos
                           WHERE estado = 'Cerrado' AND cerrado_en BETWEEN ? AND ?""", (d, h))
    t_retencion = db.valor("""SELECT AVG((julianday(resuelta_en) - julianday(creada_en)) * 1440) FROM retenciones
                              WHERE estado = 'RESUELTA' AND resuelta_en BETWEEN ? AND ?""", (d, h))
    fila_max = db.valor("SELECT MAX(cola_espera) FROM telemetria WHERE creado_en BETWEEN ? AND ?", (d, h)) or 0
    cump = citas.cumplimiento(d, h)
    por_causa = db.todos("""SELECT causa, COALESCE(resolucion, 'SIN_RESOLVER') AS resolucion, COUNT(*) AS cantidad
                            FROM retenciones WHERE creada_en BETWEEN ? AND ?
                            GROUP BY causa, resolucion ORDER BY causa, resolucion""", (d, h))
    return {
        "desde": d, "hasta": h,
        "remociones_por_contenedor_retirado": _div(remociones, retiros),
        "ciclos_grua_por_operacion_completada": _div(ciclos, cerrados),
        "distancia_total_grua_mm": int(distancia or 0),
        "tiempo_promedio_camion_min": round(t_camion or 0.0, 2),
        "tiempo_promedio_retencion_min": round(t_retencion or 0.0, 2),
        "longitud_maxima_fila_espera": int(fila_max),
        "porcentaje_citas_cumplidas_en_ventana": cump["porcentaje"],
        "retenciones_por_causa_y_resolucion": por_causa,
        "base": {"remociones": remociones, "retiros_completados": retiros, "ciclos_grua": ciclos,
                 "turnos_cerrados": cerrados, "citas_total": cump["total"],
                 "citas_en_ventana": cump["cumplidas_en_ventana"]},
    }


def generar_reporte(desde, hasta, etiqueta, usuario_id):
    m = calcular(desde, hasta)
    rid = db.insertar("reportes", {"etiqueta": etiqueta, "desde": m["desde"], "hasta": m["hasta"],
                                   "metricas_json": db.a_json(m), "generado_por": usuario_id, "generado_en": db.ahora()})
    return {"id": rid, "etiqueta": etiqueta, "metricas": m}


def exportar_csv(reporte_id):
    r = db.uno("SELECT * FROM reportes WHERE id = ?", (reporte_id,))
    if not r:
        return None
    m = db.de_json(r["metricas_json"])
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Reporte de corrida", r["etiqueta"] or ""])
    w.writerow(["Desde", m["desde"], "Hasta", m["hasta"], "Generado", r["generado_en"]])
    w.writerow([])
    w.writerow(["Metrica", "Valor"])
    for clave in ("remociones_por_contenedor_retirado", "ciclos_grua_por_operacion_completada",
                  "distancia_total_grua_mm", "tiempo_promedio_camion_min", "tiempo_promedio_retencion_min",
                  "longitud_maxima_fila_espera", "porcentaje_citas_cumplidas_en_ventana"):
        w.writerow([clave, m[clave]])
    w.writerow([])
    w.writerow(["Retenciones por causa y resolucion"])
    w.writerow(["Causa", "Resolucion", "Cantidad"])
    for f in m["retenciones_por_causa_y_resolucion"]:
        w.writerow([f["causa"], f["resolucion"], f["cantidad"]])
    w.writerow([])
    w.writerow(["Detalle de turnos del periodo"])
    w.writerow(["Turno", "Vehiculo", "Transportista", "Contenedor", "Tipo", "Estado", "Peso declarado g",
                "Peso entrada g", "Peso salida g", "Posicion", "Creado", "Cerrado", "Minutos en terminal"])
    for t in db.todos("""SELECT t.*, v.placa, tr.codigo AS transportista FROM turnos t
                         JOIN vehiculos v ON v.id = t.vehiculo_id JOIN transportistas tr ON tr.id = t.transportista_id
                         WHERE t.creado_en BETWEEN ? AND ? ORDER BY t.creado_en""", (m["desde"], m["hasta"])):
        minutos = ""
        if t["cerrado_en"]:
            minutos = round((db.a_fecha(t["cerrado_en"]) - db.a_fecha(t["creado_en"])).total_seconds() / 60, 2)
        w.writerow([t["codigo"], t["placa"], t["transportista"], t["contenedor"], t["tipo"], t["estado"],
                    t["peso_declarado_g"], t["peso_entrada_g"], t["peso_salida_g"],
                    f"P{t['posicion_asignada']}-{t['nivel_asignado']}" if t["posicion_asignada"] else "",
                    t["creado_en"], t["cerrado_en"] or "", minutos])
    return out.getvalue()
