#!/usr/bin/env python3
"""Pruebas desconectadas: no mueve servos, no usa MQTT ni Flask."""
import json
import tempfile
from pathlib import Path
import db_portus
import supervision_portus as s

with tempfile.TemporaryDirectory() as folder:
    ruta=Path(folder)/'test_portus.db'
    db_portus.inicializar_bd(ruta)
    s.conectar=lambda:db_portus.conectar(ruta)
    c=db_portus.conectar(ruta)
    c.execute("INSERT INTO navieras(id,nombre) VALUES(1,'Naviera prueba')")
    c.execute("INSERT INTO transportistas(id,nombre) VALUES(1,'Transportista prueba')")
    c.execute("INSERT INTO camiones(id,placa,rfid_uid,transportista_id,tara_g) VALUES(1,'CAM-04','E158F3B0',1,23.9)")
    c.execute("INSERT INTO contenedores(id,naviera_id) VALUES('C1',1)")
    c.execute("""INSERT INTO manifiestos(id,naviera_id,contenedor_id,operacion,
              peso_declarado_g,transportista_id) VALUES('M1002',1,'C1','DEPOSITO',13,1)""")
    c.execute("""INSERT INTO declaraciones(numero,manifiesto_id,regimen,descripcion,valor_declarado,
              levante_estado,canal) VALUES('DEC1','M1002','IMPORTACION_DEFINITIVA','Contenedor de prueba',100,'OTORGADO','VERDE')""")
    c.execute("""INSERT INTO turnos(id,manifiesto_id,camion_id,contenedor_id,operacion,
              estado,estacion,inicio,cierre) VALUES('T1','M1002',1,'C1','DEPOSITO','Cerrado','SALIDA','2026-09-26 01:00:00','2026-09-26 01:15:00')""")
    c.execute("INSERT INTO citas(manifiesto_id,contenedor_id,transportista_id,camion_id,inicio,fin,estado,dentro_ventana) VALUES('M1002','C1',1,1,'2026-09-26 01:00:00','2026-09-26 01:15:00','CUMPLIDA',1)")
    c.execute("""INSERT INTO eventos(id,timestamp,topic,origen,tipo,secuencia,datos_json,mensaje_json)
              VALUES('evt1','2026-09-26T01:00:10-06:00','portus/evt/garita','controller','GARITA',1,?,?)""",
              (json.dumps({'turno':'T1','accion':'INGRESO'}),'{"id":"evt1"}'))
    c.execute("INSERT INTO usuarios(id,username,password_hash,nombre,rol) VALUES (1,'terminal','HASH','Prueba','TERMINAL')")
    c.execute("INSERT INTO alarmas(codigo,severidad,timestamp,datos_json) VALUES('AL14','Alta','2026-09-26 01:00:00','{}')")
    c.commit();c.close()
    d=s.detalle_turno('T1')
    assert d['turno']['estado']=='Cerrado' and len(d['eventos'])==1
    assert s.detalle_turno('T99') is None
    assert s.turnos()[0]['camion']=='CAM-04'
    snapshot=s.estado_terminal()
    assert snapshot['conteos']['turnos']==0 and len(snapshot['plazas'])==3
    assert s.alarmas()[0]['codigo']=='AL14'
    assert s.reconocer_alarma(1,1)
    assert not s.reconocer_alarma(1,1)
    assert s.alarmas('RECONOCIDA')[0]['codigo']=='AL14' 
    r=s.reportes('2026-09-26','2026-09-26')
    assert r['indicadores']['turnos_cerrados']==1
    assert abs(r['indicadores']['tiempo_promedio_terminal_min']-15)<.05
    assert r['indicadores']['porcentaje_citas_cumplidas_en_ventana']==100
    assert r['indicadores']['remociones_por_retiro'] is None
    assert 'PORTUS' in s.csv_reporte(r)
    assert len(s.patio())==1
    assert s.grua()==[]
    print('OK: esquema, línea de tiempo, tablero, métricas, CSV, patio, alarmas')
