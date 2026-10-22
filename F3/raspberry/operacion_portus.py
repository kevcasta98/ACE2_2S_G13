#!/usr/bin/env python3
"""PORTUS - Estados de operación a partir de eventos físicos del Mega.

Solo se usa TRANSFERENCIA (INICIO/FIN manual) y SALIDA (COMPLETA por IR).
NO modifica inventario, NO decide movimientos de grúa, NO duplica pesajes.
"""
from __future__ import annotations
import json
import os
import paho.mqtt.client as mqtt
from db_portus import conectar, inicializar_bd
from citas_portus import encolar_notificacion

TOPICS = ('portus/evt/transferencia','portus/evt/salida')


def procesar(payload: dict, topic: str) -> None:
    data=payload.get('data') or {}
    if not isinstance(data,dict): return
    turno_id=str(data.get('turno') or data.get('turno_id') or '').upper()
    accion=str(data.get('accion') or '').upper()
    event_id=str(payload.get('id') or '')
    if not turno_id or not event_id: return
    conn=conectar()
    try:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute('SELECT 1 FROM eventos_aplicados WHERE evento_id=?',(event_id,)).fetchone():
            conn.rollback();return
        t=conn.execute('''
           SELECT t.id,t.estado,t.manifiesto_id,t.contenedor_id,t.operacion,t.inicio,
                  c.placa AS camion,m.transportista_id
           FROM turnos t JOIN camiones c ON c.id=t.camion_id
           JOIN manifiestos m ON m.id=t.manifiesto_id WHERE t.id=?
        ''',(turno_id,)).fetchone()
        if not t:
            conn.rollback();print(f'[OPERACION] Turno no registrado: {turno_id}');return
        if topic.endswith('/transferencia'):
            cambios={'INICIO':('EnRuta','EnTransferencia','TRANSFERENCIA'),
                     'FIN':('EnTransferencia','EnPesajeSalida','PESAJE_SALIDA')}
            regla=cambios.get(accion)
            if regla is None:
                conn.rollback();return
            previo,nuevo,estacion=regla
            if t['estado']!=previo:
                conn.rollback()
                print(f"[OPERACION] {turno_id} {accion}: estado={t['estado']}, esperaba={previo}")
                return
            conn.execute("UPDATE turnos SET estado=?,estacion=?,updated_at=datetime('now') WHERE id=?",
                         (nuevo,estacion,turno_id))
        elif topic.endswith('/salida'):
            if accion!='COMPLETA':
                # AUTORIZADA no significa que el vehículo haya salido;
                # TIEMPO_AGOTADO tampoco cierra un turno.
                conn.rollback();return
            if t['estado']=='Anulado':
                # El turno rechazado debe permanecer Anulado, no se convierte a Cerrado.
                print(f'[OPERACION] {turno_id} salida física confirmada; permanece Anulado')
            elif t['estado']=='EnSalida':
                conn.execute('''UPDATE turnos SET estado='Cerrado',estacion='FUERA',
                              cierre=datetime('now'),updated_at=datetime('now') WHERE id=?''',(turno_id,))
                conn.execute('''UPDATE manifiestos SET estado_operativo='FINALIZADO',
                              updated_at=datetime('now') WHERE id=?''',(t['manifiesto_id'],))
                if t['transportista_id']:
                    encolar_notificacion(conn,t['transportista_id'],'TURNO_CERRADO',
                      f"Vehículo {t['camion']}, contenedor {t['contenedor_id']}, operación {t['operacion']}: turno {turno_id} cerrado tras salida física confirmada.")
            else:
                conn.rollback()
                print(f"[OPERACION] Salida {turno_id} ignorada: estado previo {t['estado']}")
                return
        else:
            conn.rollback();return
        conn.execute('INSERT INTO eventos_aplicados(evento_id,tipo) VALUES (?,?)',
                     (event_id, 'OPERACION'))
        conn.commit()
        print(f'[OPERACION] {turno_id} | {accion} | {t["estado"]} -> confirmado')
    except Exception as exc:
        conn.rollback()
        print(f'[OPERACION ERROR] {turno_id} {exc}')
    finally:
        conn.close()


def on_connect(client, userdata, flags, code, props):
    if code == 0:
        for topic in TOPICS:
            client.subscribe(topic, qos=1)
            print('[MQTT] Escuchando', topic)
    else: print('[MQTT] Conexión fallida:',code)


def on_message(client,userdata,msg):
    try:
        procesar(json.loads(msg.payload.decode('utf-8')),msg.topic)
    except (UnicodeDecodeError, ValueError) as exc:
        print('[OPERACION] evento descartado:',exc)


def main():
    inicializar_bd()
    print('PORTUS - estados de transferencia y salida confirmados')
    cli=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id='portus-operacion')
    cli.on_connect=on_connect;cli.on_message=on_message
    cli.connect(os.environ.get('PORTUS_MQTT_HOST','localhost'),
                int(os.environ.get('PORTUS_MQTT_PORT','1883')),60)
    try:cli.loop_forever()
    except KeyboardInterrupt:pass
    finally:cli.disconnect()

if __name__=='__main__':main()
