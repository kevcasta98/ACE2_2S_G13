#!/usr/bin/env python3
"""PORTUS F3 vistas TERMINAL Accesos/iluminación/parámetros y AUTORIDAD restringidas.
RBAC en backend, auditoría e historial no eliminable desde la web.
"""
import re, os, json, time
from datetime import date
from pathlib import Path
from flask import (abort,flash,redirect,render_template,request,url_for,send_from_directory,jsonify)
import paho.mqtt.client as mqtt
from db_portus import conectar
from fase3_db import (migrar, momento, placa_norm, placa_valida, DEFAULTS, parametro,
                      estado, fijar_estado, auditar)
from fase3_mqtt import publicar, evento
ROOT=Path(__file__).resolve().parent

def resumen():
 c=conectar()
 try:
  r={x['clave']:{'valor':x['valor'],'actualizado':x['actualizado']} for x in c.execute('SELECT * FROM fase3_estado')}
  r['parametros']={x['clave']:x['valor'] for x in c.execute('SELECT * FROM fase3_parametros')}
  return r
 finally:c.close()

def enviar_mqtt(comando,params=None,topico='portus/cmd/solicitud'):
 cli=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id='web-f3-'+os.urandom(5).hex())
 try:
  cli.connect(os.environ.get('PORTUS_MQTT_HOST','localhost'),int(os.environ.get('PORTUS_MQTT_PORT','1883')),30)
  cli.loop_start()
  info=publicar(cli,comando,params,topico)
  time.sleep(0.35) # Permite al cliente efímero enviar el QoS1 antes de cerrar.
  cli.loop_stop();return info
 finally:cli.disconnect()

def instalar(app,roles_required,usuario_actual,menu_para):
 def ctx(plantilla,**k):
  u=usuario_actual();return render_template(plantilla,user=u,tabs=menu_para(u),**k)

 @app.get('/terminal/accesos')
 @roles_required('TERMINAL')
 def terminal_accesos():
  c=conectar()
  try:
   filas=[dict(x) for x in c.execute('''SELECT * FROM fase3_accesos ORDER BY id DESC LIMIT 120''')]
   camiones=[dict(x) for x in c.execute('''SELECT c.*,t.nombre AS transportista FROM camiones c
       LEFT JOIN transportistas t ON t.id=c.transportista_id ORDER BY c.id''')]
   transportistas=[dict(x) for x in c.execute('SELECT id,nombre FROM transportistas ORDER BY nombre')]
  finally:c.close()
  return ctx('fase3_accesos.html',accesos=filas,camiones=camiones,transportistas=transportistas)

 @app.get('/fase3/foto/<int:acceso_id>')
 @roles_required('TERMINAL','AUTORIDAD')
 def fase3_foto(acceso_id):
  c=conectar()
  try:r=c.execute('SELECT foto FROM fase3_accesos WHERE id=?',(acceso_id,)).fetchone()
  finally:c.close()
  if not r or not r['foto']:abort(404)
  # El cliente no puede elegir ruta de disco; solo el nombre guardado.
  nombre=Path(r['foto']).name
  if nombre!=r['foto'] or not nombre.endswith('.jpg'):abort(404)
  return send_from_directory(str(ROOT/'evidencias'/'garita'),nombre,as_attachment=False)

 @app.post('/terminal/accesos/<int:acceso_id>/resolver')
 @roles_required('TERMINAL')
 def fase3_resolver_acceso(acceso_id):
  decision=request.form.get('decision','').upper()
  motivo=request.form.get('motivo','').strip()
  if decision not in ('CONFIRMAR','RECHAZAR') or len(motivo)<10:
   flash('Decisión y motivo de al menos 10 caracteres obligatorios.','error');return redirect(url_for('terminal_accesos'))
  c=conectar()
  try:
   c.execute('BEGIN IMMEDIATE')
   r=c.execute('SELECT * FROM fase3_accesos WHERE id=?',(acceso_id,)).fetchone()
   if not r or r['resultado']!='MANUAL' or r['usuario_decision'] is not None:
    c.rollback();flash('Este intento no está pendiente.','error');return redirect(url_for('terminal_accesos'))
   from datetime import datetime
   from zoneinfo import ZoneInfo
   instante=datetime.fromisoformat(r['timestamp'])
   if (datetime.now(ZoneInfo('America/Guatemala'))-instante).total_seconds()>110:
    c.rollback();flash('Intento vencido: vuelva a presentar el RFID.','error');return redirect(url_for('terminal_accesos'))
   res='APROBADA_MANUAL' if decision=='CONFIRMAR' else 'RECHAZADA_MANUAL'
   c.execute('''UPDATE fase3_accesos SET resultado=?,usuario_decision=?,motivo_decision=?,resuelto=? WHERE id=?''',
             (res,usuario_actual()['id'],motivo,momento(),acceso_id))
   auditar(c,'VERIFICACION_MANUAL',usuario_actual()['id'],anterior='MANUAL',nuevo=res,motivo=motivo)
   c.commit()
  finally:c.close()
  cli=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id='decision-'+os.urandom(4).hex())
  try:
   cli.connect(os.environ.get('PORTUS_MQTT_HOST','localhost'),int(os.environ.get('PORTUS_MQTT_PORT','1883')),30)
   cli.loop_start()
   evento(cli,'portus/acceso/decision','DECISION',{'acceso_id':acceso_id,'resultado':res})
   time.sleep(0.35)
   cli.loop_stop()
  except Exception as exc:
   flash('La decisión se guardó, pero no llegó por MQTT: '+str(exc),'error')
  finally:cli.disconnect()
  flash('Decisión guardada. La garita debe recibir confirmación física del Mega.','ok')
  return redirect(url_for('terminal_accesos'))

 @app.post('/terminal/accesos/camiones/nuevo')
 @roles_required('TERMINAL')
 def fase3_crear_camion():
  codigo=request.form.get('codigo','').strip().upper()
  placa=placa_norm(request.form.get('placa_vision'))
  uid=re.sub('[^0-9A-F]','',request.form.get('rfid_uid','').upper())
  motivo=request.form.get('motivo','').strip()
  try:
   tara=float(request.form.get('tara_g','0'))
   transportista=int(request.form.get('transportista_id','0'))
  except ValueError:tara=0;transportista=0
  if not re.fullmatch(r'CAM-[0-9]{1,3}',codigo) or not placa_valida(placa) or len(uid)!=8 or tara<=0 or len(motivo)<10:
   flash('Código CAM-XX, placa C123ABC, RFID válido, tara positiva y motivo de 10 caracteres obligatorios.','error')
   return redirect(url_for('terminal_accesos'))
  c=conectar()
  try:
   c.execute('BEGIN IMMEDIATE')
   if not c.execute('SELECT 1 FROM transportistas WHERE id=?',(transportista,)).fetchone():
    raise ValueError('El transportista no existe')
   c.execute('INSERT INTO camiones(placa,rfid_uid,transportista_id,tara_g,activo,placa_vision) VALUES (?,?,?,?,1,?)',
             (codigo,uid,transportista,tara,placa))
   auditar(c,'ALTA_VEHICULO',usuario_actual()['id'],nuevo={'codigo':codigo,'uid':uid,'placa':placa,'transportista':transportista},motivo=motivo)
   c.commit();flash('Camión creado y auditado.','ok')
  except Exception as exc:
   c.rollback();flash('No se creó el vehículo: '+str(exc),'error')
  finally:c.close()
  return redirect(url_for('terminal_accesos'))

 @app.post('/terminal/accesos/camiones/<int:camion_id>')
 @roles_required('TERMINAL')
 def fase3_actualizar_camion(camion_id):
  placa=placa_norm(request.form.get('placa_vision'))
  uid=re.sub('[^0-9A-F]','',request.form.get('rfid_uid','').upper())
  motivo=request.form.get('motivo','').strip()
  activo=1 if request.form.get('activo')=='1' else 0
  if not placa_valida(placa) or len(uid)!=8 or len(motivo)<10:
   flash('Placa C123ABC, UID de 8 hexadecimales y motivo de 10 caracteres requeridos.','error')
   return redirect(url_for('terminal_accesos'))
  c=conectar()
  try:
   c.execute('BEGIN IMMEDIATE')
   previo=c.execute('SELECT * FROM camiones WHERE id=?',(camion_id,)).fetchone()
   if not previo:abort(404)
   # No cambiar identificación física de un camión con turno activo.
   if (uid!=re.sub('[^0-9A-F]','',previo['rfid_uid'].upper()) or placa!=placa_norm(previo['placa_vision'])) and c.execute("SELECT 1 FROM turnos WHERE camion_id=? AND estado NOT IN ('Cerrado','Anulado')",(camion_id,)).fetchone():
    c.rollback();flash('No puede cambiar RFID ni placa física durante un turno activo.','error');return redirect(url_for('terminal_accesos'))
   c.execute('UPDATE camiones SET placa_vision=?,rfid_uid=?,activo=? WHERE id=?',(placa,uid,activo,camion_id))
   auditar(c,'CATALOGO_VEHICULOS',usuario_actual()['id'],anterior=dict(previo),nuevo={'placa':placa,'uid':uid,'activo':activo},motivo=motivo)
   c.commit();flash('Camión actualizado y auditado.','ok')
  except Exception as exc:
   c.rollback();flash('No se actualizó: '+str(exc),'error')
  finally:c.close()
  return redirect(url_for('terminal_accesos'))

 @app.get('/autoridad/placas-restringidas')
 @roles_required('AUTORIDAD')
 def autoridad_placas_restringidas():
  c=conectar()
  try:filas=[dict(r) for r in c.execute('SELECT * FROM fase3_placas_restringidas ORDER BY id DESC')]
  finally:c.close()
  return ctx('fase3_placas_restringidas.html',filas=filas)

 @app.post('/autoridad/placas-restringidas')
 @roles_required('AUTORIDAD')
 def autoridad_restringir_placa():
  placa=placa_norm(request.form.get('placa'));motivo=request.form.get('motivo','').strip()
  if not placa_valida(placa) or len(motivo)<10:
   flash('Placa C123ABC y motivo mínimo 10 caracteres.','error');return redirect(url_for('autoridad_placas_restringidas'))
  c=conectar()
  try:
   c.execute('BEGIN IMMEDIATE')
   c.execute('''INSERT INTO fase3_placas_restringidas(placa,motivo,usuario_alta,alta)
     VALUES (?,?,?,?)''',(placa,motivo,usuario_actual()['id'],momento()))
   auditar(c,'RESTRINGIR_PLACA',usuario_actual()['id'],nuevo=placa,motivo=motivo)
   c.commit();flash('Placa restringida.','ok')
  except Exception as exc:
   c.rollback();flash('No se pudo restringir: '+str(exc),'error')
  finally:c.close()
  return redirect(url_for('autoridad_placas_restringidas'))

 @app.post('/autoridad/placas-restringidas/<int:restriccion_id>/quitar')
 @roles_required('AUTORIDAD')
 def autoridad_quitar_restriccion(restriccion_id):
  motivo=request.form.get('motivo','').strip()
  if len(motivo)<10:
   flash('Motivo mínimo 10 caracteres.','error');return redirect(url_for('autoridad_placas_restringidas'))
  c=conectar()
  try:
   c.execute('BEGIN IMMEDIATE')
   row=c.execute('SELECT * FROM fase3_placas_restringidas WHERE id=? AND baja IS NULL',(restriccion_id,)).fetchone()
   if not row:abort(404)
   c.execute('UPDATE fase3_placas_restringidas SET usuario_baja=?,baja=?,motivo_baja=? WHERE id=?',
          (usuario_actual()['id'],momento(),motivo,restriccion_id))
   auditar(c,'QUITAR_RESTRICCION',usuario_actual()['id'],anterior=row['placa'],motivo=motivo)
   c.commit();flash('Restricción retirada.','ok')
  finally:c.close()
  return redirect(url_for('autoridad_placas_restringidas'))

 @app.get('/terminal/fase3-parametros')
 @roles_required('TERMINAL')
 def terminal_parametros_fase3():
  c=conectar()
  try:valores={r['clave']:r['valor'] for r in c.execute('SELECT * FROM fase3_parametros')}
  finally:c.close()
  return ctx('fase3_parametros.html',valores=valores,limites=DEFAULTS)

 @app.post('/terminal/fase3-parametros')
 @roles_required('TERMINAL')
 def terminal_parametros_guardar():
  try:
   valores={k:int(request.form[k]) for k in DEFAULTS}
   for k,v in valores.items():
    if not DEFAULTS[k][1]<=v<=DEFAULTS[k][2]:raise ValueError('Fuera de rango '+k)
   if valores['UmbralLuzApagado']<valores['UmbralLuzEncendido']+5:
    raise ValueError('UmbralLuzApagado debe superar Encendido por al menos 5')
  except (ValueError,KeyError) as exc:
   flash('Parámetros no guardados: '+str(exc),'error');return redirect(url_for('terminal_parametros_fase3'))
  c=conectar()
  try:
   c.execute('BEGIN IMMEDIATE')
   for k,v in valores.items():
    ant=parametro(c,k)
    c.execute('UPDATE fase3_parametros SET valor=?,actualizado=? WHERE clave=?',(v,momento(),k))
    if ant!=v:auditar(c,'PARAMETRO_'+k,usuario_actual()['id'],anterior=ant,nuevo=v)
   c.commit()
  finally:c.close()
  try:
   import paho.mqtt.client as mqtt
   from fase3_mqtt import evento
   cli=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id='parametros-f3-'+os.urandom(4).hex())
   cli.connect(os.environ.get('PORTUS_MQTT_HOST','localhost'),int(os.environ.get('PORTUS_MQTT_PORT','1883')),30)
   cli.loop_start()
   evento(cli,'portus/estacion/config','CONFIGURACION',
          {'SegundosLecturaEstacion':valores['SegundosLecturaEstacion'],
           'SegundosLatidoEstacion':valores['SegundosLatidoEstacion']})
   time.sleep(0.35)
   cli.loop_stop();cli.disconnect()
  except Exception as exc:flash('La estación no recibió parámetros nuevos: '+str(exc),'error')
  flash('Parámetros actualizados y auditados en Raspberry.','ok')
  return redirect(url_for('terminal_parametros_fase3'))

 @app.post('/terminal/iluminacion')
 @roles_required('TERMINAL')
 def terminal_modo_iluminacion():
  modo=request.form.get('modo','').upper()
  if modo not in ('AUTOMATICO','ENCENDIDO','APAGADO'):abort(400)
  c=conectar()
  try:
   c.execute('BEGIN IMMEDIATE')
   anterior=estado(c,'iluminacion_modo')
   fijar_estado(c,'iluminacion_modo',modo)
   auditar(c,'MODO_ILUMINACION',usuario_actual()['id'],anterior=anterior,nuevo=modo)
   c.commit()
  finally:c.close()
  if modo!='AUTOMATICO':
   try:enviar_mqtt('IluminacionEncender' if modo=='ENCENDIDO' else 'IluminacionApagar',{'motivo':'OPERADOR'})
   except Exception as exc:flash('Cambio guardado, sin respuesta de MQTT: '+str(exc),'error')
  flash('Modo solicitado: '+modo,'ok')
  return redirect(url_for('terminal_operacion'))

 @app.get('/api/terminal/fase3')
 @roles_required('TERMINAL')
 def api_terminal_fase3():return jsonify(resumen())
