#!/usr/bin/env python3
"""Migración aditiva Fase 3. Nunca reemplaza ni vacía portus.db."""
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from db_portus import conectar

TZ=ZoneInfo('America/Guatemala')
DEFAULTS={
 'SegundosLecturaEstacion':(5,2,60),
 'SegundosLatidoEstacion':(10,5,60),
 'MinutosSinLluviaReanudar':(2,1,30),
 'UmbralLuzEncendido':(30,0,95),
 'UmbralLuzApagado':(45,5,100),
 'ConfianzaMinimaOCR':(60,30,95),
 'IntentosOCR':(3,1,5),
 'SegundosEsperaVerificacion':(10,5,30),
 'SegundosConteoCola':(5,2,30),
 'UmbralCola':(3,1,10),
}

def momento(): return datetime.now(TZ).isoformat(timespec='seconds')
def placa_norm(placa): return re.sub(r'\s+','',str(placa or '').upper())
def placa_valida(placa): return re.fullmatch(r'C[0-9]{3}[A-Z]{3}',placa_norm(placa)) is not None

def ampliar_causas_retencion():
 """Amplía CHECK RT01-06 -> RT01-08 conservando filas. Operación transaccional."""
 c=conectar()
 try:
  sql_row=c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='retenciones'").fetchone()
  if not sql_row or "'RT08'" in sql_row['sql']:
   return
  original=sql_row['sql']
  if "'RT06'" not in original or "'RT07'" in original:
   raise RuntimeError('Estructura de retenciones desconocida; no se migra para preservar datos')
  c.execute('PRAGMA foreign_keys=OFF')
  c.execute('BEGIN IMMEDIATE')
  # La tabla retenciones no tiene tablas hijas en el modelo F2 estándar.
  hijas=[r['name'] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
         if r['name'] != 'retenciones' and any(f['table']=='retenciones' for f in c.execute('PRAGMA foreign_key_list("'+r['name'].replace('"','')+'")'))]
  if hijas:
   raise RuntimeError('Migración requiere revisión de FKs externas a retenciones: '+str(hijas))
  nuevo=original.replace('CREATE TABLE IF NOT EXISTS retenciones', 'CREATE TABLE retenciones_f3').replace(
       'CREATE TABLE retenciones', 'CREATE TABLE retenciones_f3').replace("'RT06'", "'RT06','RT07','RT08'")
  c.execute(nuevo)
  columnas=[r['name'] for r in c.execute('PRAGMA table_info(retenciones)')]
  campos=','.join('"'+x+'"' for x in columnas)
  c.execute(f'INSERT INTO retenciones_f3({campos}) SELECT {campos} FROM retenciones')
  c.execute('DROP TABLE retenciones')
  c.execute('ALTER TABLE retenciones_f3 RENAME TO retenciones')
  c.commit()
 except Exception:
  c.rollback(); raise
 finally:
  c.execute('PRAGMA foreign_keys=ON');c.close()

def migrar():
 ampliar_causas_retencion()
 c=conectar()
 try:
  c.execute('BEGIN IMMEDIATE')
  cols={x['name'] for x in c.execute('PRAGMA table_info(camiones)')}
  if 'placa_vision' not in cols:
   c.execute('ALTER TABLE camiones ADD COLUMN placa_vision TEXT')
  c.execute('CREATE UNIQUE INDEX IF NOT EXISTS ux_camion_placa_vision ON camiones(placa_vision) WHERE placa_vision IS NOT NULL')
  c.execute('''CREATE TABLE IF NOT EXISTS fase3_parametros (
    clave TEXT PRIMARY KEY, valor INTEGER NOT NULL, actualizado TEXT NOT NULL)''')
  c.execute('''CREATE TABLE IF NOT EXISTS fase3_estado (
    clave TEXT PRIMARY KEY, valor TEXT NOT NULL, actualizado TEXT NOT NULL)''')
  c.execute('''CREATE TABLE IF NOT EXISTS fase3_auditoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT, usuario_id INTEGER, origen TEXT NOT NULL,
    accion TEXT NOT NULL, anterior TEXT, nuevo TEXT, motivo TEXT,
    timestamp TEXT NOT NULL)''')
  c.execute('''CREATE TABLE IF NOT EXISTS fase3_placas_restringidas (
    id INTEGER PRIMARY KEY AUTOINCREMENT, placa TEXT NOT NULL, motivo TEXT NOT NULL,
    usuario_alta INTEGER NOT NULL, alta TEXT NOT NULL,
    usuario_baja INTEGER, baja TEXT, motivo_baja TEXT)''')
  c.execute('CREATE UNIQUE INDEX IF NOT EXISTS ux_fase3_restringida ON fase3_placas_restringidas(placa) WHERE baja IS NULL')
  c.execute('''CREATE TABLE IF NOT EXISTS fase3_accesos (
    id INTEGER PRIMARY KEY AUTOINCREMENT, evento_id TEXT UNIQUE,
    uid TEXT NOT NULL, camion_id INTEGER, camion_codigo TEXT,
    placa_esperada TEXT, placa_leida TEXT, confianza REAL,
    foto TEXT, resultado TEXT NOT NULL, causa_retencion TEXT,
    turno_id TEXT, transportista_id INTEGER,
    usuario_decision INTEGER, motivo_decision TEXT,
    timestamp TEXT NOT NULL, resuelto TEXT)''')
  c.execute('CREATE INDEX IF NOT EXISTS ix_fase3_accesos_camion ON fase3_accesos(camion_id,timestamp)')
  c.execute('''CREATE TABLE IF NOT EXISTS fase3_fotos_intentos(
    id INTEGER PRIMARY KEY AUTOINCREMENT, acceso_id INTEGER NOT NULL,
    foto TEXT NOT NULL, intento INTEGER NOT NULL)''')
  c.execute('''CREATE TABLE IF NOT EXISTS fase3_fotos_notificacion (
    notificacion_id INTEGER PRIMARY KEY, archivo TEXT NOT NULL)''')
  c.execute('''CREATE TABLE IF NOT EXISTS fase3_clima_historial (
    id INTEGER PRIMARY KEY AUTOINCREMENT, instante TEXT NOT NULL,
    temperatura REAL, humedad REAL, lluvia INTEGER, luz REAL)''')
  # Snapshot consultable por el dashboard: una fila por estación física.
  # El historial anterior se conserva para análisis y auditoría ambiental.
  c.execute('''CREATE TABLE IF NOT EXISTS fase3_estacion_climatologica (
    estacion_id TEXT PRIMARY KEY, timestamp_sensor TEXT NOT NULL,
    recibido TEXT NOT NULL, temperatura_c REAL NOT NULL,
    humedad_pct REAL NOT NULL, lluvia INTEGER NOT NULL CHECK (lluvia IN (0,1)),
    luz_pct REAL NOT NULL CHECK (luz_pct BETWEEN 0 AND 100),
    topico TEXT NOT NULL DEFAULT 'portus/estacion/lectura')''')
  for k,(v,lo,hi) in DEFAULTS.items():
   c.execute('INSERT OR IGNORE INTO fase3_parametros(clave,valor,actualizado) VALUES (?,?,?)',(k,v,momento()))
  for k,v in [('iluminacion_modo','AUTOMATICO'),('iluminacion_encendida','1'),
              ('estacion_estado','DESCONOCIDO'),('camara_estado','DESCONOCIDO'),
              ('cola_estado','NO_DISPONIBLE'),('grua_clima','DESCONOCIDO')]:
   c.execute('INSERT OR IGNORE INTO fase3_estado(clave,valor,actualizado) VALUES (?,?,?)',(k,v,momento()))
  c.commit()
 finally: c.close()

def parametro(c,n):
 r=c.execute('SELECT valor FROM fase3_parametros WHERE clave=?',(n,)).fetchone()
 return int(r['valor']) if r else DEFAULTS[n][0]

def estado(c,k,default=None):
 r=c.execute('SELECT valor FROM fase3_estado WHERE clave=?',(k,)).fetchone()
 return r['valor'] if r else default

def fijar_estado(c,k,v):
 c.execute('''INSERT INTO fase3_estado(clave,valor,actualizado) VALUES (?,?,?)
 ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor,actualizado=excluded.actualizado''',
 (k,str(v),momento()))

def auditar(c,accion,usuario_id=None,origen='SERVIDOR',anterior=None,nuevo=None,motivo=None):
 c.execute('''INSERT INTO fase3_auditoria(usuario_id,origen,accion,anterior,nuevo,motivo,timestamp)
 VALUES (?,?,?,?,?,?,?)''',(usuario_id,origen,accion,str(anterior or ''),str(nuevo or ''),motivo,momento()))

def alarma(c,codigo,severidad='Media',detalle=None):
 # Evita alarmas repetidas, solo se renueva después de cerrarse.
 previa=c.execute("SELECT id FROM alarmas WHERE codigo=? AND estado='ACTIVA' ORDER BY id DESC LIMIT 1",(codigo,)).fetchone()
 if previa:return previa['id']
 cur=c.execute('INSERT INTO alarmas(codigo,severidad,timestamp,datos_json) VALUES (?,?,?,?)',
      (codigo,severidad,momento(),json.dumps(detalle or {},ensure_ascii=False)))
 return cur.lastrowid

def cerrar_alarma(c,codigo):
 c.execute("UPDATE alarmas SET estado='CERRADA' WHERE codigo=? AND estado='ACTIVA'",(codigo,))

if __name__=='__main__':
 migrar();print('Migracion fase 3 aplicada sin borrar registros.')
