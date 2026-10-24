PORTUS - Fase 2 - Integracion PESAJE v0.7
=========================================

Contenido:
- PORTUS_Fase2_v05_PesajeServidor.ino
- pesaje_portus.py
- verificar_pesaje.py
- reiniciar_prueba_garita.py

Objetivo de esta version
------------------------
1. Conserva la garita validada por Raspberry de v0.6.
2. El Arduino publica EVT PESAJE estructurado al obtener una meseta.
3. El bridge existente publica el evento en portus/evt/pesaje.
4. persistencia_portus.py almacena el pesaje en SQLite.
5. pesaje_portus.py actualiza el estado del turno:
   - entrada aprobada + canal verde -> EnRuta
   - peso fuera de tolerancia al ingreso -> RT01 / Retenido
   - canal rojo despues del pesaje de entrada -> RT03 / Retenido
   - salida aprobada -> EnSalida
   - peso fuera de tolerancia a la salida -> RT02 / Retenido
6. Para una retencion, el servidor asigna la plaza logica libre de menor numero.
7. El Mega conserva la reaccion fisica inmediata de la aguja con la informacion cacheada,
   de modo que un turno ya ingresado pueda continuar de forma segura si se pierde el enlace.

IMPORTANTE SOBRE LA PRUEBA ACTUAL T1
------------------------------------
Si T1 fue creado con v0.6 y aun esta en EnPesajeEntrada SIN haber cruzado la bascula,
antes de cargar el firmware v0.7 ejecuta:

  python reiniciar_prueba_garita.py T1

El script se niega a modificar el turno si ya tiene pesajes o retenciones.
Despues solicita una cita nueva para C1 y repite la entrada con CAM-04.

Servicios para la prueba
------------------------
Terminal 1:
  python bridge_portus.py

Terminal 2:
  python persistencia_portus.py

Terminal 3:
  python garita_portus.py

Terminal 4:
  python pesaje_portus.py

Verificacion:
  python verificar_pesaje.py

Prueba verde esperada
---------------------
CAM-04 / C1 / M1002 / canal VERDE
Al cruzar la bascula con peso dentro de tolerancia:
- bridge: EVT PESAJE
- pesaje_portus.py: ENTRADA APROBADA -> EnRuta
- verificar_pesaje.py: T? en EnRuta y pesaje persistido
- la aguja queda en ruta normal

Prueba roja posterior
---------------------
CAM-05 / C2 / M1003 / canal ROJO
Si el peso esta dentro de tolerancia:
- Arduino: canal rojo -> ruta retenidos
- MQTT: resultado CANAL_ROJO
- pesaje_portus.py: crea RT03
- asigna la plaza logica libre de menor numero
- turno -> Retenido
- resolver corresponde a AUTORIDAD
