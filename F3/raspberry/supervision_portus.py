#!/usr/bin/env python3
"""PORTUS Fase 2: consultas y métricas basadas exclusivamente en datos observados.
No realiza movimientos físicos. No infiere trabajo de grúa cuando no hay eventos.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from db_portus import conectar

TZ = ZoneInfo('America/Guatemala')
FINAL = ('Cerrado', 'Anulado')


def filas(conn, sql, args=()):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def _json(v):
    try:
        x = json.loads(v or '{}')
        return x if isinstance(x, dict) else {}
    except (ValueError, TypeError):
        return {}


def _tiempo(texto):
    if not texto:
        return None
    try:
        d = datetime.fromisoformat(str(texto).replace('Z', '+00:00'))
        return d.replace(tzinfo=TZ) if d.tzinfo is None else d.astimezone(TZ)
    except (TypeError, ValueError):
        return None


def estado_terminal():
    """Estado que puede verificarse con la base: nunca inventa posición de actuadores."""
    conn = conectar()
    try:
        counts = {}
        for tabla, condicion in (
            ('turnos', "estado NOT IN ('Cerrado','Anulado')"),
            ('retenciones', "estado='ACTIVA'"),
            ('alarmas', "estado='ACTIVA'"),
            ('citas', "estado='PROGRAMADA'"),
        ):
            counts[tabla] = conn.execute(f'SELECT count(*) FROM {tabla} WHERE {condicion}').fetchone()[0]
        hb = conn.execute('SELECT timestamp, estado_general, secuencia FROM telemetria ORDER BY id DESC LIMIT 1').fetchone()
        heartbeat = dict(hb) if hb else None
        ahora = datetime.now(TZ)
        ultimo = _tiempo(hb['timestamp']) if hb else None
        enlace = bool(ultimo and timedelta(seconds=0) <= ahora - ultimo <= timedelta(seconds=16))
        turno_rows = filas(conn, """
            SELECT t.id, t.estado, t.estacion, t.operacion, t.contenedor_id,
                   t.manifiesto_id, c.placa AS camion, t.updated_at
            FROM turnos t JOIN camiones c ON c.id=t.camion_id
            WHERE t.estado NOT IN ('Cerrado','Anulado')
            ORDER BY t.updated_at DESC LIMIT 20
        """)
        plazas = filas(conn, """
            SELECT p.numero, p.ocupada, p.turno_id, p.ocupada_desde,
                   c.placa AS camion, t.contenedor_id
            FROM plazas_retencion p LEFT JOIN turnos t ON t.id=p.turno_id
            LEFT JOIN camiones c ON c.id=t.camion_id ORDER BY p.numero
        """)
        recientes = filas(conn, """
            SELECT timestamp, topic, tipo, origen, datos_json FROM eventos
            ORDER BY recibido_at DESC, rowid DESC LIMIT 18
        """)
        for e in recientes:
            e['data'] = _json(e.pop('datos_json'))
        aguja = next((e for e in recientes if e['tipo'] == 'AGUJA'), None)
        return {
            'ahora': ahora.isoformat(timespec='seconds'),
            'enlace': 'CONECTADO' if enlace else 'DESCONECTADO',
            'heartbeat': heartbeat,
            'conteos': counts,
            'turnos': turno_rows,
            'plazas': plazas,
            'aguja_ultimo_evento': aguja,
            'eventos': recientes,
            'actuadores': 'SIN_TELEMETRIA_CONTINUA',
            'nota': 'Los sensores, luces, servos y grúa sin evento propio se muestran como no reportados.'
        }
    finally:
        conn.close()


def turnos(filtro='', q=''):
    conn = conectar()
    try:
        condiciones, args = [], []
        if filtro in ('Programado','EnGarita','EnPesajeEntrada','EnRuta','EnTransferencia',
                      'EnPesajeSalida','EnSalida','Retenido','Cerrado','Anulado'):
            condiciones.append('t.estado = ?'); args.append(filtro)
        if q:
            condiciones.append('(t.id LIKE ? OR t.contenedor_id LIKE ? OR c.placa LIKE ?)')
            args.extend([f'%{q}%'] * 3)
        where = 'WHERE ' + ' AND '.join(condiciones) if condiciones else ''
        return filas(conn, f"""
            SELECT t.*, c.placa AS camion, m.peso_declarado_g, d.canal,
                   n.nombre AS naviera
            FROM turnos t
            JOIN camiones c ON c.id=t.camion_id
            JOIN manifiestos m ON m.id=t.manifiesto_id
            LEFT JOIN declaraciones d ON d.manifiesto_id=m.id
            LEFT JOIN navieras n ON n.id=m.naviera_id
            {where} ORDER BY t.inicio DESC, t.id DESC LIMIT 250
        """, args)
    finally:
        conn.close()


def detalle_turno(turno_id):
    conn = conectar()
    try:
        ts = filas(conn, """
            SELECT t.*, c.placa AS camion, m.peso_declarado_g, m.tolerancia_pct,
                   d.canal FROM turnos t JOIN camiones c ON c.id=t.camion_id
            JOIN manifiestos m ON m.id=t.manifiesto_id
            LEFT JOIN declaraciones d ON d.manifiesto_id=m.id WHERE t.id = ?
        """, (turno_id,))
        if not ts:
            return None
        t = ts[0]
        pes = filas(conn, 'SELECT * FROM pesajes WHERE turno_id=? ORDER BY timestamp,id', (turno_id,))
        ret = filas(conn, 'SELECT * FROM retenciones WHERE turno_id=? ORDER BY inicio,id', (turno_id,))
        hist = []
        # Usamos el identificador del turno dentro de los eventos, no aproximaciones por placa.
        eventos = filas(conn, 'SELECT id,timestamp,origen,tipo,datos_json FROM eventos ORDER BY recibido_at DESC LIMIT 3500')
        for e in eventos:
            data = _json(e['datos_json'])
            if str(data.get('turno') or data.get('turno_id') or '') == turno_id:
                hist.append({'timestamp':e['timestamp'], 'origen':e['origen'],
                             'tipo':e['tipo'], 'datos':data})
        hist.sort(key=lambda e:e['timestamp'])
        return dict(turno=t, pesajes=pes, retenciones=ret, eventos=hist,
                    cronologia_parcial=True)
    finally:
        conn.close()


def alarmas(estado=''):
    conn = conectar()
    try:
        where = 'WHERE a.estado=?' if estado in ('ACTIVA','RECONOCIDA','CERRADA') else ''
        rows = filas(conn, f"""
            SELECT a.id,a.codigo,a.severidad,a.estado,a.timestamp,a.datos_json,
                   a.reconocida_at,u.nombre AS reconocida_por
            FROM alarmas a LEFT JOIN usuarios u ON u.id=a.reconocida_por
            {where} ORDER BY a.timestamp DESC,a.id DESC LIMIT 300
        """, (estado,) if where else ())
        for row in rows:
            row['datos'] = _json(row.pop('datos_json'))
        return rows
    finally:
        conn.close()


def reconocer_alarma(alarma_id, usuario_id):
    conn = conectar()
    try:
        conn.execute('BEGIN IMMEDIATE')
        changed = conn.execute("""
            UPDATE alarmas SET estado='RECONOCIDA', reconocida_por=?,
            reconocida_at=datetime('now') WHERE id=? AND estado='ACTIVA'
        """, (usuario_id, alarma_id)).rowcount
        conn.commit()
        return bool(changed)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def patio():
    conn = conectar()
    try:
        return filas(conn, """
          SELECT c.id, c.estado, c.ubicacion, c.nivel, c.permanencia_inicio,
                 i.confirmado_fisicamente, n.nombre AS naviera,
                 (SELECT m.peso_declarado_g FROM manifiestos m
                  WHERE m.contenedor_id=c.id AND m.anulado=0
                  ORDER BY m.created_at DESC LIMIT 1) AS peso_declarado_g,
                 (SELECT d.levante_estado FROM declaraciones d
                  JOIN manifiestos m ON m.id=d.manifiesto_id
                  WHERE m.contenedor_id=c.id ORDER BY d.id DESC LIMIT 1) AS levante
          FROM contenedores c LEFT JOIN inventario i ON i.contenedor_id=c.id
          LEFT JOIN navieras n ON n.id=c.naviera_id
          ORDER BY c.ubicacion,c.nivel,c.id
        """)
    finally:
        conn.close()


def grua():
    conn = conectar()
    try:
        rows = filas(conn, """
           SELECT timestamp, origen, tipo, datos_json FROM eventos
           WHERE topic='portus/evt/grua' ORDER BY recibido_at DESC LIMIT 80
        """)
        for e in rows:
            e['datos'] = _json(e.pop('datos_json'))
        return rows
    finally:
        conn.close()


def reportes(desde: str, hasta: str):
    """Calcula lo verificable, dejando N/D cuando faltan eventos del hardware."""
    inicio = f'{desde} 00:00:00'; fin = f'{hasta} 23:59:59'
    conn = conectar()
    try:
        cerrados = conn.execute("""
          SELECT COUNT(*) AS n,
          AVG((julianday(cierre)-julianday(inicio))*24*60) AS minutos
          FROM turnos WHERE estado='Cerrado' AND cierre BETWEEN ? AND ?
        """, (inicio, fin)).fetchone()
        ret = conn.execute("""
          SELECT COUNT(*) AS n,
          AVG((julianday(fin)-julianday(inicio))*24*60) AS minutos
          FROM retenciones WHERE estado='RESUELTA' AND fin BETWEEN ? AND ?
        """, (inicio, fin)).fetchone()
        citas = conn.execute("""
          SELECT COUNT(*) AS total,
          SUM(CASE WHEN estado='CUMPLIDA' AND dentro_ventana=1 THEN 1 ELSE 0 END) AS dentro
          FROM citas WHERE inicio BETWEEN ? AND ?
        """, (inicio, fin)).fetchone()
        resumen_ret = filas(conn, """
          SELECT causa, COALESCE(resolucion,'PENDIENTE') AS resolucion,
          COUNT(*) AS cantidad FROM retenciones
          WHERE inicio BETWEEN ? AND ? GROUP BY causa,resolucion
          ORDER BY causa,resolucion
        """, (inicio, fin))
        # No fingir sensores de fila ni datos de grúa. Solo usar eventos instrumentados.
        e_grua = filas(conn, """
          SELECT tipo,datos_json FROM eventos
          WHERE topic='portus/evt/grua' AND substr(timestamp,1,10) BETWEEN ? AND ?
        """, (desde,hasta))
        # La grúa aún no emite estos eventos estandarizados en el firmware base.
        grua_instrumentada = any(
           _json(e['datos_json']).get('accion') in ('CICLO_COMPLETO','REMOCION')
           for e in e_grua
        )
        indicadores = {
          'turnos_cerrados':cerrados['n'],
          'tiempo_promedio_terminal_min':round(cerrados['minutos'],2) if cerrados['minutos'] is not None else None,
          'retenciones_resueltas':ret['n'],
          'tiempo_promedio_retencion_min':round(ret['minutos'],2) if ret['minutos'] is not None else None,
          'porcentaje_citas_cumplidas_en_ventana':round(100*(citas['dentro'] or 0)/citas['total'],2) if citas['total'] else None,
          'citas_en_periodo':citas['total'],
          'remociones_por_retiro':None,
          'ciclos_grua_por_operacion':None,
          'distancia_grua_cm':None,
          'longitud_maxima_fila':None,
        }
        return {'desde':desde,'hasta':hasta,'indicadores':indicadores,
                'retenciones':resumen_ret, 'grua_instrumentada':grua_instrumentada,
                'nota':'N/D = no medido; requiere eventos instrumentados, no se inventan métricas.'}
    finally:
        conn.close()


def csv_reporte(r):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['PORTUS - Reporte Fase 2',r['desde'],r['hasta']])
    writer.writerow(['Metrica','Valor'])
    for k,v in r['indicadores'].items():
        writer.writerow([k, v if v is not None else 'N/D'])
    writer.writerow([])
    writer.writerow(['Retención por causa','Resolución','Cantidad'])
    for fila in r['retenciones']:
        writer.writerow([fila['causa'],fila['resolucion'],fila['cantidad']])
    return '\ufeff'+out.getvalue()
