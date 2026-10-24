#!/usr/bin/env python3
"""Diagnóstico sin mover actuadores ni simular sensores."""
from pathlib import Path
from importlib.util import find_spec
import os,subprocess
from db_portus import conectar
from fase3_db import migrar, estado

migrar()
print('=== PORTUS FASE 3 - Diagnóstico NO ACTUANTE ===')
print('Puerto configurado:',os.environ.get('PORTUS_SERIAL_PORT','/dev/ttyACM0'))
by_id=Path('/dev/serial/by-id')
if by_id.exists():
 for path in sorted(by_id.iterdir()):print('USB-ID:',path,'->',path.resolve())
else:print('Sin /dev/serial/by-id: revisar conexiones USB')
print('Cámara /dev/video0:',Path('/dev/video0').exists())
for mod in ['cv2','pytesseract','ultralytics','paho.mqtt']:
 try:disponible=find_spec(mod) is not None
 except ModuleNotFoundError:disponible=False
 print(mod,':','INSTALADO' if disponible else 'NO INSTALADO')
try:
 r=subprocess.run(['tesseract','--version'],capture_output=True,text=True,timeout=3)
 print('Tesseract:',r.stdout.splitlines()[0] if r.stdout else r.stderr.splitlines()[0])
except Exception:print('Tesseract: NO DISPONIBLE')
peso=Path(os.environ.get('PORTUS_MODELO_CONTEO',str(Path(__file__).resolve().parent/'modelos'/'yolov8n.pt')))
print('Modelo COCO local:',peso,'EXISTE' if peso.is_file() else 'FALTA')
c=conectar()
try:
 camiones=c.execute('SELECT placa,placa_vision,rfid_uid FROM camiones ORDER BY id').fetchall()
 print('Placas impresas registradas:',sum(bool(x['placa_vision']) for x in camiones),'/',len(camiones))
 for x in camiones:print('  ',x['placa'],'RFID',x['rfid_uid'],'placa impresa:',x['placa_vision'] or 'FALTA')
 for k in ['estacion_estado','estacion_latido','luz','lluvia','camara_estado','cola_estado',
           'iluminacion_encendida','iluminacion_modo','grua_clima']:
  print(' ',k,':',estado(c,k,'NO REPORTADO'))
 print('Accesos manuales pendientes:',c.execute("SELECT count(*) FROM fase3_accesos WHERE resultado='MANUAL'").fetchone()[0])
 print('Retenciones RT07/08:',c.execute("SELECT count(*) FROM retenciones WHERE causa IN ('RT07','RT08')").fetchone()[0])
finally:c.close()
print('\nNo se publicó MQTT, no se movieron servos ni se generaron datos meteorológicos.')
