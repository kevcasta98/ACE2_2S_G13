PORTUS - Fase 2 - Garita controlada por servidor v0.6
======================================================

OBJETIVO DE ESTA VERSION
------------------------
Conectar la cadena documental/citas ya implementada con la garita fisica.

Flujo implementado:
RFID -> Mega -> EVT GARITA -> MQTT -> garita_portus.py -> SQLite
     -> AbrirTalanquera/CerrarTalanquera -> bridge -> Mega -> ACK/NACK

Cambios importantes:
- El Mega YA NO autoriza el ingreso usando los manifiestos precargados de Fase 1.
- La tabla de manifiestos del Mega pasa a ser un cache operativo de seis slots,
  uno por camion, llenado unicamente por la Raspberry al autorizar un ingreso.
- La Raspberry valida camion, turno activo, manifiesto, levante y cita/ventana.
- El Mega sigue validando los enclavamientos fisicos antes de abrir.
- Si la Raspberry no responde en 8 s, el nuevo ingreso se rechaza en modo degradado.
- Una operacion que ya ingreso conserva en el Mega la informacion recibida y puede
  seguir con la logica local existente.
- Al confirmar fisicamente el cruce de la talanquera, la Raspberry crea el turno
  en SQLite, marca la cita CUMPLIDA y el manifiesto EN_CURSO.

ARCHIVOS
--------
PORTUS_Fase2_v04_GaritaServidor.ino  Firmware para Arduino Mega.
garita_portus.py                     Servicio MQTT/SQLite de validacion de acceso.
verificar_garita.py                  Diagnostico previo a la prueba fisica.

NO SE MODIFICA
--------------
- La implementacion fisica de la grua.
- El bridge Serial <-> MQTT existente.
- La web v0.5.1.
- La base SQLite ni su esquema.

LIMITES INTENCIONALES DE ESTE BLOQUE
------------------------------------
Esta v0.6 valida primero el happy path de garita (canal VERDE).
La retencion RT04 por llegada fuera de ventana y el desvio RT03 por canal ROJO
se integraran en el siguiente bloque, junto con los eventos de pesaje.
Por seguridad, en v0.6 un camion fuera de ventana permanece con la talanquera cerrada.

PRUEBA RECOMENDADA
------------------
1. Tener una cita PROGRAMADA para C1, vehiculo CAM-04, canal VERDE.
2. Reprogramarla a la siguiente franja y esperar a estar dentro de la ventana.
3. Ejecutar en Raspberry:
     source ~/portus/venv/bin/activate
     python verificar_garita.py
4. Ejecutar bridge_portus.py y persistencia_portus.py como hasta ahora.
5. Ejecutar en otra terminal:
     python garita_portus.py
6. Acercar RFID de CAM-04.
7. Resultado esperado:
   - Mega publica EVT GARITA/RFID.
   - garita_portus.py encuentra la cita valida.
   - publica AbrirTalanquera.
   - Mega valida interlocks y responde ACK.
   - servo de entrada abre.

Si se deja pasar completamente el camion:
- Mega publica accion=INGRESO;resultado=COMPLETO.
- SQLite crea Tn en estado EnPesajeEntrada.
- cita pasa a CUMPLIDA.
- manifiesto pasa a EN_CURSO.

IMPORTANTE
----------
Para probar solamente la autorizacion fisica sin iniciar el resto del flujo, deje
que la talanquera abra pero NO haga cruzar completamente el camion. A los 15 s el
Mega cerrara la entrada y no se creara turno en SQLite.
