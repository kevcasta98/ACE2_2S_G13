# PORTUS — Fase 1

## Documento Técnico

**Universidad San Carlos de Guatemala — Facultad de Ingeniería**
**Ingeniería en Ciencias y Sistemas — Arquitectura de Computadoras y Ensambladores 2**

---

## 1. Propósito de PORTUS

PORTUS es un proyecto del curso de Arquitectura de Computadoras y Ensambladores 2 que aplica principios de sistemas embebidos, automatización y control en tiempo real mediante la construcción de una maqueta funcional inspirada en las operaciones logísticas de Puerto Quetzal, la principal instalación portuaria del Pacífico guatemalteco.

El proyecto responde a problemas reales de la operación portuaria: congestión de vehículos, falta de trazabilidad de contenedores, coordinación deficiente entre procesos y uso ineficiente de los espacios de almacenamiento. PORTUS representa una terminal en la que el sistema autoriza el ingreso de camiones, controla su avance entre estaciones, verifica el peso de la carga y mantiene actualizado el estado físico del patio.

---

## 2. Objetivos de la Fase 1

Diseñar e implementar el núcleo físico y operativo de la terminal, cubriendo:

- Gestión del ingreso de camiones mediante identificación RFID.
- Control de talanquera y semáforo en la garita de entrada.
- Pesaje dinámico en movimiento, con desvío físico ante pesos fuera de tolerancia.
- Zona de transferencia entre el camión y la grúa.
- Control de una grúa de dos grados de libertad (traslación longitudinal e izaje) capaz de depositar, retirar, apilar y remover contenedores.
- Patio lineal apilable a dos niveles, con inventario coherente actualizado solo tras confirmación física.
- Concurrencia: varios camiones en estaciones distintas, con la grúa como recurso compartido atendido mediante cola de trabajos.
- Mecanismos de seguridad y manejo de errores, incluyendo paro de emergencia.

Toda la operación es completamente local (sin red, sin servidor, sin servicios externos), controlada desde Arduino, usando interrupciones, temporizadores y manipulación directa de puertos para las tareas deterministas, sin esperas bloqueantes que impidan atender otras estaciones simultáneamente.

---

## 3. Alcance implementado

### 3.1 Módulo de Garita — Ingreso y talanquera

- Lectura de tarjetas RFID (módulo MFRC522) contra una base de datos local de camiones (RFID, placa, autorización).
- Máquina de estados no bloqueante: `ESPERANDO_CAMION → VALIDANDO_ACCESO → TIEMPO_CIEGO_ARRANQUE → TALANQUERA_ABIERTA → CAMION_CRUZANDO`.
- Semáforo de tres colores (rojo / amarillo / verde) sincronizado con cada etapa: rojo en espera, amarillo durante la validación (1.5 s), verde al autorizar.
- Talanquera controlada por servomotor, con apertura al autorizar el acceso y cierre automático tras confirmar, mediante sensor infrarrojo, que el camión terminó de cruzar.
- Rechazo de acceso ante RFID no reconocido o camión no autorizado, regresando el semáforo a rojo sin abrir la talanquera.
- Control de tiempo mediante `millis()`, sin `delay()`, permitiendo que el resto del sistema siga operando durante la validación.

### 3.2 Módulo de Grúa — Traslación, izaje y patio

- Movimiento del eje X (traslación longitudinal) no bloqueante, basado en temporizador (`micros()`), con protección física mediante finales de carrera en ambos extremos.
- Referenciado automático al encender: la grúa se dirige a la posición HOME (patio) y establece su origen antes de operar.
- Detección de presencia del camión en la zona de transferencia mediante sensor infrarrojo, como condición obligatoria antes de iniciar cualquier movimiento hacia esa zona.
- Movimiento del eje Y (izaje vertical) no bloqueante: desciende hasta detectar contacto físico (no por conteo fijo de pasos) y asciende una distancia calculada dinámicamente (pasos de bajada + margen de seguridad), evitando desajustes cuando la altura de la pila cambia.
- Control del electroimán mediante MOSFET de canal N, activado/desactivado por el Arduino sin pasar corriente de 12V por el microcontrolador.
- Patio lineal representado como matriz de 3 columnas × 2 niveles, con política de asignación determinista (primera posición libre y accesible, llenando primero el nivel base).
- Identificación física de cada columna del patio mediante sensores ópticos individuales; el conteo de pasos se usa solo para ejecutar el movimiento, nunca como única fuente de posición, cumpliendo el requisito de detección de pérdida de referencia.
- Ciclo funcional completo probado: referenciado → espera de camión → recolección en transferencia → depósito en la primera posición libre del patio → regreso a HOME.

## 4. Arquitectura general de la solución

La terminal se organiza sobre un eje longitudinal único. La garita se ubica en el punto de ingreso; a continuación, la posición de transferencia se ubica en uno de los extremos del recorrido de la grúa, y se distribuyen las posiciones del patio. Los camiones ingresan perpendicularmente al extremo del riel, permitiendo que la grúa interactúe con ellos desde una posición fija.

### 4.2 Diagrama de bloques del sistema

```
┌──────────────┐   RFID/talanquera    ┌──────────────┐
│   Garita     │ ────────────────────▶│  Cola de      │
│(implementado)│                      │  trabajos      │
└──────────────┘                      │  de la grúa    │
        │ semáforo/talanquera          └──────┬─────────┘
        ▼                                     ▼
┌──────────────┐   pesaje válido      ┌──────────────┐      ┌──────────────┐
│  Pesaje       │ ────────────────────▶│  Zona de     │◀────▶│   Grúa X/Y   │
│ (pendiente)   │                      │ transferencia │      │(implementado)│
└──────────────┘                      └──────────────┘      └──────┬───────┘
                                                                     ▼
                                                           ┌───────────────────┐
                                                           │ Patio (3 col x 2   │
                                                           │ niveles) + sensores│
                                                           │ ópticos por columna│
                                                           └───────────────────┘
```

### 4.3 Principio de no bloqueo

Ningún módulo utiliza `delay()` ni funciones bloqueantes equivalentes para el control de motores, servos o sensores críticos. En la garita, el cooldown de lectura RFID y el tiempo de validación (semáforo amarillo) se controlan con `millis()`. En la grúa, el motor X y el motor Y avanzan un paso cada vez que se cumple su propio intervalo de tiempo (medido con `micros()`), permitiendo que ambos ejes se muevan de forma concurrente y que el resto del sistema (lectura de sensores, cambios de estado) se siga ejecutando en cada vuelta del `loop()` sin esperas.

---

## 5. Flujo de los vehículos

1. El camión llega a la garita; el sistema lee su RFID contra la base de datos local y valida si está registrado y autorizado.
2. Si es válido, el semáforo cambia a amarillo (validación), luego a verde, se abre la talanquera y el camión avanza. El sensor IR confirma cuándo terminó de cruzar para cerrar la talanquera automáticamente.
3. Si no es válido (RFID no reconocido o camión no autorizado), el semáforo permanece/regresa a rojo y la talanquera no se abre.
4. El camión avanza hacia el pesaje dinámico _(módulo pendiente)_; si el peso está dentro de tolerancia, es dirigido hacia la zona de transferencia.
5. En la zona de transferencia, el sensor de presencia (implementado en el módulo de grúa) detecta al camión y habilita el ciclo de la grúa.
6. La grúa ejecuta el depósito o retiro correspondiente (ver sección 7).
7. El camión pasa nuevamente por el pesaje y, si todas las validaciones son correctas, la puerta de salida se abre _(módulo pendiente)_.

---

## 6. Modelo de datos

El proyecto define cuatro entidades mínimas.

| Modelo     | Función                                                                   | Información mínima                                                                                                                |
| ---------- | ------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Camión     | Representar e identificar al vehículo dentro de la terminal.              | Identificador, código RFID, placa, tara registrada, estado de autorización local.                                                 |
| Contenedor | Representar la carga y conservar su ubicación física.                     | Identificador, peso declarado, ubicación actual (columna, nivel), estado.                                                         |
| Manifiesto | Relacionar un camión con un contenedor y definir la operación autorizada. | Camión, contenedor, tipo de operación, peso declarado, tolerancia, estado.                                                        |
| Turno      | Controlar la ejecución de una operación dentro de la terminal.            | Identificador, manifiesto asociado, estación actual, siguiente estación, pesajes, posición asignada, trabajo de grúa relacionado. |

### 6.1 Representación local del camión (garita, implementada)

```cpp
struct Camion {
  String rfid;
  String placa;
  bool autorizadoLocalmente;
};

Camion baseDatosCamiones[] = {
  {"EA225305", "C-101", true},
  {"99A08729", "C-202", true},
  {"E116F9B0", "C-303", false}
};
```

### 6.2 Representación local del patio (grúa, implementada)

El patio se modela como una matriz de 3 columnas por 2 niveles. Cada posición conserva un estado (LIBRE, RESERVADA, OCUPADA, BLOQUEADA) y el identificador del contenedor almacenado.

```cpp
enum EstadoPosicion { LIBRE, RESERVADA, OCUPADA, BLOQUEADA };
EstadoPosicion patio[3][2];       // [columna][nivel]
int contenedorEnPosicion[3][2];   // identificador del contenedor, 0 = vacío
```

Una posición pasa a RESERVADA en cuanto el sistema decide depositar ahí (antes de mover la grúa), y solo cambia a OCUPADA después de que la grúa confirma físicamente la colocación (contacto detectado + electroimán liberado). Esto evita que el inventario se actualice antes de que el movimiento físico haya concluido.

---

## 7. Módulo de Garita — arquitectura y comportamiento

### 7.1 Componentes

- Lector RFID MFRC522 (identificación del camión).
- Servomotor (talanquera).
- Sensor infrarrojo (confirmación de cruce del camión).
- Semáforo de 3 LEDs (rojo, amarillo, verde).

### 7.2 Máquina de estados

```
ESPERANDO_CAMION → VALIDANDO_ACCESO → TIEMPO_CIEGO_ARRANQUE → TALANQUERA_ABIERTA → CAMION_CRUZANDO → (vuelve a ESPERANDO_CAMION)
```

- **ESPERANDO_CAMION**: el sistema revisa periódicamente (con cooldown de 1.5 s) si hay una tarjeta RFID presente.
- **VALIDANDO_ACCESO**: se mantiene el semáforo en amarillo durante 1.5 s (tiempo de validación visible), mientras se compara el UID leído contra la base de datos local.
- **TIEMPO_CIEGO_ARRANQUE**: tras autorizar y abrir la talanquera, se espera un tiempo fijo (3 s) antes de empezar a monitorear el sensor de cruce, evitando falsas lecturas mientras el servo termina de subir la talanquera.
- **TALANQUERA_ABIERTA**: se espera a que el sensor IR detecte al camión pasando debajo.
- **CAMION_CRUZANDO**: se espera a que el sensor libere la señal (el camión ya cruzó por completo) para cerrar la talanquera y volver a poner el semáforo en rojo.

### 7.3 Validación de acceso

Actualmente la validación compara el UID leído contra la lista local de camiones y su bandera `autorizadoLocalmente`. La verificación de manifiesto pendiente, tipo de operación autorizada y disponibilidad de la siguiente estación (patio/grúa) está pendiente de integrarse a esta lógica.

---

## 8. Módulo de Grúa — arquitectura y comportamiento

### 8.1 Grados de libertad

- **Eje X** — traslación longitudinal, motor 28BYJ-48 + ULN2003, control por secuencia de medio paso (8 pasos), no bloqueante.
- **Eje Y** — izaje vertical, mismo tipo de motor y control, con detección de contacto físico para el descenso.

### 8.2 Referenciado

Al energizar el sistema, la posición de la grúa es desconocida. El eje X se mueve automáticamente en dirección a HOME (extremo izquierdo del riel) hasta activar el final de carrera correspondiente. Ese evento establece el origen de referencia; el conteo de pasos se usa únicamente para ejecutar movimientos posteriores, nunca como fuente única de posición.

Durante el desplazamiento hacia una columna del patio, el sistema cuenta los pasos transcurridos. Si se supera un umbral máximo esperado sin detectar la marca óptica de la columna destino, se declara pérdida de referencia, se detiene el motor y se reinicia el procedimiento de referenciado.

### 8.3 Máquina de estados del ciclo completo

```
REFERENCIANDO → ESPERANDO_CAMION → MOVIENDO_A_TRANSFERENCIA
→ BAJANDO_RECOGER → AGARRANDO → SUBIENDO_CON_CARGA
→ BUSCANDO_COLUMNA → MOVIENDO_A_COLUMNA → BAJANDO_DEPOSITAR
→ SOLTANDO → SUBIENDO_VACIO → REGRESANDO_A_HOME → (vuelve a ESPERANDO_CAMION)

Estados de excepción: PERDIDA_REFERENCIA, PATIO_LLENO
```

**Descenso (eje Y) — basado en contacto, no en conteo fijo.** El motor Y desciende de forma continua mientras no se detecte el switch de contacto en el cabezal. Al presionarse, el motor se detiene de inmediato. Esto permite que el mismo procedimiento funcione sin cambios sin importar si el cabezal encuentra el piso del patio (posición vacía) o la superficie de un contenedor ya apilado (nivel 1).

**Ascenso (eje Y) — basado en pasos contados durante el descenso.** Se registra la cantidad exacta de pasos que el motor dio al bajar (`pasosBajadaContados`). Al subir, se usa esa misma cantidad más un margen fijo de seguridad (`MARGEN_ALTURA_SEGURA`):

```cpp
pasosRestantesY = pasosBajadaContados + MARGEN_ALTURA_SEGURA;
```

**Agarre y liberación de carga (electroimán).** El electroimán se controla mediante un MOSFET de canal N (IRLZ44N, logic level) activado desde un pin digital del Arduino a través de una resistencia de 220Ω en la compuerta, con resistencia pull-down de 10kΩ y diodo flyback 1N4007 en paralelo con la bobina, protegiendo el circuito del pico inductivo al desenergizar. La alimentación de 12V del electroimán es independiente de la del Arduino, con tierra común obligatoria.

**Selección de posición en el patio.** Tras confirmar la carga y alcanzar la altura segura, el sistema busca la primera posición libre siguiendo un orden determinista: primero recorre el nivel base (0) de las tres columnas en orden; si todas las bases están ocupadas, busca la primera columna cuyo nivel 0 esté ocupado y nivel 1 esté libre.

**Confirmación física y actualización del inventario.** La posición destino se marca como RESERVADA antes de iniciar el movimiento. El inventario solo se actualiza a OCUPADA después de que el switch de contacto confirma que el cabezal tocó la superficie de depósito y el electroimán fue liberado, nunca al emitir el comando de movimiento.

---

## 9. Conexiones físicas

### 9.1 Garita

| Componente                  | Pin en Arduino Mega |
| --------------------------- | ------------------- |
| RFID — SS (SDA)             | Pin 53              |
| RFID — RST                  | Pin 5               |
| Servo (talanquera)          | Pin 9               |
| Sensor IR (cruce de camión) | Pin 7               |
| LED rojo                    | Pin 22              |
| LED amarillo                | Pin 23              |
| LED verde                   | Pin 24              |

### 9.2 Grúa — Motor X (ULN2003, traslación longitudinal)

| Pin en la placa ULN2003 | Conecta a Arduino Mega                  |
| ----------------------- | --------------------------------------- |
| IN1                     | Pin 13                                  |
| IN2                     | Pin 12                                  |
| IN3                     | Pin 11                                  |
| IN4                     | Pin 10                                  |
| VCC                     | Fuente externa 5V (+)                   |
| GND                     | Tierra común (fuente externa + Arduino) |

### 9.3 Grúa — Motor Y (ULN2003, izaje vertical)

| Pin en la placa ULN2003 | Conecta a Arduino Mega                    |
| ----------------------- | ----------------------------------------- |
| IN1                     | Pin 9                                     |
| IN2                     | Pin 8                                     |
| IN3                     | Pin 7                                     |
| IN4                     | Pin 6                                     |
| VCC                     | Fuente externa 5V (+) — misma que motor X |
| GND                     | Tierra común                              |

### 9.4 Grúa — Finales de carrera y switch de contacto

| Componente                               | COM         | NO     | NC          |
| ---------------------------------------- | ----------- | ------ | ----------- |
| Final de carrera IZQUIERDO (HOME)        | GND Arduino | Pin A0 | No conectar |
| Final de carrera DERECHO (transferencia) | GND Arduino | Pin A1 | No conectar |
| Switch de contacto (cabezal Y)           | GND Arduino | Pin A2 | No conectar |

### 9.5 Grúa — Sensores IR y ópticos

| Sensor                              | VCC | GND | Salida |
| ----------------------------------- | --- | --- | ------ |
| Presencia de camión (transferencia) | 5V  | GND | Pin 4  |
| Óptico — columna 1 (patio)          | 5V  | GND | Pin 2  |
| Óptico — columna 2 (patio)          | 5V  | GND | Pin 3  |
| Óptico — columna 3 (patio)          | 5V  | GND | Pin A3 |

### 9.6 Grúa — Electroimán (control vía MOSFET)

| Componente                  | Conexión                                                       |
| --------------------------- | -------------------------------------------------------------- |
| Compuerta (Gate) del MOSFET | Pin 5 del Arduino, con resistencia de 220Ω en serie            |
| Resistencia pull-down       | Entre Gate y GND — 10kΩ                                        |
| Drenaje (Drain)             | Electroimán (-)                                                |
| Fuente (Source)             | GND común                                                      |
| Electroimán (+)             | Fuente externa 12V (+)                                         |
| Diodo flyback 1N4007        | En paralelo con el electroimán (cátodo hacia +, ánodo hacia -) |
| Fuente 12V (-)              | GND común                                                      |

### 9.7 Resumen de pines del Arduino Mega utilizados (módulo de grúa)

| Pin   | Función                                                             |
| ----- | ------------------------------------------------------------------- |
| 2     | Sensor óptico columna 1                                             |
| 3     | Sensor óptico columna 2                                             |
| 4     | Sensor IR de presencia (camión)                                     |
| 5     | Compuerta MOSFET (electroimán) — en conflicto con RST_PIN de garita |
| 6–9   | Motor Y (IN4, IN3, IN2, IN1)                                        |
| 10–13 | Motor X (IN4, IN3, IN2, IN1)                                        |
| A0    | Final de carrera HOME                                               |
| A1    | Final de carrera transferencia                                      |
| A2    | Switch de contacto (cabezal Y)                                      |
| A3    | Sensor óptico columna 3                                             |
| 5V    | VCC de sensores IR y ópticos                                        |
| GND   | Tierra común (Arduino + switches + sensores + fuentes externas)     |

Todos los GND deben unirse entre sí: el del Arduino, el de la fuente externa de 5V de los motores y el de la fuente de 12V del electroimán. Sin esta tierra común, las lecturas digitales y el control del MOSFET no son confiables.

---

## 10. Seguridad y manejo de errores

| Condición                           | Mecanismo de detección                                                                               | Respuesta del sistema                                                                          |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Límite físico del riel (X)          | Finales de carrera en ambos extremos, revisados en cada ciclo antes de dar un paso                   | Detención inmediata del motor X; solo se permite movimiento en la dirección contraria          |
| Fin de descenso (Y)                 | Switch de contacto en el cabezal                                                                     | Detención inmediata del motor Y; transición al siguiente estado (agarre o suelta)              |
| Pérdida de referencia (X)           | Conteo de pasos en tránsito supera el umbral máximo esperado sin detectar la marca óptica de destino | Detención del motor; el sistema regresa al estado REFERENCIANDO                                |
| Patio lleno                         | Ninguna posición LIBRE encontrada en la búsqueda determinista                                        | Transición a estado PATIO_LLENO; el ciclo no continúa hasta que exista una posición disponible |
| Ausencia de camión en transferencia | Sensor IR de presencia                                                                               | La grúa permanece en ESPERANDO_CAMION; no se ejecuta ningún movimiento hacia esa zona          |
| Acceso no autorizado en garita      | Comparación de UID contra base de datos local                                                        | La talanquera permanece cerrada y el semáforo regresa a rojo                                   |

Quedan por integrar: paro de emergencia físico atendido por interrupción (con rearme explícito), y las validaciones de seguridad de nivel de sistema completo (posición de destino ocupada verificada desde garita, pérdida de carga durante el traslado, movimiento del camión durante la transferencia), que requieren coordinación entre los módulos de garita, transferencia y grúa.

---

## 11. Código fuente

El código de ambos módulos (garita/talanquera y grúa) se entrega junto con este documento en la carpeta `Codigo_Fuente/`, comentado por sección. Ninguno de los dos utiliza `delay()` para el control de motores, servos o lectura de sensores críticos: ambos se basan en `millis()`/`micros()` y máquinas de estado, cumpliendo el requerimiento técnico de no bloquear la atención simultánea de otras estaciones.

---

## 12. Conclusiones

- El ciclo completo de la garita (lectura RFID, validación, apertura/cierre de talanquera, semáforo) fue probado de forma funcional de manera independiente.
- El ciclo completo de la grúa (recolección, traslado y depósito) fue probado de forma funcional: referenciado, detección de camión, descenso hasta contacto, agarre, ascenso proporcional, traslado a la primera posición libre del patio, descenso, liberación y regreso a HOME.
- El uso de un switch de contacto (en vez de conteo fijo) para el descenso, y de pasos contados (en vez de un valor fijo) para el ascenso, resuelve correctamente el problema de alturas variables según el estado de apilamiento del patio.
- Antes de la integración conjunta en un solo Arduino, es necesario resolver el conflicto de pin 5 entre ambos módulos y conectar la validación de garita con la disponibilidad real del patio.
