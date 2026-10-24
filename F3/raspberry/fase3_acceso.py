#!/usr/bin/env python3
"""Prevalidación cámara+RFID, decisiones manuales y retención planificada.
Todas las autorizaciones documentales continúan pasando por garita_portus.
"""
import json, os, re, threading, time, uuid
from fase3_db import (migrar, momento, placa_norm, parametro, alarma,
                      cerrar_alarma, fijar_estado, auditar)
from fase3_mqtt import publicar,evento
from db_portus import conectar
from fase3_vision import leer_placa

EN_PROCESO=set()
MUTEX=threading.Lock()
ESPERAS_ACK={}

def publicar_confirmado(cliente,comando,params=None,timeout=4.0):
    marcador=threading.Event(); caja={}
    rid='cmd-f3-'+uuid.uuid4().hex
    with MUTEX:ESPERAS_ACK[rid]=(marcador,caja)
    publicar(cliente,comando,params or {},identificador=rid)
    try:
        if not marcador.wait(timeout):return False
        return caja.get('tipo')=='ACK'
    finally:
        with MUTEX:ESPERAS_ACK.pop(rid,None)

def recibir_respuesta(payload):
    rid=(payload.get('data') or {}).get('request_id')
    with MUTEX: par=ESPERAS_ACK.get(rid)
    if par:
        evento_ack,caja=par
        caja['tipo']=payload.get('type')
        evento_ack.set()


def distancia_uno(a,b):
 if len(a)!=len(b):return False
 return sum(x!=y for x,y in zip(a,b))==1

def resolver_texto(leido, confianza, catalogo, restringidos, minimo):
 """Coincidencia exacta o a 1 carácter SOLO si hay un único candidato."""
 if confianza<minimo:return None
 candidatos=set(catalogo)|set(restringidos)
 if leido in candidatos:return leido
 proximos=[c for c in candidatos if distancia_uno(leido,c)]
 return proximos[0] if len(proximos)==1 else None

def registrar_lectura(cliente,datos,evento_id,camion,placa_esperada,resultado,leido='',confianza=0,foto='',retencion=None,fotos=None):
 conn=conectar()
 try:
  conn.execute('BEGIN IMMEDIATE')
  conn.execute('''INSERT OR IGNORE INTO fase3_accesos
  (evento_id,uid,camion_id,camion_codigo,placa_esperada,placa_leida,confianza,foto,
   resultado,causa_retencion,transportista_id,timestamp)
   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',(
   evento_id, str(datos.get('uid') or ''),camion['id'],camion['placa'],
   placa_esperada,leido,confianza,foto,resultado,retencion,
   camion['transportista_id'],momento()))
  acceso=conn.execute('SELECT id FROM fase3_accesos WHERE evento_id=?',(evento_id,)).fetchone()
  if acceso:
   for numero,nombre in enumerate(fotos or [],1):
    conn.execute('INSERT INTO fase3_fotos_intentos(acceso_id,foto,intento) VALUES (?,?,?)',
                (acceso['id'],str(nombre),numero))
  if retencion in ('RT07','RT08'):
   alarma(conn,'AL20' if retencion=='RT07' else 'AL21','Crítica' if retencion=='RT08' else 'Alta',
          {'camion':camion['placa'],'placa_leida':leido})
  if resultado=='MANUAL':alarma(conn,'AL22','Media',{'camion':camion['placa']})
  conn.commit()
 finally:conn.close()
 evento(cliente,'portus/vision/placa','PLACA',{'camion':camion['placa'],'uid':datos.get('uid'),
     'placa':leido,'confianza':confianza,'resultado':resultado,'foto':foto or '',
     'retencion':retencion or ''})
 return acceso['id'] if acceso else None

def prevalidar(cliente, datos, evento_id, continuar):
 """Continúa solo tras reconocimiento válido; si no, espera decisión humana."""
 uid=re.sub('[^0-9A-F]','',str(datos.get('uid') or '').upper())
 with MUTEX:
  if uid in EN_PROCESO:return
  EN_PROCESO.add(uid)
 try:
  conn=conectar()
  try:
   camion=conn.execute('SELECT * FROM camiones WHERE UPPER(REPLACE(rfid_uid,\' \',\'\'))=? AND activo=1',(uid,)).fetchone()
   if camion is None:
    continuar(cliente,datos,skip_fase3=True) # el flujo original deniega RFID no registrado
    return
   camion=dict(camion)
   placa_esperada=placa_norm(camion.get('placa_vision'))
   catalogo={placa_norm(r['placa_vision']) for r in conn.execute('SELECT placa_vision FROM camiones WHERE placa_vision IS NOT NULL')}
   restringidas={r['placa'] for r in conn.execute('SELECT placa FROM fase3_placas_restringidas WHERE baja IS NULL')}
   intentos=parametro(conn,'IntentosOCR'); minimo=parametro(conn,'ConfianzaMinimaOCR')
  finally:conn.close()
  publicar(cliente,'GaritaResultado',{'estado':'LEYENDO','camion':camion['placa']})
  resultado='MANUAL';retencion=None;leido='';conf=0;foto='';fotos=[];degradado=False;inicio_verificacion=time.monotonic()
  # Toda fotografía exige encender luz y esperar 1 segundo, también en modo apagado.
  conn=conectar()
  try:
   iluminacion_previa=conn.execute("SELECT valor FROM fase3_estado WHERE clave='iluminacion_encendida'").fetchone()
   iluminacion_previa=iluminacion_previa and iluminacion_previa['valor']=='1'
  finally:conn.close()
  luz_confirmada=publicar_confirmado(cliente,'IluminacionEncender',{'captura':1,'motivo':'FOTO_PLACA'})
  if luz_confirmada:time.sleep(1)
  try:
   if not luz_confirmada:raise RuntimeError('ILUMINACION_NO_CONFIRMADA')
   lectura=leer_placa(intentos)
   leido=placa_norm(lectura['placa']);conf=lectura['confianza'];foto=lectura['foto'];fotos=lectura.get('fotos',[])
   if time.monotonic()-inicio_verificacion > 30:  # segundo límite físico independiente
    raise RuntimeError('OCR_EXCEDIO_TIEMPO_DE_LECTURA')
   candidato=resolver_texto(leido,conf,catalogo,restringidas,minimo)
   if candidato:
    if candidato in restringidas:
     resultado='RESTRINGIDA';retencion='RT08'
    elif placa_esperada and candidato==placa_esperada:resultado='VERIFICADA'
    elif placa_esperada:resultado='NO_COINCIDE';retencion='RT07'
  except Exception as exc:
   degradado=not isinstance(exc,ValueError)
   print('[FASE3 CAMARA/PLACA]',type(exc).__name__,exc)
   if degradado:
    conn=conectar()
    try:
     conn.execute('BEGIN IMMEDIATE');alarma(conn,'AL18','Alta',{'detalle':str(exc)[:180]})
     fijar_estado(conn,'camara_estado','FUERA_DE_SERVICIO');conn.commit()
    finally:conn.close()
    publicar(cliente,'GaritaResultado',{'estado':'DEGRADADO','camion':camion['placa']})
  publicar(cliente,'IluminacionEncender' if iluminacion_previa else 'IluminacionApagar',
          {'captura':0,'motivo':'FIN_FOTO'})
  # Si el tiempo configurado se excedió, el operador debe revisar incluso si el OCR terminó.
  conn=conectar()
  try:limite=parametro(conn,'SegundosEsperaVerificacion')
  finally:conn.close()
  if time.monotonic()-inicio_verificacion > limite:
   resultado='MANUAL';retencion=None
  acceso_id=registrar_lectura(cliente,datos,evento_id,camion,placa_esperada,resultado,leido,conf,foto,retencion,fotos)
  datos=dict(datos);datos['_fase3_acceso_id']=acceso_id
  if resultado=='MANUAL':
   if not degradado:publicar(cliente,'GaritaResultado',{'estado':'MANUAL','camion':camion['placa']})
   return
  if retencion:
   # no admitir vehículo de riesgo sin plaza, incluso si levante original es VERDE
   conn=conectar()
   try:
    libres=conn.execute('SELECT COUNT(*) FROM plazas_retencion WHERE ocupada=0').fetchone()[0]
   finally:conn.close()
   if not libres:
    publicar(cliente,'CerrarTalanquera',{'causa':'PARQUEO_LLENO'})
    return
   publicar(cliente,'GaritaResultado',{'estado':'RESTRINGIDA' if retencion=='RT08' else 'NO_COINCIDE',
                                       'placa':leido,'camion':camion['placa']})
  else:
   publicar(cliente,'GaritaResultado',{'estado':'VERIFICADA','placa':leido,'camion':camion['placa']})
  continuar(cliente,datos,skip_fase3=True)
 finally:
  with MUTEX:EN_PROCESO.discard(uid)

def respuesta_manual(cliente, payload, continuar):
 id_acceso=payload.get('data',{}).get('acceso_id')
 if not isinstance(id_acceso,int):return
 conn=conectar()
 try:
  acceso=conn.execute("SELECT * FROM fase3_accesos WHERE id=?",(id_acceso,)).fetchone()
  if not acceso or acceso['resultado'] not in ('APROBADA_MANUAL','RECHAZADA_MANUAL'):return
  from datetime import datetime
  from zoneinfo import ZoneInfo
  try:
   instante=datetime.fromisoformat(acceso['timestamp'])
   if (datetime.now(ZoneInfo('America/Guatemala'))-instante).total_seconds()>110:return
  except (TypeError,ValueError):return
  mas_nuevo=conn.execute('SELECT id FROM fase3_accesos WHERE camion_id=? ORDER BY id DESC LIMIT 1',
                         (acceso['camion_id'],)).fetchone()
  if not mas_nuevo or mas_nuevo['id']!=acceso['id']:return
  decision=acceso
  if decision['usuario_decision'] is None:return
  datos={'uid':acceso['uid'],'camion':acceso['camion_codigo'],'_fase3_acceso_id':acceso['id']}
  if decision['resultado']=='APROBADA_MANUAL':
   publicar(cliente,'GaritaResultado',{'estado':'VERIFICADA','placa':acceso['placa_leida'] or acceso['placa_esperada'] or ''})
   continuar(cliente,datos,skip_fase3=True)
  elif decision['resultado']=='RECHAZADA_MANUAL':
   publicar(cliente,'CerrarTalanquera',{'causa':'RECHAZO_OPERADOR'})
 finally:conn.close()
