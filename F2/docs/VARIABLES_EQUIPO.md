# PORTUS Fase 2 — Nombres, variables y funciones para el equipo

Documento del **Compañero 1 (backend + base de datos + usuarios)**. Aquí está todo lo que los demás
necesitan usar **con el nombre exacto**. La fuente única de verdad es
[`server/models/constantes.py`](../server/models/constantes.py): si alguien necesita un estado, causa,
alarma, comando o tópico, lo importa de ahí (Python) o copia el valor literal (Arduino / JS).
También se pueden pedir todos juntos en `GET /api/catalogos/constantes`.

- Endpoints completos: [API_ENDPOINTS.md](API_ENDPOINTS.md)
- Tablas: [BASE_DE_DATOS.md](BASE_DE_DATOS.md)

---

## 0. Reglas comunes (para todos)

| Qué | Valor |
|---|---|
| URL del backend | `http://<ip-raspberry>:5000` (local: `http://localhost:5000`) |
| Formato de respuesta | éxito `{"ok": true, "datos": ...}` · error `{"ok": false, "error": "mensaje", "codigo": ...}` |
| Códigos HTTP de error | `400` datos inválidos · `401` sin sesión · `403` sin permiso · `404` no existe · `409` conflicto de estado |
| Sesión web | cookie de Flask. Login en `POST /api/auth/login` con `{"usuario", "password"}` |
| Token para bot/puente/simulador | encabezado `X-Portus-Token: portus-interno-dev` (en la Raspberry: variable `PORTUS_TOKEN_INTERNO`) |
| Pesos | **siempre gramos enteros** (`peso_declarado_g`, `peso_g`, `tara_g`) |
| Fechas | `"YYYY-MM-DD HH:MM:SS"` hora local |
| Contraseña de prueba de todos los usuarios | `1234` (se guarda con hash) |

### Usuarios de prueba (mismos nombres que el mock del Compañero 2)

| usuario | rol | entidad |
|---|---|---|
| `operador1` | TERMINAL | — |
| `naviera1` | NAVIERA | `NAVIERA1` (Naviera Pacífico S.A.) |
| `naviera2` | NAVIERA | `NAVIERA2` (Naviera Atlántico S.A.) |
| `agente1` | AGENTE | — |
| `autoridad1` | AUTORIDAD | — |
| `transportista1` | TRANSPORTISTA | `TRANS-A` (sin acceso web, usa el bot) |
| `transportista2` | TRANSPORTISTA | `TRANS-B` (sin acceso web, usa el bot) |

### Vehículos (UID reales del firmware Fase 1, `control_central.cpp`)

| rfid_uid | placa | transportista | tara_g |
|---|---|---|---|
| `EA225305` | `C-101` | TRANS-A | 500 |
| `99A08729` | `C-202` | TRANS-B | 520 |
| `E116F9B0` | `C-303` | TRANS-A | 500 |
| `00000004` | `C-404` | TRANS-B | 500 ← cambiar por el UID de una 4.ª tarjeta (escenario E11) |

Contenedores del catálogo: `CONT-001` … `CONT-010`. Patio inicial: P1 = CONT-001 (nivel 1) + CONT-002 (nivel 2), P2 = CONT-003.
Se edita en [`server/models/semilla.py`](../server/models/semilla.py) (`VEHICULOS`, `CONTENEDORES`, `INVENTARIO_INICIAL`)
y **debe coincidir con la maqueta física** antes de la demo.

---

## 1. Constantes oficiales (valores literales)

### Roles
`TERMINAL`, `NAVIERA`, `AGENTE`, `AUTORIDAD`, `TRANSPORTISTA`

### Estados del turno (exactamente estos 10, con esta escritura)
`Programado`, `EnGarita`, `EnPesajeEntrada`, `EnRuta`, `EnTransferencia`, `EnPesajeSalida`, `EnSalida`, `Retenido`, `Cerrado`, `Anulado`

### Manifiesto
| Campo | Valores |
|---|---|
| `tipo` | `DEPOSITO`, `RETIRO` |
| `estado_documental` | `PENDIENTE_DECLARACION`, `DECLARACION_PRESENTADA`, `LEVANTE_SOLICITADO`, `LEVANTE_OTORGADO`, `LEVANTE_RETENIDO`, `ANULADO` |
| `estado_operativo` | `SIN_CITA`, `CITA_PROGRAMADA`, `EN_TERMINAL`, `COMPLETADO`, `ANULADO` |
| `canal` | `VERDE`, `ROJO` (o `null`) |
| `regimen` (declaración) | `IMPORTACION_DEFINITIVA`, `DEPOSITO_TEMPORAL` |
| solicitud de levante `estado` | `PENDIENTE`, `OTORGADO`, `RETENIDO` |

### Retenciones
| Código | Causa | Rol facultado |
|---|---|---|
| `RT01` | Discrepancia de peso al ingreso | TERMINAL |
| `RT02` | Discrepancia de peso a la salida | TERMINAL |
| `RT03` | Canal rojo de selectivo | AUTORIDAD |
| `RT04` | Llegada fuera de la ventana asignada | TERMINAL |
| `RT05` | Retención documental | AUTORIDAD |
| `RT06` | Retención manual operativa | TERMINAL |

Resoluciones: `ACLARAR`, `CORREGIR` (solo TERMINAL, solo RT01/RT02), `RECHAZAR` (exige `motivo`).
Estado de retención: `ABIERTA`, `RESUELTA`.

### Alarmas
| Código | Severidad | | Código | Severidad |
|---|---|---|---|---|
| `AL01` Enlace perdido | `CRITICA` | | `AL08` Movimiento del vehículo en transferencia | `ALTA` |
| `AL02` Paro de emergencia | `CRITICA` | | `AL09` Pesaje fuera de tolerancia | `MEDIA` |
| `AL03` Pérdida de referencia grúa | `CRITICA` | | `AL10` Vehículo incorrecto en salida | `MEDIA` |
| `AL04` Pérdida de carga | `CRITICA` | | `AL11` Parqueo de retención lleno | `MEDIA` |
| `AL05` Agarre no confirmado | `ALTA` | | `AL12` Retención > 30 min | `MEDIA` |
| `AL06` Trabajo de grúa abortado | `ALTA` | | `AL13` Permanencia > 2 h | `BAJA` |
| `AL07` Inconsistencia altura/inventario | `ALTA` | | `AL14` Comando rechazado | `BAJA` |

### Comandos remotos (exactamente estos 13)
`AbrirTalanquera`, `CerrarTalanquera`, `AbrirPuertaSalida`, `AgujaRecta`, `AgujaParqueo`, `AgujaLiberar`,
`GruaReferenciar`, `GruaSuspender`, `GruaReanudar`, `PosicionBloquear`, `PosicionLiberar`, `ModoMantenimiento`, `AlarmaSilenciar`

Parámetros: `PosicionBloquear`/`PosicionLiberar` → `{"posicion": 1..6}` · `ModoMantenimiento` → `{"activar": true|false}` · `AgujaParqueo`/`AgujaLiberar` → `{"plaza": 1..3}`.

### Citas
Franja `15` min · capacidad `2` · gracia `5` min después del fin · recordatorio `60` min antes.
Estados: `PROGRAMADA`, `CUMPLIDA`, `VENCIDA`, `CANCELADA`.

### Patio / sistema
Posiciones `1..6`, niveles `1..2`. Estado de posición: `LIBRE`, `RESERVADA`, `OCUPADA_N1`, `OCUPADA_N2`, `BLOQUEADA`.
Modo: `NORMAL`, `MANTENIMIENTO`, `DEGRADADO`. Enlace: `CONECTADO`, `DESCONECTADO`. Plazas de parqueo: `1..3`.

---

## 2. Compañero 2 — Interfaces web

### 2.1 Qué endpoint alimenta cada pestaña

| Rol / Pestaña | Leer | Acciones |
|---|---|---|
| Todas: barra superior | `GET /api/auth/yo` → `nombre`, `rol`, `pestanas`, `permisos` | `POST /api/auth/logout` |
| TERMINAL · Operación | `GET /api/sistema/estado` **solo al cargar**, luego MQTT (ver 2.3) | `POST /api/comandos`, `POST /api/parqueo/<plaza>/liberar` |
| TERMINAL · Turnos | `GET /api/turnos?seccion=activos` / `historicos` (+`estado`,`tipo`,`desde`,`hasta`,`q`) · `GET /api/turnos/<id>/linea-tiempo` | `POST /api/turnos/<id>/retener`, `POST /api/turnos/<id>/anular` |
| TERMINAL · Retenciones | `GET /api/retenciones?estado=ABIERTA&causa=RT01` | `POST /api/retenciones/<id>/aclarar` · `/corregir` · `/rechazar` |
| TERMINAL · Patio | `GET /api/patio` | `POST /api/patio/<pos>/bloquear` · `/liberar` |
| TERMINAL · Grúa | `GET /api/grua?limite=50\|100\|200` | `GET /api/grua/exportar.csv?limite=50` |
| TERMINAL · Alarmas | `GET /api/alarmas?estado=activas\|historicas&severidad=MEDIA` | `POST /api/alarmas/<id>/reconocer` · `POST /api/alarmas/reconocer-todas` |
| TERMINAL · Citas | `GET /api/citas/agenda?fecha=2026-09-26` · `GET /api/citas/franjas-disponibles` | `POST /api/citas/<id>/cancelar` · `/reprogramar` · `POST /api/franjas/<id>/bloquear` |
| TERMINAL · Reportes | `GET /api/reportes` | `POST /api/reportes` · `GET /api/reportes/<id>/exportar.csv` |
| TERMINAL · (vinculación bot) | `GET /api/catalogos/transportistas` | `POST /api/transportistas/TRANS-A/codigo-vinculacion` |
| NAVIERA · Manifiestos | `GET /api/manifiestos` · `GET /api/manifiestos/<id>` · `GET /api/catalogos/transportistas` | `POST /api/manifiestos` · `POST /api/manifiestos/<id>/anular` |
| NAVIERA · Mis contenedores | `GET /api/contenedores?q=&autorizacion=` (el servidor ya filtra solo los suyos) | — |
| AGENTE · Declaraciones | `GET /api/declaraciones/pendientes` | `POST /api/manifiestos/<id>/declaracion` · `/solicitar-levante` · `/observaciones` |
| AGENTE · Seguimiento | `GET /api/declaraciones/seguimiento?estado=&numero=` | — |
| AUTORIDAD · Solicitudes de levante | `GET /api/levantes` · `GET /api/levantes/<id>` (ver declaración) | `POST /api/levantes/<id>/otorgar {canal}` · `/retener {motivo}` |
| AUTORIDAD · Retenciones aduaneras | `GET /api/retenciones` (el servidor devuelve solo RT03/RT05) | `/aclarar`, `/rechazar` (sin Corregir) · `POST /api/turnos/<id>/retencion-documental` (RT05) |
| AUTORIDAD · Consulta de carga | `GET /api/contenedores?q=&naviera=&autorizacion=` | — |

### 2.2 Cambios de nombres respecto a `F2/App/mock_data.py`

| mock_data | Backend real |
|---|---|
| `peso_declarado` | `peso_declarado_g` |
| `tolerancia` | `tolerancia_pct` |
| `tipo: "Deposito"` | `tipo: "DEPOSITO"` |
| `estado: "Pendiente declaración"` | `estado_documental: "PENDIENTE_DECLARACION"` |
| `canal: "Verde"` | `canal: "VERDE"` |
| retención `estado: "Abierta"` | `estado: "ABIERTA"` |
| retención `causa: "RT01 - Discrepancia..."` | `causa: "RT01"` + `causa_descripcion` |
| retención `diferencia_pct` suelto | `evidencia_peso: {peso_declarado_g, peso_medido_g, diferencia_g, diferencia_pct}` (null si no es de peso) |
| alarma `severidad: "Media"` | `severidad: "MEDIA"` |
| alarma `reconocida: False` | `reconocida: 0/1` + `estado_reconocimiento` |
| turno `id: "T-501"` | `id` numérico (para URLs) + `codigo: "T-0001"` (para mostrar) |
| turno `peso_ingreso` / `peso_salida` | `peso_entrada_g` / `peso_salida_g` (bruto) |
| turno `posicion_patio: "A1-1"` | `posicion_patio: "P1-1"` |
| turno `tiempo` | `tiempo_en_terminal` (`"0h 12m 05s"`) |
| contenedor `permanencia_h` | `permanencia` (`"2h 05m"`), `permanencia_min`, `permanencia_excesiva` (true si > 2 h) |
| `session["entidad"]` | viene en `/api/auth/yo` como `naviera_codigo` |

Mostrar botones según `permisos` de `/api/auth/yo`, pero **el servidor valida igual**: si un botón se
muestra por error, la acción devuelve 403 con el mensaje en `error` → mostrarlo tal cual.

### 2.3 Sinóptico en tiempo real (OBLIGATORIO por MQTT, prohibido consultar periódicamente)

1. Mosquitto con WebSockets (en la Raspberry, `/etc/mosquitto/conf.d/portus.conf`):
   ```
   listener 1883
   listener 9001
   protocol websockets
   allow_anonymous true
   ```
2. En la página Operación: `GET /api/sistema/estado` **una sola vez** para el estado inicial, luego:
   ```html
   <script src="https://cdn.jsdelivr.net/npm/mqtt/dist/mqtt.min.js"></script>
   <script>
     const cliente = mqtt.connect("ws://" + location.hostname + ":9001");
     cliente.on("connect", () => { cliente.subscribe("portus/evt/#"); cliente.subscribe("portus/srv/#"); });
     cliente.on("message", (topico, payload) => {
       const m = JSON.parse(payload);   // {id, ts, origen, tipo, datos}
       // actualizar el elemento del sinóptico según topico + m.tipo
     });
   </script>
   ```
3. Qué escuchar:

| Tópico | `tipo` | Para |
|---|---|---|
| `portus/evt/estado` | `LATIDO` | talanquera, puerta, aguja, grúa, cola, modo (ver campos en 5.2). Guardar `m.ts` como "último mensaje" |
| `portus/srv/sistema` | `ENLACE` | `datos.enlace` = `CONECTADO`/`DESCONECTADO` → marcar datos como NO actuales y mostrar `ultimo_latido` |
| `portus/srv/turno` | `TURNO_CREADO`, `TURNO_ESTADO` | vehículos del sinóptico, pestaña Turnos |
| `portus/srv/parqueo` | `PARQUEO_ACTUALIZADO` | `datos.plazas[]` con `numero`, `estado`, `vehiculo`, `segundos_retenido`, `estado_retencion` |
| `portus/srv/patio` | `PATIO_ACTUALIZADO` | `datos.posiciones[]` con `numero`, `estado`, `contenedor_n1`, `contenedor_n2` |
| `portus/srv/retencion` | `RETENCION_CREADA`, `RETENCION_RESUELTA` | bandeja de retenciones |
| `portus/srv/alarma` | `ALARMA_NUEVA`, `ALARMA_RECONOCIDA` | pestaña Alarmas / contador |
| `portus/srv/comando` | `COMANDO_RESULTADO` | mostrar al usuario si su comando fue `ACEPTADO` o `RECHAZADO` + `causa_rechazo` |
| `portus/evt/pesaje`, `portus/evt/grua`, `portus/evt/transferencia`, `portus/evt/garita`, `portus/evt/aguja`, `portus/evt/salida` | ver 5.2 | animación de cada estación |

Condiciones de los botones del sinóptico (sección 4.1): Reanudar solo si grúa `SUSPENDIDA`; Referenciar solo si `REPOSO` o `SUSPENDIDA`;
Abrir talanquera / puerta / Modo mantenimiento piden confirmación; Liberar parqueo solo si la plaza tiene `estado_retencion == "RESUELTA"`.

### 2.4 Integración con el backend
La forma más simple: registrar las páginas de `F2/App` como un Blueprint dentro de `create_app()` (misma cookie de sesión)
y que las plantillas llamen a `/api/...` con `fetch(url, {credentials: "same-origin"})`.

---

## 3. Compañero 3 — Cadena documental

Tu lógica está en [`server/services/cadena_documental.py`](../server/services/cadena_documental.py) (ya funcional, para que la extiendas).
Las rutas en [`server/routes/documental.py`](../server/routes/documental.py) ya validan permisos con la matriz; no hace falta tocarlas.

| Función | Quién | Qué hace |
|---|---|---|
| `crear_manifiesto(usuario, datos)` | NAVIERA | valida catálogo, tipo, peso > 0, tolerancia (5 % por defecto), transportista, **un solo manifiesto pendiente por contenedor** |
| `anular_manifiesto(usuario, manifiesto_id, motivo)` | NAVIERA dueña | solo si no tiene turno; cancela la cita si existe |
| `listar(usuario, alcance, estado, contenedor)` / `detalle(...)` | todos menos TRANSPORTISTA | `alcance="PROPIOS"` filtra por naviera |
| `pendientes_de_levante()` | AGENTE | manifiestos de cualquier naviera sin levante |
| `presentar_declaracion(usuario, manifiesto_id, datos)` | AGENTE | `numero_declaracion` único, `regimen`, `descripcion` ≥ 10, `valor_declarado` > 0 → `DECLARACION_PRESENTADA` |
| `solicitar_levante(usuario, manifiesto_id)` | AGENTE | solo con declaración presentada (o tras retención) → `LEVANTE_SOLICITADO` |
| `agregar_observacion(usuario, manifiesto_id, texto)` | AGENTE | nota visible para la autoridad |
| `seguimiento(usuario, estado, numero)` | AGENTE | sus solicitudes con canal y motivo |
| `solicitudes(estado)` / `obtener_solicitud(sid)` | AUTORIDAD | bandeja y "Ver declaración" |
| `otorgar_levante(usuario, sid, canal)` | AUTORIDAD | canal obligatorio → `LEVANTE_OTORGADO` + notificación `LEVANTE_OTORGADO` |
| `retener_levante(usuario, sid, motivo)` | AUTORIDAD | motivo obligatorio → `LEVANTE_RETENIDO` + notificación `LEVANTE_RETENIDO` |

Efecto físico (ya implementado en `services/operacion.py → validar_ingreso`): sin levante la garita responde
`autorizado: false` y la talanquera no abre; con canal `ROJO` el vehículo va al parqueo (RT03) tras el pesaje de entrada.
Para notificar al transportista usa siempre `notificaciones.notificar(transportista_id, C.NOTIF_..., {...})`.

---

## 4. Compañero 4 — Bot del transportista

El bot **no** accede a la base directamente: usa la API `/api/bot/*` con el encabezado `X-Portus-Token`
y el `chat_id` de Telegram/WhatsApp del usuario. El servidor ya garantiza que solo recibe **su** carga.

| Comando | Llamada | Qué mostrar |
|---|---|---|
| (cualquiera, no vinculado) | cualquier ruta responde `403` con `"codigo": "NO_VINCULADO"` | siempre el mismo texto de `error` (pedir `/vincular CODIGO`) |
| `/inicio`, `/ayuda` | no requiere API | saludo + `NOMBRE_TERMINAL` = `"PORTUS - Terminal Puerto Quetzal"` + lista de los 7 comandos |
| `/vincular CODIGO` | `POST /api/bot/vincular {"chat_id", "codigo"}` | `datos.nombre` del transportista; error si inválido, usado o vencido (60 min) |
| `/cita` paso 1 | `GET /api/bot/contenedores-para-cita?chat_id=` | lista de `contenedor` (con levante y sin cita) |
| `/cita` paso 2 | `GET /api/bot/franjas-disponibles?chat_id=` | `id`, `fecha`, `hora_inicio`, `hora_fin` de las próximas franjas con cupo |
| `/cita` paso 3 | `POST /api/bot/citas {"chat_id", "contenedor", "franja_id"}` | confirmación: `contenedor`, `fecha`, `hora_inicio`, `hora_fin` |
| `/miscitas` | `GET /api/bot/citas?chat_id=` | `contenedor`, `fecha`, `hora_inicio`-`hora_fin`, `estado` |
| `/estado CONT-001` | `GET /api/bot/contenedores/CONT-001?chat_id=` | `contenedor`, `estado`, `ubicacion`, `posicion`, `permanencia`, `autorizacion`, `canal`. Si no es suyo → 404 "No tiene carga asociada a ese identificador." |
| `/misturnos` | `GET /api/bot/turnos?chat_id=` | `vehiculo`, `contenedor`, `tipo`, `estado`, `estacion` |
| texto no reconocido | — | "Comando no reconocido. Escriba /ayuda" (nunca quedarse sin responder) |

**Notificaciones automáticas (las 9):** el servidor las deja en la tabla `notificaciones` con el texto ya
armado en `mensaje`. Bucle del bot (cada 2–3 s, o al recibir `portus/srv/notificacion` por MQTT):
1. `GET /api/bot/notificaciones/pendientes` → lista con `id`, `tipo`, `mensaje`, `datos`, `chat_id`.
2. Si `chat_id` es null, saltarla (queda pendiente hasta que el transportista se vincule).
3. Enviar `mensaje` a `chat_id` → `POST /api/bot/notificaciones/<id>/enviada` (o `/error {"error": "..."}`).

Tipos: `LEVANTE_OTORGADO`, `LEVANTE_RETENIDO`, `CITA_ASIGNADA`, `CITA_RECORDATORIO`, `VEHICULO_RETENIDO`,
`RETENCION_RESUELTA`, `CITA_MODIFICADA`, `TURNO_CERRADO`, `TURNO_ANULADO`.
El código de vinculación lo genera TERMINAL: `POST /api/transportistas/TRANS-A/codigo-vinculacion`.

---

## 5. Firmware + puente serial ↔ MQTT (controller/ y bridge/)

### 5.1 Formato obligatorio de TODO mensaje MQTT (igual en todos los tópicos)
```json
{"id": "uuid", "ts": "2026-09-26T10:15:02.123", "origen": "controlador", "tipo": "VEHICULO_DETECTADO",
 "seq": 57, "datos": {"rfid": "EA225305"}}
```
- `seq`: número de secuencia creciente del controlador (el servidor detecta pérdidas).
- `id`: lo genera el puente; si reenvía eventos guardados durante una desconexión, **mantener el mismo id**
  (el servidor descarta duplicados). `ts` = hora del evento (para eventos acumulados: ahora − `edad_ms`).
- Tras `GARITA_RESULTADO` autorizado, todos los eventos del camión deben incluir `"turno": "T-0001"` y/o `"rfid"`.

### 5.2 Eventos que publica el controlador

| Tópico | `tipo` | `datos` |
|---|---|---|
| `portus/evt/garita` | `VEHICULO_DETECTADO` | `rfid` |
| `portus/evt/pesaje` | `MEDICION_INICIADA` | `turno`, `etapa` (`ENTRADA`/`SALIDA`) |
| `portus/evt/pesaje` | `MEDICION_FINAL` | `turno`, `etapa`, `peso_g` (bruto), `muestras`, `resultado` (opcional) |
| `portus/evt/aguja` | `AGUJA_ESTADO` | `estado`: `RECTA` / `PARQUEO` / `LIBERANDO` |
| `portus/evt/transferencia` | `VEHICULO_POSICIONANDO`, `VEHICULO_ALINEADO`, `TRANSFERENCIA_INICIO`, `TRANSFERENCIA_ABORTO`, `TRANSFERENCIA_FIN` | `turno`, (`causa` en aborto) |
| `portus/evt/grua` | `GRUA_ESTADO` | `estado` (`REPOSO`, `REFERENCIANDO`, `DESPLAZANDO`, `IZANDO`, `TRASLADANDO`, `DEPOSITANDO`, `SUSPENDIDA`, `FALLA`), `posicion`, `trabajo_id`, `agarre` |
| `portus/evt/grua` | `CICLO_INICIO` / `CICLO_FIN` | `trabajo_id`, `tipo`, `contenedor`, `origen`, `destino` / `resultado` (`OK`/`ABORTADO`/`FALLA`), `distancia_mm`, `duracion_ms` |
| `portus/evt/grua` | `FALLA` | `falla`: `PERDIDA_REFERENCIA` / `AGARRE_NO_CONFIRMADO` / `MOVIMIENTO_ABORTADO` / `PERDIDA_CARGA`, `trabajo_id` (el servidor genera AL03/AL05/AL06/AL04) |
| `portus/evt/patio` | `POSICION_CAMBIO` | `posicion`, `nivel`, `contenedor`, `accion` (`COLOCADO`/`RETIRADO`), `motivo` (`DEPOSITO`/`RETIRO`/`REMOCION`), `turno` — **solo con confirmación física** |
| `portus/evt/salida` | `VEHICULO_EN_SALIDA`, `VEHICULO_SALIO` | `rfid`, `turno` |
| `portus/evt/alarma` | `ALARMA` / `ALARMA_CESADA` | `codigo` (`AL02`, `AL08`, …), `detalle`, `clave` |
| `portus/evt/estado` | `LATIDO` (cada ≤ 5 s) | `modo`, `talanquera`, `puerta_salida`, `aguja`, `grua_estado`, `grua_posicion`, `cola_grua`, `trabajo_actual`, `cola_espera`, `paro_emergencia`, `garita`, `pesaje`, `transferencia` |
| `portus/evt/estado` | `ESTADO_REAL` (al reconectar) | lo mismo + `patio: [{"posicion":1,"n1":"CONT-001","n2":null}, ...]` → el servidor reconcilia |
| `portus/cmd/respuesta` | `COMANDO_RESPUESTA` | `comando_id` (= `id` de la solicitud), `aceptado`, `causa` |

### 5.3 Lo que el servidor le manda al controlador

| Tópico | `tipo` | `datos` → qué hacer |
|---|---|---|
| `portus/cmd/solicitud` | nombre del comando (ej. `GruaSuspender`) | `comando`, `parametros` → validar seguridad y responder en `portus/cmd/respuesta` con `comando_id = id` del mensaje |
| `portus/srv/decision` | `GARITA_RESULTADO` | `rfid`, `autorizado`, `causa`, `mensaje_lcd` (≤ 32 car.), y si autoriza: `turno`, `contenedor`, `tipo`, `peso_declarado_g`, `tolerancia_pct`, `tara_g`, `canal`, `fuera_de_ventana` (guardarlos para operar en modo degradado) |
| `portus/srv/decision` | `RUTA_TRANSFERENCIA` / `RUTA_PARQUEO` | `turno`, `plaza` → aguja recta / al parqueo |
| `portus/srv/decision` | `TRABAJOS_GRUA` | `turno`, `trabajos[]` con `trabajo_id`, `orden`, `tipo`, `contenedor`, `origen`, `destino` (`{"posicion","nivel"}` o `"VEHICULO"`) → encolar |
| `portus/srv/decision` | `RETENCION_RESUELTA` | `turno`, `plaza`, `continuar`, `estado` → sale del parqueo y sigue |
| `portus/srv/decision` | `PESAJE_SALIDA_OK` / `SALIDA_AUTORIZADA` / `SALIDA_DENEGADA` | `turno`, `rfid` → abrir o no la puerta de salida |

Sin servidor (3 latidos sin respuesta) el controlador debe: terminar el trabajo de grúa en curso, completar los turnos
que ya están dentro con los datos de `GARITA_RESULTADO`, rechazar ingresos nuevos (LCD "modo degradado"), guardar eventos y
al reconectar enviar `ESTADO_REAL` + los eventos guardados.

Para probar sin Arduino ni Mosquitto: `POST /api/interno/eventos {"topico": "...", "mensaje": {...}}` con `X-Portus-Token`.
