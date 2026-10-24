DOCUMENTO HISTORICO v0.8: Para la versión nueva usar README_V09.md y MANIFIESTO_VERSIONES.txt

PORTUS - PAQUETE FUNCIONAL ACTUAL
=================================
Fecha de consolidación: 2026-10-20

Este ZIP reúne las versiones que actualmente se han probado de forma integrada:
- Arduino Mega: GARITA + RFID + talanquera + pesaje dinámico + retenciones + AgujaLiberar + CRC + ACK/NACK.
- Raspberry Pi: bridge Serial<->MQTT, persistencia SQLite, validación de garita, servicio de pesaje, web Flask, cadena documental, citas, mensajería y retenciones.

IMPORTANTE
----------
1. NO se incluye portus.db para no sobrescribir la base de datos real que ya tienes en ~/portus.
2. Si ya tienes ~/portus funcionando, copia estos archivos SOBRE ese directorio, pero conserva tu portus.db.
3. Antes de reemplazar archivos, haz respaldo:

   cd ~/portus
   cp portus.db portus_respaldo_antes_paquete.db
   cp app_portus.py app_portus_respaldo.py 2>/dev/null || true

4. Firmware oficial actual del Mega:

   arduino/PORTUS_Fase2_v06_Retenciones.ino

   Esta versión reemplaza a v05_PesajeServidor porque agrega AgujaLiberar y resolución física de retenciones.

ESTRUCTURA
----------
arduino/
  PORTUS_Fase2_v06_Retenciones.ino

raspberry/
  app_portus.py
  bridge_portus.py
  protocolo_portus.py
  persistencia_portus.py
  garita_portus.py
  pesaje_portus.py
  db_portus.py
  inicializar_db.py
  citas_portus.py
  mensajeria_portus.py
  simular_transportista.py
  consultar_db.py
  verificar_garita.py
  verificar_pesaje.py
  verificar_citas.py
  reiniciar_prueba_garita.py
  registrar_camiones_portus.py
  seed_usuarios.py
  seed_catalogo.py
  probar_mqtt_portus.py
  probar_ping_portus.py
  requirements.txt
  templates/

docs/
  Notas técnicas de Garita, Pesaje y Retenciones.

============================================================
A. INSTALAR / ACTUALIZAR EN LA RASPBERRY
============================================================

Desde el PC, copia el contenido de la carpeta raspberry al proyecto de la Pi.
Ejemplo si extraes el ZIP en Descargas:

  scp -r PORTUS_Proyecto_Funcional_Actual_2026-10-20/raspberry/* \
      portus@192.168.1.83:/home/portus/portus/

Para copiar también .env.example, si lo deseas:

  scp PORTUS_Proyecto_Funcional_Actual_2026-10-20/raspberry/.env.example \
      portus@192.168.1.83:/home/portus/portus/

En Raspberry:

  cd ~/portus
  source venv/bin/activate
  pip install -r requirements.txt

NO ejecutes seed_usuarios.py, seed_catalogo.py ni inicializar_db.py sobre tu base de datos actual salvo que estés creando una instalación desde cero.

============================================================
B. CARGAR EL FIRMWARE AL ARDUINO MEGA
============================================================

Carga con Arduino IDE:

  arduino/PORTUS_Fase2_v06_Retenciones.ino

Placa:
  Arduino Mega or Mega 2560

Después conecta el Mega por USB a la Raspberry y verifica:

  ls -l /dev/ttyACM*

Normalmente debe aparecer:

  /dev/ttyACM0

Hardware principal actual:
  RC522 SS  -> 53
  RC522 RST -> 49
  HX711 DT  -> 32
  HX711 SCK -> 33
  Servo entrada     -> 3
  Servo desviador   -> 5
  Servo salida      -> 6
  IR entrada        -> 28
  IR salida         -> 29
  IR espera         -> 30
  IR retenidos      -> 31
  LCD garita        -> 0x27
  LCD salida        -> 0x23

============================================================
C. MOSQUITTO
============================================================

Comprobar:

  sudo systemctl status mosquitto --no-pager

Si no está activo:

  sudo systemctl start mosquitto

Opcional, habilitar al arrancar:

  sudo systemctl enable mosquitto

============================================================
D. LEVANTAR PORTUS COMPLETO
============================================================

Abre TERMINALES SEPARADAS. En todas:

  cd ~/portus
  source venv/bin/activate

TERMINAL 1 - Bridge Serial <-> MQTT
----------------------------------

  python bridge_portus.py

Debe indicar aproximadamente:
  Serial: /dev/ttyACM0 @ 9600
  MQTT: localhost:1883
  Bridge activo
  Protocolo Fase 2 PORTUS v0.6 ...

Además debe recibir EVT ESTADO aproximadamente cada 5 segundos.

TERMINAL 2 - Persistencia MQTT -> SQLite
----------------------------------------

  python persistencia_portus.py

Debe suscribirse a:
  portus/evt/#
  portus/cmd/respuesta

TERMINAL 3 - Servicio de GARITA
-------------------------------

  python garita_portus.py

Valida RFID contra SQLite, manifiesto, levante y cita, y solicita AbrirTalanquera al Mega.

TERMINAL 4 - Servicio de PESAJE
-------------------------------

  python pesaje_portus.py

Procesa EVT PESAJE, actualiza turnos y crea RT01/RT03 cuando corresponda.

TERMINAL 5 - Web Flask
----------------------

Primero comprobar si ya está levantada:

  ss -ltnp | grep :5000

Si no hay proceso:

  python app_portus.py

Desde otro equipo de la red:

  http://IP_DE_LA_RASPBERRY:5000

En la instalación usada durante las pruebas la Raspberry estuvo accesible en 192.168.1.83, pero la IP puede cambiar.

============================================================
E. SIMULADOR DEL TRANSPORTISTA
============================================================

En otra terminal:

  cd ~/portus
  source venv/bin/activate
  python simular_transportista.py

Comandos principales:
  /inicio
  /vincular CODIGO
  /cita
  /miscitas
  /estado CONTENEDOR
  /misturnos
  /ayuda

============================================================
F. VERIFICADORES / DIAGNÓSTICO
============================================================

Garita:

  python verificar_garita.py

Pesaje / retenciones / plazas:

  python verificar_pesaje.py

Citas:

  python verificar_citas.py

Base de datos:

  python consultar_db.py

Prueba MQTT:

  python probar_mqtt_portus.py

Prueba serial PING (detén bridge_portus.py antes, porque ambos no deben abrir /dev/ttyACM0 a la vez):

  python probar_ping_portus.py

============================================================
G. CREDENCIALES DE DEMOSTRACIÓN
============================================================

TERMINAL
  usuario: terminal
  contraseña: Terminal2026!

AGENTE
  usuario: agente
  contraseña: Agente2026!

AUTORIDAD
  usuario: autoridad
  contraseña: Autoridad2026!

NAVIERA 1
  usuario: naviera1
  contraseña: Naviera12026!

NAVIERA 2
  usuario: naviera2
  contraseña: Naviera22026!

TRANSPORTISTA no usa la web; usa mensajería/simulador.

============================================================
H. CAMIONES / RFID USADOS
============================================================

CAM-01 -> 322C4507
CAM-02 -> EA225305
CAM-03 -> 409A9558
CAM-04 -> E158F3B0
CAM-05 -> E116F9B0
CAM-06 -> 59CF9229

============================================================
I. FLUJO ACTUAL QUE YA SE HA PROBADO
============================================================

NAVIERA
  -> manifiesto
AGENTE
  -> declaración
  -> solicitud de levante
AUTORIDAD
  -> levante VERDE/ROJO
TRANSPORTISTA
  -> cita
GARITA
  -> RFID
  -> validación servidor
  -> AbrirTalanquera
  -> ACK/NACK del Mega
  -> paso físico / cierre de talanquera
PESAJE ENTRADA
  -> meseta HX711
  -> EVT PESAJE
  -> dentro de tolerancia: EnRuta
  -> fuera de tolerancia: RT01 + parqueo
  -> canal rojo: RT03 después del pesaje
RETENCIONES
  -> vista TERMINAL
  -> Aclarar / Corregir / Rechazar
  -> AgujaLiberar
  -> ACK/NACK
  -> actualización SQLite después de ACK

============================================================
J. COSAS QUE TODAVÍA NO DEBEN CONSIDERARSE CERRADAS
============================================================

Este paquete refleja el punto actual del desarrollo. Aún quedan por completar/probar de extremo a extremo:
- Integración definitiva de transferencia y grúa con servidor.
- Pesaje de salida integrado a toda la cadena.
- Puerta/salida y cierre completo del turno.
- RT04 fuera de ventana con flujo completo de parqueo.
- Todas las alarmas y sinóptico final.
- Métricas/reportes finales.
- Prueba completa de modo degradado/reconciliación.

No confundir los comandos manuales de depuración del firmware con el flujo final de evaluación.

============================================================
K. SI PORTUS NO ARRANCA
============================================================

1. Mega no aparece:
   ls -l /dev/ttyACM*

2. Permisos serial:
   groups
   sudo usermod -aG dialout portus
   (cerrar sesión y volver a entrar)

3. Puerto 5000 ocupado:
   ss -ltnp | grep :5000

4. Mosquitto:
   sudo systemctl status mosquitto

5. Solo UN proceso debe abrir /dev/ttyACM0. Normalmente ese proceso es bridge_portus.py.

6. Si se reinicia el Mega, vuelve a revisar heartbeat en bridge_portus.py antes de mover un camión.
