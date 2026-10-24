#!/usr/bin/env python3
"""Fase3 Raspberry: recepción MQTT de clima, iluminación y conteo real COCO.
Las lecturas ambientales solo se guardan cuando llegan válidas desde la estación.
"""
import json,os,time,threading
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import paho.mqtt.client as mqtt
from db_portus import conectar
from fase3_db import migrar, parametro, estado, fijar_estado, momento, alarma, cerrar_alarma, auditar
from fase3_mqtt import publicar, evento

TZ=ZoneInfo('America/Guatemala')
cliente=None
ultimo_latido=None
inicio_servicio=datetime.now(TZ)
inicio_sin_lluvia=None
lluvia_previa=None
cola_trabajando=False
ultimo_error_vision=''

def guardar_notificacion_afectados(conn,tipo,texto):
 ahora=datetime.now(TZ).replace(tzinfo=None)
 siguiente=ahora+timedelta(minutes=30)
 rows=conn.execute('''SELECT DISTINCT transportista_id FROM (
  SELECT m.transportista_id AS transportista_id FROM turnos t JOIN manifiestos m ON m.id=t.manifiesto_id
  WHERE t.estado NOT IN ('Cerrado','Anulado')
  UNION ALL SELECT transportista_id FROM citas WHERE estado='PROGRAMADA' AND inicio<=? AND fin>=?
 ) WHERE transportista_id IS NOT NULL''',(siguiente.strftime('%Y-%m-%d %H:%M:%S'),ahora.strftime('%Y-%m-%d %H:%M:%S'))).fetchall()
 for r in rows:
  conn.execute("INSERT INTO notificaciones_transportista(transportista_id,tipo,mensaje) VALUES (?,?,?)",(r[0],tipo,texto))

def iluminacion(client,encender,motivo):
 conn=conectar()
 try:
  previo=estado(conn,'iluminacion_encendida')
  if previo==('1' if encender else '0'):return
 finally:conn.close()
 publicar(client,'IluminacionEncender' if encender else 'IluminacionApagar',{'motivo':motivo})

def lluvia_bool(valor):
 if isinstance(valor,str):
  normal=valor.strip().lower()
  if normal in ('1','true','si','sí','lloviendo','rain','wet'):return True
  if normal in ('0','false','no','seco','sin lluvia','dry'):return False
  raise ValueError('Valor de lluvia no reconocido')
 if isinstance(valor,(int,float)) and valor in (0,1):return bool(valor)
 if isinstance(valor,bool):return valor
 raise ValueError('Valor de lluvia no reconocido')

def procesar_estacion(client,payload,topico):
 global ultimo_latido, inicio_sin_lluvia, lluvia_previa
 data=payload.get('data',{})
 if not isinstance(data,dict):return
 ahora=datetime.now(TZ)
 conn=conectar()
 try:
  if topico.endswith('/estado'):
   ultimo_latido=ahora
   fijar_estado(conn,'estacion_estado','OPERATIVA')
   fijar_estado(conn,'estacion_latido',momento())
   cerrar_alarma(conn,'AL16');conn.commit()
   return
  t=data.get('temperatura',data.get('temperatura_c'))
  h=data.get('humedad',data.get('humedad_pct'))
  luz=data.get('luz',data.get('nivel_luz'))
  lluvia=data.get('lluvia',data.get('lloviendo'))
  if t is None or h is None or luz is None or lluvia is None:return
  t=float(t);h=float(h);luz=float(luz)
  if not (-30<=t<=80 and 0<=h<=100 and 0<=luz<=100):return
  try:lluvia=lluvia_bool(lluvia)
  except ValueError:return
  ultimo_latido=ahora
  estacion_id=str(data.get('estacion_id') or payload.get('origin') or 'estacion-esp32')[:80]
  timestamp_sensor=str(payload.get('timestamp') or momento())[:64]
  recibido=momento()
  fijar_estado(conn,'estacion_estado','OPERATIVA');fijar_estado(conn,'estacion_latido',momento())
  fijar_estado(conn,'temperatura',t);fijar_estado(conn,'humedad',h)
  fijar_estado(conn,'luz',luz);fijar_estado(conn,'lluvia','1' if lluvia else '0')
  conn.execute('''INSERT INTO fase3_estacion_climatologica
    (estacion_id,timestamp_sensor,recibido,temperatura_c,humedad_pct,lluvia,luz_pct,topico)
    VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(estacion_id) DO UPDATE SET
    timestamp_sensor=excluded.timestamp_sensor,recibido=excluded.recibido,
    temperatura_c=excluded.temperatura_c,humedad_pct=excluded.humedad_pct,
    lluvia=excluded.lluvia,luz_pct=excluded.luz_pct,topico=excluded.topico''',
    (estacion_id,timestamp_sensor,recibido,t,h,int(lluvia),luz,topico))
  conn.execute('INSERT INTO fase3_clima_historial(instante,temperatura,humedad,lluvia,luz) VALUES (?,?,?,?,?)',
               (recibido,t,h,int(lluvia),luz))
  cerrar_alarma(conn,'AL16')
  modo=estado(conn,'iluminacion_modo','AUTOMATICO')
  encendida=estado(conn,'iluminacion_encendida','1')=='1'
  if modo=='ENCENDIDO':objetivo=True
  elif modo=='APAGADO':objetivo=False
  else:
   objetivo = True if luz<parametro(conn,'UmbralLuzEncendido') else (False if luz>parametro(conn,'UmbralLuzApagado') else encendida)
  if objetivo!=encendida:iluminacion(client,objetivo,'AUTO')
  if lluvia:
   inicio_sin_lluvia=None
   if lluvia_previa is not True:
    alarma(conn,'AL17','Media',{'lluvia':True})
    fijar_estado(conn,'grua_clima','ORDEN_SUSPENSION_PENDIENTE')
    fijar_estado(conn,'suspension_desde',momento())
    publicar(client,'GruaSuspender',{'motivo':'Clima'},topico='portus/cmd/grua/solicitud')
    # Requiere ACK del Arduino de grúa integrado externamente
    guardar_notificacion_afectados(conn,'LLUVIA_SUSPENSION',
          'PORTUS: lluvia detectada. Se solicitó suspensión de grúa; su operación podría retrasarse.')
    auditar(conn,'INICIO_LLUVIA',origen='AUTOMATICO',nuevo='lloviendo')
    evento(client,'portus/evt/clima','CLIMA',{'accion':'INICIO','grua':'ORDEN_PENDIENTE'})
  else:
   if lluvia_previa is True:inicio_sin_lluvia=ahora
   if inicio_sin_lluvia and (ahora-inicio_sin_lluvia).total_seconds()>=60*parametro(conn,'MinutosSinLluviaReanudar'):
    publicar(client,'GruaReanudar',{'motivo':'Clima'},topico='portus/cmd/grua/solicitud')
    fijar_estado(conn,'grua_clima','ORDEN_REANUDACION_PENDIENTE')
    cerrar_alarma(conn,'AL17')
    auditar(conn,'FIN_LLUVIA',origen='AUTOMATICO',nuevo='sin lluvia')
    guardar_notificacion_afectados(conn,'LLUVIA_REANUDACION',
          'PORTUS: terminó la lluvia y se solicitó reanudar la grúa.')
    evento(client,'portus/evt/clima','CLIMA',{'accion':'FIN','grua':'ORDEN_PENDIENTE'})
    inicio_sin_lluvia=None
  lluvia_previa=lluvia
  conn.commit()
 finally:conn.close()

def estado_conteo(client):
 global cola_trabajando, ultimo_error_vision
 if cola_trabajando:return
 cola_trabajando=True
 def tarea():
  global cola_trabajando, ultimo_error_vision
  try:
   from fase3_vision import contar_vehiculos
   n=contar_vehiculos()
   conn=conectar()
   try:
    limite=parametro(conn,'UmbralCola')
    fijar_estado(conn,'cola_estado',str(n));fijar_estado(conn,'camara_estado','OPERATIVA')
    cerrar_alarma(conn,'AL18')
    if n>=limite:alarma(conn,'AL19','Media',{'cantidad':n})
    else:cerrar_alarma(conn,'AL19')
    conn.commit()
   finally:conn.close()
   evento(client,'portus/vision/cola','COLA',{'cantidad':n,'congestionada':n>=limite})
   evento(client,'portus/vision/estado','VISION',{'camara':'OPERATIVA','conteo':'DISPONIBLE'})
   ultimo_error_vision=''
  except Exception as exc:
   error=str(exc)[:180]
   if error!=ultimo_error_vision:print('[FASE3 VISION]',error);ultimo_error_vision=error
   conn=conectar()
   try:
    fijar_estado(conn,'camara_estado','FUERA_DE_SERVICIO')
    fijar_estado(conn,'cola_estado','NO_DISPONIBLE')
    alarma(conn,'AL18','Alta',{'detalle':error});conn.commit()
   finally:conn.close()
   evento(client,'portus/vision/estado','VISION',{'camara':'FUERA_DE_SERVICIO','detalle':error})
  finally:cola_trabajando=False
 threading.Thread(target=tarea,daemon=True).start()

def gestionar_inactividad(client):
 conn=conectar()
 try:
  ultima=estado(conn,'estacion_latido')
  if ultima:
   try:edad=(datetime.now(TZ)-datetime.fromisoformat(ultima)).total_seconds()
   except Exception:edad=1e6
  else:
   edad=(datetime.now(TZ)-inicio_servicio).total_seconds()
  if edad>3*parametro(conn,'SegundosLatidoEstacion'):
   if estado(conn,'estacion_estado')!='FUERA_DE_SERVICIO':
    fijar_estado(conn,'estacion_estado','FUERA_DE_SERVICIO')
    alarma(conn,'AL16','Alta',{'detalle':'Tres latidos sin estación'})
    iluminacion(client,True,'FALLO_ESTACION')
   # no emitir órdenes de grúa por caída meteorológica
   conn.commit()
 finally:conn.close()

def on_connect(client,userdata,flags,code,props):
 if code==0:
  for topic in ('portus/estacion/lectura','portus/estacion/estado','portus/cmd/respuesta','portus/cmd/grua/respuesta'):
   client.subscribe(topic,qos=1)
  print('[FASE3] Suscrito a estación / respuestas de controladores')

def on_message(client,userdata,msg):
 try:
  p=json.loads(msg.payload.decode('utf-8'))
  if msg.topic.startswith('portus/estacion/'):procesar_estacion(client,p,msg.topic)
  elif msg.topic=='portus/cmd/respuesta':
   d=p.get('data',{});cmd=str(d.get('command','')).upper()
   if cmd in ('ILUMINACIONENCENDER','ILUMINACIONAPAGAR') and p.get('type')=='ACK':
    conn=conectar()
    try:fijar_estado(conn,'iluminacion_encendida','1' if cmd.endswith('ENCENDER') else '0');conn.commit()
    finally:conn.close()
  elif msg.topic=='portus/cmd/grua/respuesta':
   d=p.get('data',{});cmd=str(d.get('command','')).upper()
   if p.get('type')=='ACK' and cmd in ('GRUASUSPENDER','GRUAREANUDAR'):
    conn=conectar()
    try:fijar_estado(conn,'grua_clima','SUSPENDIDA' if cmd=='GRUASUSPENDER' else 'OPERANDO');conn.commit()
    finally:conn.close()
    publicar(client,'BalizaClima',{'estado':1 if cmd=='GRUASUSPENDER' else 0})
 except Exception as exc:print('[FASE3 MQTT ERROR]',exc)

def main():
 global cliente
 migrar()
 cliente=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id='portus-fase3-main')
 cliente.on_connect=on_connect;cliente.on_message=on_message
 cliente.connect(os.environ.get('PORTUS_MQTT_HOST','localhost'),int(os.environ.get('PORTUS_MQTT_PORT','1883')),60)
 cliente.loop_start()
 ultimo_conteo=0; ultimo_ping=0
 try:
  while True:
   gestionar_inactividad(cliente)
   if time.monotonic()-ultimo_ping>=5:
    publicar(cliente,'PING',{})
    conn_config=conectar()
    try:valor=parametro(conn_config,'SegundosEsperaVerificacion')
    finally:conn_config.close()
    publicar(cliente,'GaritaResultado',{'estado':'CONFIG','segundos':valor})
    ultimo_ping=time.monotonic()
   conn=conectar()
   try:periodo=parametro(conn,'SegundosConteoCola')
   finally:conn.close()
   if time.monotonic()-ultimo_conteo>=periodo:
    estado_conteo(cliente);ultimo_conteo=time.monotonic()
   time.sleep(1)
 except KeyboardInterrupt:pass
 finally:cliente.loop_stop();cliente.disconnect()
if __name__=='__main__':main()
