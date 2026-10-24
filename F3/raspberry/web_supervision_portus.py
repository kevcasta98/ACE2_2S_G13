#!/usr/bin/env python3
"""Extensión PORTUS Terminal: Operación, Turnos, Patio, Grúa, Alarmas y Reportes.
No envía órdenes a la grúa ni altera inventario por presunción.
"""
from __future__ import annotations

import json
import os
import queue
import uuid
from datetime import date, datetime

from flask import Response, jsonify, redirect, render_template, request, flash, url_for, stream_with_context
import paho.mqtt.client as mqtt

from fase3_web import resumen as resumen_f3
from supervision_portus import (estado_terminal, turnos, detalle_turno,
                                alarmas, reconocer_alarma, patio, grua,
                                reportes, csv_reporte)


def instalar(app, roles_required, usuario_actual, menu_para, enviar_comando_controlador):
    def ctx(template, **data):
        user=usuario_actual()
        return render_template(template, user=user, tabs=menu_para(user), **data)

    @app.get('/terminal/operacion')
    @roles_required('TERMINAL')
    def terminal_operacion():
        return ctx('terminal_operacion.html', estado=estado_terminal(), fase3=resumen_f3())

    @app.get('/api/terminal/estado')
    @roles_required('TERMINAL')
    def api_terminal_estado():
        return jsonify({'ok':True, **estado_terminal()})

    @app.get('/api/terminal/eventos-stream')
    @roles_required('TERMINAL')
    def api_terminal_eventos_stream():
        """SSE alimentado por suscripción MQTT real; solo señales, sin comandos."""
        def events():
            cola=queue.Queue(maxsize=30)
            cliente=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                client_id='portus-sse-'+uuid.uuid4().hex[:10])
            def on_connect(cli, ud, flags, code, props):
                if code == 0:
                    cli.subscribe('portus/evt/#', qos=0)
                    cli.subscribe('portus/cmd/respuesta', qos=0)
                    cli.subscribe('portus/vision/#', qos=0)
                    cli.subscribe('portus/estacion/#', qos=0)
            def on_message(cli, ud, msg):
                try:
                    data=json.loads(msg.payload.decode('utf-8'))
                    evt={'topic':msg.topic,'id':data.get('id'),
                         'type':data.get('type'),'timestamp':data.get('timestamp')}
                    try: cola.put_nowait(evt)
                    except queue.Full:
                        try: cola.get_nowait()
                        except queue.Empty: pass
                        try: cola.put_nowait(evt)
                        except queue.Full: pass
                except (UnicodeDecodeError, ValueError): pass
            cliente.on_connect=on_connect
            cliente.on_message=on_message
            try:
                cliente.connect(os.environ.get('PORTUS_MQTT_HOST','localhost'),
                                int(os.environ.get('PORTUS_MQTT_PORT','1883')),30)
                cliente.loop_start()
                yield ': conexion establecida\n\n'
                while True:
                    try:
                        dato=cola.get(timeout=12)
                        yield f"data: {json.dumps(dato, ensure_ascii=False)}\n\n"
                    except queue.Empty:
                        yield ': latido sse\n\n'
            except Exception as exc:
                yield f"event: error\ndata: {json.dumps({'error':str(exc)})}\n\n"
            finally:
                try: cliente.loop_stop(); cliente.disconnect()
                except Exception: pass
        resp=Response(stream_with_context(events()), mimetype='text/event-stream')
        resp.headers['Cache-Control']='no-cache, no-store'
        resp.headers['X-Accel-Buffering']='no'
        return resp

    @app.get('/terminal/turnos')
    @roles_required('TERMINAL')
    def terminal_turnos():
        estado=request.args.get('estado','').strip()
        q=request.args.get('q','').strip()[:80]
        return ctx('terminal_turnos.html', turnos=turnos(estado,q),
                   estado_filtro=estado, q=q)

    @app.get('/terminal/turnos/<turno_id>')
    @roles_required('TERMINAL')
    def terminal_turno_detalle(turno_id):
        d=detalle_turno(turno_id)
        if d is None:
            from flask import abort
            abort(404)
        return ctx('terminal_turno_detalle.html', detalle=d)

    @app.get('/terminal/alarmas')
    @roles_required('TERMINAL')
    def terminal_alarmas():
        estado=request.args.get('estado','')
        return ctx('terminal_alarmas.html', alarmas=alarmas(estado), filtro=estado)

    @app.post('/terminal/alarmas/<int:alarma_id>/reconocer')
    @roles_required('TERMINAL')
    def terminal_alarma_reconocer(alarma_id):
        try:
            ok=reconocer_alarma(alarma_id, usuario_actual()['id'])
            flash('Alarma reconocida; el reconocimiento no elimina su causa.' if ok
                  else 'No se reconoció la alarma: ya no estaba activa.',
                  'ok' if ok else 'error')
        except Exception as exc:
            flash('Error al reconocer alarma: '+str(exc), 'error')
        return redirect(url_for('terminal_alarmas'))

    @app.post('/terminal/control/abrir-puerta-salida')
    @roles_required('TERMINAL')
    def terminal_abrir_puerta_salida():
        aceptado, msg, payload=enviar_comando_controlador('AbrirPuertaSalida',{})
        flash(f"Controlador: {'ACK' if aceptado else 'NACK'} - {msg}",
              'ok' if aceptado else 'error')
        return redirect(url_for('terminal_operacion'))

    @app.get('/terminal/patio')
    @roles_required('TERMINAL')
    def terminal_patio():
        return ctx('terminal_patio.html', contenedores=patio())

    @app.get('/terminal/grua')
    @roles_required('TERMINAL')
    def terminal_grua():
        return ctx('terminal_grua.html', eventos=grua())

    @app.get('/terminal/reportes')
    @roles_required('TERMINAL')
    def terminal_reportes():
        desde=request.args.get('desde',date.today().replace(day=1).isoformat())
        hasta=request.args.get('hasta',date.today().isoformat())
        try:
            if date.fromisoformat(desde)>date.fromisoformat(hasta): raise ValueError()
            d=reportes(desde,hasta)
        except (TypeError,ValueError):
            flash('Rango de fechas inválido.','error')
            return redirect(url_for('terminal_reportes'))
        return ctx('terminal_reportes.html', reporte=d)

    @app.get('/terminal/reportes.csv')
    @roles_required('TERMINAL')
    def terminal_reportes_csv():
        desde=request.args.get('desde',date.today().replace(day=1).isoformat())
        hasta=request.args.get('hasta',date.today().isoformat())
        try:
            if date.fromisoformat(desde)>date.fromisoformat(hasta): raise ValueError()
            d=reportes(desde,hasta)
        except (TypeError,ValueError):
            return Response('Rango de fechas inválido',status=400)
        return Response(csv_reporte(d),mimetype='text/csv; charset=utf-8',
                        headers={'Content-Disposition':f'attachment; filename="PORTUS_{desde}_{hasta}.csv"'})

    @app.post('/terminal/control/cerrar-talanquera')
    @roles_required('TERMINAL')
    def terminal_cerrar_talanquera():
        # Único comando manual genérico del catálogo que admite el firmware vigente;
        # el Mega siempre valida físicamente el IR antes de aceptar.
        aceptado, msg, payload=enviar_comando_controlador('CerrarTalanquera',{})
        flash(f"Controlador: {'ACK' if aceptado else 'NACK'} - {msg}",
              'ok' if aceptado else 'error')
        return redirect(url_for('terminal_operacion'))

    return True
