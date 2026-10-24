"""Utilidades comunes para publicar órdenes con el formato vigente de PORTUS."""
import json,uuid,os
from fase3_db import momento

def publicar(client,comando,params=None,topico='portus/cmd/solicitud',identificador=None):
 identificador=identificador or ('cmd-f3-'+uuid.uuid4().hex)
 p={'id':identificador,'timestamp':momento(),'origin':'server','type':'CMD',
    'data':{'command':comando.upper(),'params':params or {}}}
 info=client.publish(topico,json.dumps(p,ensure_ascii=False,separators=(',',':')),qos=1)
 return identificador

def evento(client,topico,tipo,data):
 p={'id':'evt-f3-'+uuid.uuid4().hex,'timestamp':momento(),
    'origin':'server','type':tipo,'data':data}
 client.publish(topico,json.dumps(p,ensure_ascii=False),qos=1)
 return p
