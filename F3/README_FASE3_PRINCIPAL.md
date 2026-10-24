# PORTUS — Fase 3, extensión del sistema principal (v1.0)

**Base:** PORTUS v0.9 (22 octubre 2026). Incluye firmware ESP32 meteorológico. **NO** se reemplaza firmware del segundo Arduino de grúa; **NO** se incluye `portus.db`, claves ni fotografías personales.

## 1. Alcance real, sin simular dispositivos

Se conservan la web F2, MQTT/serial, citas, RFID, pesaje, controles físicos existentes, retenciones, auditoría y mensajería. La actualización agrega:

- Firmware del Mega principal: salida **D34** para módulo de potencia de la iluminación, **D35** para LED ámbar con resistencia, control no bloqueante; fail-safe de luz encendida cuando no llegan comandos válidos durante 15 s; `GaritaResultado`, `IluminacionEncender`, `IluminacionApagar`, `BalizaClima`, ACK/NACK; espera de verificación configurable de 5 a 30 s y acceso manual con caducidad. No se modifica la lógica del segundo Arduino de grúa.
- Raspberry: recepción MQTT de estación (`portus/estacion/lectura`, `portus/estacion/estado`), reglas de lluvia e histéresis de iluminación, detección de pérdida de tres latidos, AL16–AL22, monitoreo y conteo con cámara real + modelo COCO local, OCR con Tesseract y detector de placas preentrenado opcional; ROI fija configurada si el detector no localiza placas. El sistema **nunca inventa detecciones**.
- Control de entrada: `RFID → captura/lectura → coincidencia de placa → consulta documental y cita → comando al Mega`. Si la placa falla, pasa a **confirmación manual** (no abre automáticamente). Placa de otro camión: **RT07**; placa restringida: **RT08**, ambas usan la retención física después del pesaje y ocupan plaza lógica.
- Web: pestañas **TERMINAL/Accesos**, **AUTORIDAD/Placas restringidas**, **TERMINAL/Parámetros F3** y panel ampliado de Operación; rol/permiso comprobado en backend, catálogo de vehículos, auditoría y fotos del historial. `/clima` y envío de foto por Telegram si se configura el bot.

**Límites que NO podemos resolver sin la maqueta o el proyecto del compañero:** el Arduino de grúa es un segundo dispositivo y el paquete v0.9 no contiene su protocolo/firmware; los comandos de clima se publican en **`portus/cmd/grua/solicitud`**, que deberá ser recibido y confirmado por una integración separada. Solo después de un **ACK real en `portus/cmd/grua/respuesta`** se actualiza la grúa como suspendida y se controla la baliza. No se anuncia como funcionando sin ese enlace. La grúa debe completar/depositar su carga antes de suspenderse. El Mega principal **rechaza** `GruaSuspender`/`GruaReanudar` si llegan por su puerto, porque la grúa está en otro Arduino.

**Restricción de LCD:** en la maqueta histórica la pantalla de garita está declarada como **16×2**; el enunciado de F3 menciona líneas 3 y 4 y cadenas de más de 16 caracteres. El firmware muestra los textos posibles en dos líneas y trunca los demás. Para reproducir *todos* los textos literales sin abreviaciones se requerirá cambiar/adaptar la pantalla física o implementar paginación validada.

**Raspberry Pi 3B+ de 1 GB:** YOLO + OCR pueden ser demasiado costosos para este hardware. El enunciado recomienda Pi 4 o superior. Instalar modelos compatibles ARM64 y medir tiempos. Si falla la cámara/modelo, el acceso queda manual y se genera AL18, nunca hay autorización silenciosa de un único factor. Eso permite probar el modo degradado, pero **no** valida los escenarios de reconocimiento de la rúbrica mientras falte el modelo real.

## 2. Conexiones NUEVAS solamente — Mega principal

Mantener todos los pines existentes: RC522 SS53/RST49, HX711 DT32/SCK33, servos 3/5/6, sensores 28/29/30/31, semáforos 22–27, LCD 0x27/0x23. No agregar otro HX711.

- **D34:** señal de control a módulo MOSFET/relé (nivel HIGH = luces encendidas). Conectar *la tira LED* a **fuente externa apropiada**, con GND común cuando el driver requiera referencia; no alimentar la tira desde el pin Mega. Verificar polaridad del módulo, no conectar directamente cargas de corriente significativa al pin.
- **D35:** LED ámbar de baliza con resistencia limitadora y driver si la corriente lo requiere. Parpadea a 1 Hz **solo tras confirmación de suspensión climática desde la grúa**.
- **USB del Mega de garita:** puerto estable `/dev/serial/by-id/...` apuntando al Mega principal. La grúa permanece por su propio USB/puerto/servicio. **No usar el mismo puerto para ambos**.
- **Cámara:** USB al Raspberry (`/dev/video0`, verificar). Encuadre fijo que abarque entrada y zona de espera. Si usa CSI, adaptar captura a `libcamera`/V4L2. Placas físicas con formato `C123ABC` negro sobre blanco, únicas para los seis vehículos. Los IDs operativos `CAM-04` **no** son las placas impresas.
- **Estación:** ESP32, WiFi/MQTT independiente, sin cable al Mega; el firmware ESP32 es trabajo separado.

## 3. Actualizar una Raspberry ya en operación

**No actualizar firmware con camiones dentro de la terminal.** Completar o reconciliar turnos pendientes y conservar posición del patio. Detener los servicios PORTUS existentes, especialmente la web, garita y bridge.

En PC Windows con PowerShell (sustituir IP):

```powershell
scp .\PORTUS_Fase3_Principal_v10.zip portus@192.168.1.83:/home/portus/
ssh portus@192.168.1.83
```

En Raspberry:

```bash
cd ~
unzip PORTUS_Fase3_Principal_v10.zip -d portus_f3_entrega
cd ~/portus_f3_entrega/PORTUS_Fase3_Principal_v10
bash INSTALAR_ACTUALIZACION.sh
```

El instalador verifica que **ningún proceso PORTUS siga corriendo**, hace backup consistente SQLite en `~/portus/respaldo_antes_fase3_*`, copia código y plantillas (sin `.env` ni `portus.db`) y aplica migraciones **aditivas** incluyendo RT07/RT08. No reinicializar seeds en una instalación real.

**Instalar dependencias** (con la virtualenv existente):

```bash
cd ~/portus
source venv/bin/activate
pip install -r requirements.txt
sudo apt-get update
sudo apt-get install -y tesseract-ocr v4l-utils
pip install opencv-python-headless pytesseract
# Solo si la distribución de Raspberry soporta PyTorch/Ultralytics:
pip install ultralytics
```

En Raspberry Pi OS puede resultar más conveniente `sudo apt install python3-opencv` si el wheel de pip falla; hay que instalarlo en el entorno Python que realmente ejecuta PORTUS, o crear el venv con `--system-site-packages`. **No asumir** que `ultralytics` se instalará en Pi 3B+. Los pesos de YOLO no están incluidos; instalar localmente el preentrenado COCO ligero, por ejemplo `modelos/yolov8n.pt`, y un detector especializado de placas compatible si se dispone de él. Registrar fuente, versión y licencia de esos pesos. Tesseract tiene modelo OCR preentrenado con la instalación del sistema.

Crear/editar `.env` **sin borrar las claves existentes**:

```bash
cd ~/portus
cp -n .env.example .env
nano .env
```

Con **dos Arduinos** primero:

```bash
ls -l /dev/serial/by-id/
udevadm info -q property -n /dev/ttyACM0 | grep -E 'ID_SERIAL|ID_PATH'
udevadm info -q property -n /dev/ttyACM1 | grep -E 'ID_SERIAL|ID_PATH'
```

Definir `PORTUS_SERIAL_PORT=/dev/serial/by-id/<IDENTIFICADOR_DEL_MEGA_GARITA>` en `.env`. Si hay varios puertos y no se configuró explícitamente, el script de inicio **se negará a elegir arbitrariamente**. Si ambos Arduinos tienen IDs USB idénticos, usar reglas udev por ruta física (`ID_PATH`) y **no intercambiar el cable de puertos**.

Configurar `PORTUS_CAMARA`, `PORTUS_ROI_PLACA` y `PORTUS_ROI_COLA` según imagen real. ROI `x,y,ancho,alto` escala 0–1. El modelo de conteo usa COCO clases **2, 5 y 7** (auto, autobús, camión). Captura de placas **solo por RFID/presencia**, no OCR en bucle; el conteo sí se programa periódicamente.

Comprobar antes de habilitar garita:

```bash
source ~/portus/venv/bin/activate
cd ~/portus
python verificar_fase3.py
python pruebas_fase3_offline.py
```

Cargar en el **Mega principal, con todos los vehículos fuera**:

`arduino/PORTUS_Fase3_v10_Principal.ino`

Usar Arduino IDE → placa Mega 2560. Las bibliotecas físicas son las mismas de v0.9 (`MFRC522`, `Servo`, `Wire`, `LiquidCrystal_I2C`, `HX711`). La compilación en Arduino IDE **no ha sido verificada aquí**: realizar Compile/Verify primero y no sobrescribir v0.9 hasta tener respaldo. Mantener intacto firmware de grúa.

Iniciar servicios:

```bash
sudo systemctl start mosquitto
cd ~/portus
./iniciar_portus.sh
./estado_portus.sh
tail -f logs/fase3.log
```

Web: `http://<IP_RASPBERRY>:5000`. Detener solo los procesos lanzados con el script: `./detener_portus.sh`.

## 4. Cómo ingresar las placas impresas

Cuenta `terminal` → **Accesos** → Catálogo. Cada `CAM-01…CAM-06` conservará su `rfid_uid` y código interno pero debe asociarse a una **placa nueva y única** en formato `C###AAA`. Introducir **la que realmente está impresa**, no asumir un código de ejemplo; motivo mínimo 10 caracteres. Registrar el lugar y tamaño de las placas para ROI.

Cuenta `autoridad` → **Placas restringidas** para alta y baja, siempre con motivo de 10 caracteres, auditado. RT08 tiene prioridad si la placa leída está restringida, incluso si coincide con el RFID válido.

## 5. Firmware y MQTT de la estación

El firmware está en `arduino/PORTUS_Fase3_Estacion_Climatologica.ino`. Usa DHT22, LDR y salida digital DO del comparador YL-83. Valores iniciales de cableado: DHT22 DATA en GPIO4, LDR en GPIO34 (ADC1) y lluvia DO en GPIO27. Deben coincidir con el montaje real. `LDR_DARK_ADC` y `LDR_BRIGHT_ADC` requieren calibración; `RAIN_LEVEL_WET` se invierte si el módulo entrega HIGH cuando está mojado. El código asume que la entrada analógica LDR produce un valor mayor en oscuridad. Instalar PubSubClient, ArduinoJson 7 y DHT sensor library de Adafruit en Arduino IDE.

Antes de compilar, configurar SSID/clave WiFi y la dirección del broker MQTT de la Raspberry en el encabezado del firmware. Puerto predeterminado: 1883. La estación usa NTP para la hora, intenta reconectar WiFi/MQTT y sigue leyendo sensores durante una caída de red. No es necesario cablearla al controlador Arduino.

Publica en `portus/estacion/lectura` el mismo sobre de F2:

```json
{"id":"lectura-real-001","timestamp":"2026-10-23T18:00:00-06:00","origin":"estacion","type":"LECTURA","data":{"temperatura":27.3,"humedad":70,"lluvia":false,"luz":62}}
```

Cada `SegundosLatidoEstacion` segundos publica `portus/estacion/estado` con `type: ESTADO`. La web publica cambios de intervalo en `portus/estacion/config`; el firmware los guarda en NVS y los conserva después de reiniciarse. El receptor valida las mediciones y guarda cada una en `fase3_clima_historial`; la tabla `fase3_estacion_climatologica` conserva la lectura más reciente por identificador de estación. El panel TERMINAL → Operación muestra los valores actuales y últimas lecturas, consultando la API cada dos segundos. **Estos JSON son ejemplos de protocolo; no se publicarán como pruebas de la evaluación**, que exige sensores reales.

Se usan `portus/vision/placa`, `portus/vision/cola`, `portus/vision/estado`, `portus/evt/iluminacion` y `portus/evt/clima`, además de los tópicos anteriores.

## 6. Reglas operativas y pruebas reales, en orden

1. **Preflight y fases previas:** comprobar Mosquitto, ambos USB, bridge, heartbeat, RX RFID, pesaje verde y RT01; sin forzar un estado físico con UPDATE de SQLite.
2. **Luz:** en TERMINAL → Operación seleccionar Encendido forzado y Apagado forzado, verificar físicamente el driver en D34 y ACK/`EVT ILUMINACION`. Automático: cubrir/descubrir el sensor real de estación, verificar umbrales (30/45 por defecto) sin parpadeo.
3. **Clima:** recibir lecturas reales de ESP32. Con lluvia se solicita `GruaSuspender` en **`portus/cmd/grua/solicitud`**, se registra AL17 y se notifica posible demora. **No avanzar** a prueba de baliza/suspensión hasta que el segundo Arduino reporte ACK tras terminar el movimiento. Con ACK la baliza D35 parpadea y el sinóptico confirma suspensión. Reanudar automáticamente tras 2 min sin lluvia (configurable); la baliza apaga solo tras ACK de reanudación.
4. **Falla de estación:** desconectar ESP32; tras 3 latidos faltantes esperar AL16, clima desconocido, luces encendidas y grúa conservando su estado previo (sin orden de suspensión por ausencia de estación).
5. **Cámara/OCR:** apuntar la cámara real y comprobar Tesseract/modelo instalado. Registrar placa impresa para cada UID. Presentar camión con documentación y cita; servidor pide luz/espera 1 s, toma foto, lee placa y verifica. El Mega recibe `GaritaResultado`, luego `AbrirTalanquera` únicamente tras autorización de F2.
6. **Placa equivocada:** usar RFID de un camión y placa física de otro; esperar `PLACA NO COINCIDE`, AL20; ingreso con canal físico hacia retención **RT07** después de pesaje, plaza libre. Resolver solo TERMINAL con Aclarar/Rechazar.
7. **Placa restringida:** AUTORIDAD marca una placa y luego presentar ese camión; AL21, RT08, plaza física tras pesaje; resuelve exclusivamente AUTORIDAD.
8. **Sin lectura / fallo cámara:** tapar placa o desconectar cámara: AL22 (sin OCR válido) o AL18 (sin cámara/modelo); talanquera cerrada hasta que TERMINAL vea la captura disponible y confirme/rechace en **Accesos**, dejando motivo de mínimo 10 caracteres. Si el intento caduca, presentar RFID otra vez.
9. **Cola:** modelo COCO captura la ROI de espera cada `SegundosConteoCola` segundos. Probar 0/1/2/3 vehículos reales, AL19 al alcanzar el umbral, sin contar etiquetas simuladas. Si se ejecuta OCR, el conteo se pausa por el mismo bloqueo.
10. **Mensajería:** transportista vinculado envía `/clima` y obtiene temperatura, humedad, lluvia, hora de última lectura y estado de grúa. Tras ingreso verificado recibe fotografía por Telegram si se configuró el bot; comprobar privacidad entre transportistas.
11. **Retenciones previas:** comprobar que RT01/RT03 de F2 siguen funcionando y ninguna fase nueva cambia el inventario sin confirmación física.

## 7. Controles de seguridad y diagnóstico

- El código NO publica lecturas meteorológicas ni detecciones ficticias en evaluación.
- Si no están instalados cámara/modelos, **degrada a validación manual** y NO abre por RFID solamente. El estado `MANUAL` caduca; no utilizarlo como bypass permanente.
- El acceso manual **sigue pasando** por manifiesto, levante, cita, disponibilidad de parqueo y enclavamientos del Mega.
- Para evidencia fotográfica se conservan los archivos en `~/portus/evidencias/garita` y su rastro en SQLite; no hay borrado desde la web.
- La fuente de la grúa sigue siendo su segundo Arduino; no enviar comandos de grúa al puerto del Mega principal ni conectar pines a ciegas. El ACK de la grúa requiere integración real de su segundo puerto serial (no incluida).
- No se han verificado físicamente las nuevas luces, baliza ni cámara; realizar pruebas incrementales con el compañero que tiene la maqueta.
- **Fase 2 aún tiene pendientes previos a la Fase 3** (integración completa de grúa/patio, algunas excepciones, reconciliación total). Este paquete no los declara terminados.

## 8. Archivos relevantes

```text
arduino/PORTUS_Fase3_v10_Principal.ino
arduino/PORTUS_Fase2_v07_Supervision_Operacion.ino  (respaldo)
raspberry/fase3_db.py               (migración de datos)
raspberry/fase3_web.py              (vistas / RBAC / auditoría)
raspberry/fase3_vision.py           (captura real, OCR, detector/YOLO)
raspberry/fase3_acceso.py           (2FA físico, manual, RT07/08)
raspberry/fase3_servicio.py         (clima, iluminación, conteo)
raspberry/verificar_fase3.py        (diagnóstico sin actuar)
raspberry/pruebas_fase3_offline.py  (test de DB/validadores aislado)
raspberry/requirements_fase3.txt
INSTALAR_ACTUALIZACION.sh
```

Este paquete aporta integración de software y un firmware candidato; no implica que la maqueta se haya ensayado físicamente. La rúbrica F3 incluye **13 escenarios completos**, y para los de clima/grúa/cámara se requerirán los equipos, los modelos y la confirmación real del compañero.
