PORTUS - Retenciones / Resolución física v0.8
=============================================

Incluye:
- PORTUS_Fase2_v06_Retenciones.ino
- app_portus.py (Web v0.5.3)
- templates/terminal_retenciones.html
- requirements_web.txt

Qué agrega
----------
1. TERMINAL -> Retenciones muestra Aclarar, Corregir y Rechazar cuando el rol
   está facultado.
2. La web envía AgujaLiberar por MQTT y espera el ACK/NACK real del Arduino.
3. SQLite solo se modifica después de recibir ACK. Si hay NACK, la retención
   sigue ACTIVA y se registra AL14.
4. AgujaLiberar agrega un tercer estado físico del servo desviador:
      RUTA_NORMAL   = 90
      RUTA_RETENIDA = 180
      RUTA_LIBERAR  = 0
5. Al liberar, el Arduino rechaza el comando si:
   - todavía hay un vehículo en tránsito hacia el parqueo,
   - ya hay una liberación en curso,
   - no hay vehículo detectado en el parqueo,
   - el turno no está retenido,
   - los parámetros son inválidos.
6. El Arduino publica EVT AGUJA durante la liberación y cuando vuelve a recta.
7. Reconciliación mínima: si el Mega se reinicia al cargar este firmware pero
   SQLite conserva un turno Retenido, AgujaLiberar recibe desde el servidor los
   datos necesarios para reconstruir el cache operativo del turno antes de
   liberarlo. Esto permite conservar el T2 actual sin repetir la prueba.
8. Corregir actualiza el peso declarado, registra historial y notifica al
   transportista. En el modelo actual el manifiesto guarda el peso del
   contenedor, mientras HX711 mide el conjunto camión+carga, por lo que se
   calcula peso_contenedor = peso_medido - tara únicamente en una estación donde
   el vehículo debe ir cargado.

IMPORTANTE PARA EL T2 ACTUAL
----------------------------
T2 / CAM-06 / C3 está retenido porque el camión pasó SIN contenedor. Por eso
Corregir no es una resolución válida para este caso: peso_medido - tara sería
cero o negativo. Para esta prueba use Rechazar con un motivo como:
"Vehículo ingresó sin contenedor".

No borre T2, no borre portus.db y no ejecute seeds.

Instalación recomendada
-----------------------
A) En el PC, extraiga este ZIP y cargue al Mega:
   PORTUS_Fase2_v06_Retenciones.ino

B) Copie el ZIP a la Raspberry y, en ~/portus, haga respaldo:
   cp portus.db portus_pre_retenciones_v08.db
   cp app_portus.py app_portus_pre_retenciones_v08.py
   cp templates/terminal_retenciones.html templates/terminal_retenciones_pre_v08.html

C) Descomprima sobre ~/portus:
   unzip -o PORTUS_Retenciones_Resolucion_v08.zip

D) El mismo entorno virtual ya utilizado por bridge_portus.py contiene paho-mqtt.
   Si fuese necesario:
   pip install -r requirements_web.txt

E) Reinicie bridge_portus.py y app_portus.py. En el bridge debe aparecer:
   Protocolo Fase 2 PORTUS v0.6 listo: GARITA + PESAJE + RETENCIONES + AgujaLiberar + CRC + ACK/NACK.

Prueba con el T2 actual
-----------------------
1. Mantenga CAM-06 físicamente en el área de retenidos.
2. Abra TERMINAL -> Retenciones.
3. En R1/T2 elija Rechazar.
4. Motivo sugerido: Vehículo ingresó sin contenedor.
5. La web debe confirmar AgujaLiberar aceptado.
6. El bridge debe mostrar CMD AGUJALIBERAR y ACK ACEPTADO.
7. El servo desviador debe ir a RUTA_LIBERAR (0 grados).
8. Retire físicamente CAM-06 del ramal. Al quedar libre el sensor de retenidos,
   el servo vuelve a RUTA_NORMAL (90 grados).
9. La web debe mostrar R1 RESUELTA / RECHAZAR, T2 Anulado y Plaza 1 LIBRE.

Para probar Aclarar o Corregir posteriormente conviene crear otra retención con
un camión que sí lleve el contenedor.
