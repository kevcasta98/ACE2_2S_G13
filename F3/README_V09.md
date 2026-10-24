# PORTUS — Integración incremental v0.9 (22/10/2026)

Paquete completo de los archivos de código **disponibles**: Arduino Mega + Raspberry Pi (Flask, MQTT, SQLite, servicios, mensajería y plantillas). Se parte del ZIP funcional del 20/10/2026; no hay base de datos ni credenciales reales dentro del archivo.

## Qué trae esta actualización

Se mantienen los módulos documentales NAVIERA, AGENTE y AUTORIDAD, citas de 15 minutos, mensajería transportista, GARITA por RFID, pesaje HX711, retenciones y resolución remota con AgujaLiberar (base v0.8). Se agregan:

- TERMINAL → Operación: datos observados, estado del enlace, plazas y turnos, suscripción MQTT vía SSE y actualización de respaldo; controles seguros **CerrarTalanquera** y **AbrirPuertaSalida** (el Mega verifica interlocks y responde ACK/NACK).
- TERMINAL → Turnos: búsqueda, estados e historial de eventos físicos (sin inventar eventos faltantes).
- TERMINAL → Alarmas: consulta, filtros y reconocimiento por usuario; watchdog AL01 cuando se pierden 3 latidos después de haber tenido enlace.
- TERMINAL → Patio: inventario de SQLite con indicador de confirmación física; **no modifica posiciones por estimaciones**.
- TERMINAL → Grúa: visualizador de eventos reales y controles deshabilitados hasta disponer del firmware de grúa.
- TERMINAL → Reportes: métricas reales consultables por fecha y CSV. Lo no instrumentado se muestra N/D.
- Firmware opcional `arduino/PORTUS_Fase2_v07_Supervision_Operacion.ino`: agrega eventos `TRANSFERENCIA INICIO/FIN` y `SALIDA AUTORIZADA/TIEMPO_AGOTADO/COMPLETA`; `AbrirPuertaSalida` remoto con interlocks. **No modifica el control de grúa.**
- `operacion_portus.py` sincroniza EnRuta→EnTransferencia→EnPesajeSalida al recibir eventos del controlador; marca `Cerrado` solo tras sensor físico de salida y si el turno estaba EnSalida. Respeta turnos Anulados.
- Idempotencia de eventos de pesaje/operación; un evento repetido no vuelve a retener un turno ya resuelto ni reinicia otro estado.

## Importante: alcance real, no simulado

**ESTO NO ES TODAVÍA LA FASE 2 COMPLETA PARA EVALUACIÓN FINAL.** Aún falta integrar/probar las funciones que no aparecen en el firmware base: control físico completo de grúa/patio, trece comandos remotos y sus interlocks, RT04 fuera de ventana hasta parqueo, RT05/RT06 físicos, alarma del catálogo completa, inventario físico por movimiento, cuatro métricas dependientes de grúa/fila, recuperación/reconciliación integral al caer el servidor. Tampoco se ha hecho prueba sobre el Mega físico de este nuevo firmware; la integración real debe comprobarse. Los códigos anteriores tampoco se han revalidado físicamente tras la actualización.

Si el Mega contiene todavía la v0.6, **la cadena anterior garita/pesaje/retención sigue siendo la que conoces**. Los nuevos eventos TRANSFERENCIA y SALIDA solo se reciben después de cargar el firmware v0.9 (v07 en el nombre del archivo).

## 1. Requisitos Raspberry Pi

Raspberry Pi OS 64 bits, Python 3, Arduino Mega por USB, Mosquitto, SQLite. La carpeta de trabajo es `~/portus`. La IP `192.168.1.83` fue utilizada antes; en otra red puede cambiar.

Comprobar:

```bash
ls -l /dev/ttyACM*
sudo systemctl status mosquitto --no-pager
```

Si Mosquitto no está activo:

```bash
sudo systemctl start mosquitto
```

En una instalación nueva, coloca manualmente `raspberry/` en `~/portus`, crea un venv y dependencias, inicializa DB, registra usuarios/camiones solo si realmente se trata de un entorno NUEVO:

```bash
cd ~/portus
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python inicializar_db.py
```

`seed_usuarios.py` y `seed_catalogo.py` NO deben ejecutarse sobre bases reales. Nunca se incluye `portus.db` ni se restaura desde un ZIP sin verificar.

## 2. Actualizar la instalación existente (recomendado)

**No cargas el firmware mientras existan vehículos/turnos activos**: reiniciar el Mega pierde su caché RAM. Termina físicamente las operaciones y comprueba el estado antes de programar.

Desde tu PC Linux, descomprime o transfiere el ZIP. Ejemplo:

```bash
scp PORTUS_Integracion_v09_2026-10-22.zip portus@192.168.1.83:/home/portus/
```

En la Pi, detén las cinco terminales actuales con `Ctrl+C` (bridge, persistencia, garita, pesaje y web) y, si está activo, el simulador/bot. Si las habías iniciado con el script v0.9, usa `./detener_portus.sh`. El instalador rechaza actualizar archivos mientras detecta procesos PORTUS.

```bash
cd ~
unzip -q PORTUS_Integracion_v09_2026-10-22.zip -d portus_v09_paquete
cd ~/portus_v09_paquete/PORTUS_Integracion_v09
bash INSTALAR_ACTUALIZACION.sh
```

El instalador:
1. hace un respaldo consistente de `portus.db` y copia la web anterior a un directorio de respaldo;
2. instala los .py, templates y scripts, sin borrar ninguna cuenta, manifiesto, cita, turno, retención o peso;
3. aplica migraciones compatibles (`eventos_aplicados`) y compila sintácticamente Python;
4. muestra una advertencia si quedan turnos activos y NO toca Arduino.

## 3. Cargar firmware nuevo

Cuando el Mega esté **sin operaciones activas**, usa Arduino IDE en Windows/Linux. Selecciona `Arduino Mega or Mega 2560` y abre:

```text
arduino/PORTUS_Fase2_v07_Supervision_Operacion.ino
```

El firmware previo también se incluye para recuperación:

```text
arduino/PORTUS_Fase2_v06_Retenciones.ino
```

Conserva: RFID SS53/RST49, HX711 DT32/SCK33 y factor 706.0, servos D3/D5/D6, IR 28/29/30/31, LCD 0x27/0x23. Se mantiene **un solo HX711**. No cambies pines de grúa ni cableado. Necesita las mismas bibliotecas Arduino de antes: MFRC522, HX711 y LiquidCrystal_I2C, además de Servo/SPI/Wire. **Compila primero**: aquí se verificó sintaxis Python, pero no se dispone de Arduino IDE ni de la maqueta para validación de compilación o hardware.

Conecta el Mega a la Pi; verifica `/dev/ttyACM0`. Solo el **bridge** debe abrir ese puerto serie (no abras simultáneamente el monitor serial del IDE).

## 4. Arranque completo

Tras la actualización:

```bash
cd ~/portus
./iniciar_portus.sh
./estado_portus.sh
```

Este script levanta (o evita duplicar si ya corren) los procesos:

```text
bridge_portus.py          USB/Serial ⇄ MQTT
persistencia_portus.py    MQTT → SQLite + AL01
 garita_portus.py         RFID → validar → autorizar
 pesaje_portus.py         EVT PESAJE → turno/retención
 operacion_portus.py      EVT TRANSFERENCIA/SALIDA → estados
 app_portus.py            Web Flask TCP 5000
 mensajeria_portus.py     Solo si está configurado PORTUS_TELEGRAM_TOKEN
```

Para el simulador de mensajería en otra terminal:

```bash
cd ~/portus
source venv/bin/activate
python simular_transportista.py
```

Web en la misma red:

```text
http://IP_DE_LA_RASPBERRY:5000
```

El script crea una clave secreta de Flask en `.run/secret_key` (modo privado) si no se estableció `PORTUS_SECRET_KEY`. Para Telegram crea `.env` con `PORTUS_TELEGRAM_TOKEN=...` sin incluirlo en el ZIP; usa permisos `chmod 600 .env`. El bot de Telegram no es necesario para el simulador.

Ver logs y detener:

```bash
tail -f ~/portus/logs/bridge.log
tail -f ~/portus/logs/garita.log
tail -f ~/portus/logs/pesaje.log
tail -f ~/portus/logs/operacion.log
cd ~/portus && ./detener_portus.sh
```

Si el puerto 5000 ya está ocupado, usa `ss -ltnp | grep :5000` y detén la instancia anterior. No detengas procesos ajenos.

## 5. Verificación funcional recomendada

Sin vehículos en zonas de riesgo, comprueba que `bridge_portus.py` reciba `ESTADO` cada cinco segundos. En la web entra como TERMINAL → Operación y verifica ENLACE CONECTADO, plazas, turnos y registros recientes. Revisa Turnos y Alarmas. Asegúrate de que al desconectar el enlace surja AL01 después de tres periodos y, al reponerlo, se marque cerrada; **no pruebes desconexión con un camión debajo de talanquera ni aguja**.

Para ensayar la cadena que **sí** está integrada de extremo a extremo: NAVIERA crea manifiesto → AGENTE presenta declaración y solicita levante → AUTORIDAD lo otorga con canal VERDE → TRANSPORTISTA solicita cita → RFID → paso físico bajo talanquera → pesaje de entrada aprobado → EnRuta. El operador puede observarlo desde las pestañas Operación y Turnos.

El código de Fase 1 todavía contempla los comandos locales `T/F` para transferencia, **pero el bridge ocupa en exclusividad el puerto USB** y no existe aún un comando remoto oficialmente integrado para iniciar/finalizar esos movimientos. No intentes abrir el Monitor Serial de Arduino simultáneamente con `bridge_portus.py`, ni des por realizado un trabajo de grúa por pulsar `F`. La sincronización final de estados de transferencia/salida entregada en esta versión está **preparada para consumir eventos reales**, pero la operación física continua hasta Cerrado requiere integrar el firmware de grúa y el mecanismo de control de transferencia. No declaramos que ese happy path completo ya esté probado.

Si el resultado del pesaje produce retención, NO avances hasta resolver con el rol correspondiente; las operaciones retenidas no deben liberarse manualmente en SQLite. La parte de RT01/RT03 reutiliza el firmware probado; la resolución AgujaLiberar por web se entregó en v0.8 pero debe verificarse nuevamente tras actualizar.

## 6. Estado físico y límites

- Ninguna ruta web mueve la grúa sin hardware integrado.
- El dashboard distingue la telemetría real de datos no disponibles.
- Las métricas no instrumentadas se muestran N/D.
- Todos los movimientos remotos implementados requieren confirmación del controlador, y `AbrirPuertaSalida` se rechaza si el IR está ocupado, la salida está atendiendo otro vehículo o no hay turno listo.
- La arquitectura actual no sustituye una prueba física de interlocks, pérdida de enlace y reconciliación para la entrega final.
