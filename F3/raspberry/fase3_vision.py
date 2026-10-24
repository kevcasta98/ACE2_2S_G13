#!/usr/bin/env python3
"""Cámara real + OCR preentrenado (Tesseract) + YOLO COCO (conteo).
El OCR por evento usa ROI de respaldo fija documentada. Nunca simula detecciones.
"""
import os, time, threading, uuid, re
from pathlib import Path
from fase3_db import placa_norm

ROOT=Path(__file__).resolve().parent
FOTOS=ROOT/'evidencias'/'garita'
LOCK=threading.RLock()
CAMARA=int(os.environ.get('PORTUS_CAMARA','0'))
_modelo_placas=None
# x, y, w, h fracciones de la imagen. Deben ajustarse mirando la maqueta real.
def roi(nombre,predeterminado):
 t=os.environ.get('PORTUS_ROI_'+nombre,predeterminado)
 try:
  v=[float(x) for x in t.split(',')]
  if len(v)!=4 or not all(0<=x<=1 for x in v) or v[2]<=0 or v[3]<=0 or v[0]+v[2]>1 or v[1]+v[3]>1: raise ValueError()
  return v
 except ValueError: raise ValueError('ROI '+nombre+' inválida. Ejemplo 0.5,0.3,0.4,0.3')

def recortar(im,nombre,predeterminado):
 x,y,w,h=roi(nombre,predeterminado)
 H,W=im.shape[:2]
 return im[max(0,int(y*H)):min(H,int((y+h)*H)),max(0,int(x*W)):min(W,int((x+w)*W))]

def capturar():
 import cv2
 with LOCK:
  cap=cv2.VideoCapture(CAMARA)
  try:
   if not cap.isOpened(): raise RuntimeError('CAMARA_NO_DISPONIBLE')
   ok,frame=cap.read()
   if not ok or frame is None: raise RuntimeError('CAMARA_SIN_IMAGEN')
   return frame
  finally:cap.release()

def guardar(frame):
 import cv2
 FOTOS.mkdir(parents=True,exist_ok=True)
 nombre='garita-'+uuid.uuid4().hex+'.jpg'
 ruta=FOTOS/nombre
 if not cv2.imwrite(str(ruta),frame): raise RuntimeError('NO_SE_PUDO_GUARDAR_FOTO')
 return nombre

def detectar_zona_placa(frame):
 """Detector opcional preentrenado YOLO. Si falla localización se usa ROI fija.
 Solo usar pesos descargados por el grupo y conservar fuente/licencia en la bitácora.
 """
 global _modelo_placas
 ruta=os.environ.get('PORTUS_MODELO_PLACAS','').strip()
 if ruta and Path(ruta).is_file():
  try:
   from ultralytics import YOLO
   if _modelo_placas is None:_modelo_placas=YOLO(ruta)
   res=_modelo_placas.predict(source=frame,verbose=False,device='cpu',conf=0.25,imgsz=416)[0]
   if res.boxes is not None and len(res.boxes):
    mejores=res.boxes.conf.tolist()
    indice=max(range(len(mejores)),key=lambda i:mejores[i])
    x1,y1,x2,y2=[int(n) for n in res.boxes.xyxy[indice].tolist()]
    H,W=frame.shape[:2]
    zona=frame[max(0,y1):min(H,y2),max(0,x1):min(W,x2)]
    if zona.size:return zona
  except Exception as exc:
   print('[VISION] Detector de placas no pudo localizar:',str(exc)[:120])
 return recortar(frame,'PLACA','0.40,0.25,0.57,0.50')


def sincronizado(fn):
 def wrapper(*a,**kw):
  with LOCK:return fn(*a,**kw)
 return wrapper

@sincronizado
def leer_placa(max_intentos=3):
 """No ejecuta lectura continua. Llamar solo después del RFID/presencia."""
 import cv2,pytesseract
 from pytesseract import Output
 ultimo=None; foto=None; confianza=0.0; fotos=[]
 for i in range(max_intentos):
  frame=capturar()
  foto=guardar(frame);fotos.append(foto)
  zona=detectar_zona_placa(frame)
  if zona.size==0:raise RuntimeError('ROI_PLACA_VACIA')
  gris=cv2.cvtColor(zona,cv2.COLOR_BGR2GRAY)
  gris=cv2.resize(gris,None,fx=3,fy=3,interpolation=cv2.INTER_CUBIC)
  gris=cv2.GaussianBlur(gris,(3,3),0)
  info=pytesseract.image_to_data(gris,config='--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',output_type=Output.DICT)
  piezas=[]; confs=[]
  for texto,conf in zip(info['text'],info['conf']):
   palabra=placa_norm(texto)
   if palabra and float(conf)>=0:
    piezas.append(palabra);confs.append(float(conf))
  texto=placa_norm(''.join(piezas))
  confianza=sum(confs)/len(confs) if confs else 0.0
  ultimo={'placa':texto,'confianza':round(confianza,2),'foto':foto,'fotos':fotos}
  if re.fullmatch(r'C[0-9]{3}[A-Z]{3}',texto):return ultimo
 return ultimo or {'placa':'','confianza':0.0,'foto':foto,'fotos':fotos}

_modelo=None
def contar_vehiculos():
 """Requiere peso COCO local verificado. Si no existe falla explícita."""
 global _modelo
 from ultralytics import YOLO
 peso=Path(os.environ.get('PORTUS_MODELO_CONTEO',str(ROOT/'modelos'/'yolov8n.pt')))
 if not peso.is_file():raise RuntimeError('FALTA_MODELO_COCO_LOCAL:'+str(peso))
 with LOCK:
  if _modelo is None:_modelo=YOLO(str(peso))
  frame=capturar()
  crop=recortar(frame,'COLA','0.0,0.0,0.45,1.0')
  if crop.size==0:raise RuntimeError('ROI_COLA_VACIA')
  res=_modelo.predict(source=crop,verbose=False,conf=0.35,device='cpu',imgsz=320)[0]
  clases=[int(x) for x in res.boxes.cls.tolist()]
  # COCO car=2 bus=5 truck=7
  return sum(x in (2,5,7) for x in clases)
