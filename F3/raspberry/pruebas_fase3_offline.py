#!/usr/bin/env python3
"""Pruebas sin Raspberry ni Arduino: NO usan portus.db real ni fuentes simuladas para evaluación.
Valida esquema, restricciones y algoritmo de comparación. No publican MQTT.
"""
import os,sys,tempfile,shutil,subprocess
from pathlib import Path
SOURCE=Path(__file__).resolve().parent
NAMES=('db_portus.py','fase3_db.py','fase3_mqtt.py','fase3_vision.py','fase3_acceso.py')
with tempfile.TemporaryDirectory(prefix='portus-f3-pruebas-') as folder:
 d=Path(folder)
 for n in NAMES:shutil.copy2(SOURCE/n,d/n)
 script='''
from db_portus import conectar,inicializar_bd
from fase3_db import migrar,placa_norm,placa_valida,DEFAULTS,parametro,fijar_estado,estado
from fase3_acceso import resolver_texto
inicializar_bd()
migrar();migrar()
c=conectar()
assert placa_valida('c 123 bcd')
assert placa_norm('c 123 bcd')=='C123BCD'
assert not placa_valida('CAM-04')
assert resolver_texto('C123BCD',75,{'C123BCD','C456EFG'},set(),60)=='C123BCD'
assert resolver_texto('C123BCF',75,{'C123BCD'},set(),60)=='C123BCD'
assert resolver_texto('C123BCF',75,{'C123BCD','C123BCG'},set(),60) is None
assert resolver_texto('C123BCD',30,{'C123BCD'},set(),60) is None
c.execute("INSERT INTO navieras(nombre) VALUES ('PRUEBA')")
c.execute("INSERT INTO transportistas(nombre) VALUES ('PRUEBA')")
c.execute("INSERT INTO camiones(placa,rfid_uid,transportista_id,tara_g,placa_vision) VALUES ('CAM-04','E158F3B0',1,23.9,'C123BCD')")
try:
 c.execute("INSERT INTO camiones(placa,rfid_uid,transportista_id,tara_g,placa_vision) VALUES ('CAM-05','E116F9B0',1,23.9,'C123BCD')")
 raise AssertionError('No detectó placa duplicada')
except Exception as exc:
 assert 'UNIQUE' in str(exc)
assert parametro(c,'ConfianzaMinimaOCR')==60
fijar_estado(c,'estacion_estado','FUERA_DE_SERVICIO')
assert estado(c,'estacion_estado')=='FUERA_DE_SERVICIO'
# verificación de CHECK del catálogo nuevo, sin insertar turnos reales
sql=c.execute("SELECT sql FROM sqlite_master WHERE name='retenciones'").fetchone()['sql']
assert "'RT07'" in sql and "'RT08'" in sql
c.commit()
assert not c.execute('PRAGMA foreign_key_check').fetchall()
c.close()
print('OK: F3 migraciones repetibles, UID/placa únicos, reglas OCR, parámetros y RT07/RT08')
'''
 (d/'run.py').write_text(script,encoding='utf-8')
 env=dict(os.environ)
 env['PYTHONPATH']=str(d)
 result=subprocess.run([sys.executable,str(d/'run.py')],cwd=d,env=env,
                       capture_output=True,text=True)
 print(result.stdout,end='')
 if result.returncode:
  print(result.stderr);raise SystemExit(result.returncode)
