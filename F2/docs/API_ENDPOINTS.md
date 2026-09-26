# PORTUS Fase 2 — Endpoints del backend

Base: `http://<raspberry>:5000`. Todas las respuestas son JSON `{"ok": true, "datos": ...}` o
`{"ok": false, "error": "mensaje explícito", "codigo": ...}`. El cuerpo puede ser JSON o formulario.
La columna **Permiso** es la acción de la matriz 2.3 que el servidor valida (`server/auth/permisos.py`);
si el rol no la tiene, responde **403** con el motivo.

## Autenticación
| Método | Ruta | Permiso | Cuerpo / parámetros | Respuesta |
|---|---|---|---|---|
| POST | `/api/auth/login` | público | `{"usuario", "password"}` | usuario público. 401 credenciales, 403 si es TRANSPORTISTA |
| POST | `/api/auth/logout` | público | — | — |
| GET | `/api/auth/yo` | sesión | — | `id, username, nombre, rol, naviera_codigo, pestanas[], permisos{}` |
| GET | `/api/salud` | público | — | estado del servicio |

## Catálogos
| Método | Ruta | Permiso | Notas |
|---|---|---|---|
| GET | `/api/catalogos/constantes` | público | roles, estados, causas, alarmas, comandos, tópicos, matriz de permisos |
| GET | `/api/catalogos/transportistas` | sesión | para el selector del manifiesto |
| GET | `/api/catalogos/contenedores` | sesión | catálogo de la maqueta (NAVIERA ve los libres y los suyos) |
| GET | `/api/contenedores` | CONSULTAR_CONTENEDOR (NAVIERA: propios) | `?q= &naviera= &autorizacion= &ubicacion=` → ubicación, estado, autorización, permanencia |

## Cadena documental
| Método | Ruta | Permiso | Cuerpo |
|---|---|---|---|
| GET | `/api/manifiestos` | VER_MANIFIESTO (NAVIERA: propios) | `?estado= &contenedor=` |
| POST | `/api/manifiestos` | CREAR_MANIFIESTO | `contenedor, tipo, peso_declarado_g, tolerancia_pct?, transportista (id o código), observaciones?` |
| GET | `/api/manifiestos/<id>` | VER_MANIFIESTO | incluye `historial`, `solicitudes_levante`, `observaciones_documentales` |
| POST | `/api/manifiestos/<id>/anular` | ANULAR_MANIFIESTO (propios) | `motivo?` — solo sin turno |
| GET | `/api/declaraciones/pendientes` | PRESENTAR_DECLARACION | manifiestos sin levante |
| POST | `/api/manifiestos/<id>/declaracion` | PRESENTAR_DECLARACION | `numero_declaracion, regimen, descripcion (≥10), valor_declarado (>0)` |
| POST | `/api/manifiestos/<id>/solicitar-levante` | PRESENTAR_DECLARACION | — |
| POST | `/api/manifiestos/<id>/observaciones` | PRESENTAR_DECLARACION | `texto` |
| GET | `/api/declaraciones/seguimiento` | VER_SEGUIMIENTO_AGENTE | `?estado=PENDIENTE\|OTORGADO\|RETENIDO &numero=` |
| GET | `/api/levantes` | OTORGAR_RETENER_LEVANTE | `?estado=PENDIENTE (defecto)\|RETENIDO\|OTORGADO\|TODAS` |
| GET | `/api/levantes/<id>` | OTORGAR_RETENER_LEVANTE | incluye la declaración (Ver declaración) |
| POST | `/api/levantes/<id>/otorgar` | OTORGAR_RETENER_LEVANTE | `canal: VERDE\|ROJO` (obligatorio) |
| POST | `/api/levantes/<id>/retener` | OTORGAR_RETENER_LEVANTE | `motivo` (obligatorio) |

## Operación (TERMINAL)
| Método | Ruta | Permiso | Notas |
|---|---|---|---|
| GET | `/api/sistema/estado` | VER_SINOPTICO | **solo carga inicial** del sinóptico; luego MQTT |
| POST | `/api/sistema/politica-patio` | EMITIR_COMANDOS | `politica: FASE1` |
| POST | `/api/comandos` | EMITIR_COMANDOS | `comando, parametros{}` → 202; resultado por MQTT `portus/srv/comando` |
| GET | `/api/comandos` · `/api/comandos/<id>` | EMITIR_COMANDOS | historial / estado `ENVIADO\|ACEPTADO\|RECHAZADO` + `causa_rechazo` |
| GET | `/api/turnos` | GESTIONAR_TURNOS | `?seccion=activos\|historicos &estado= &tipo= &desde= &hasta= &q=` |
| GET | `/api/turnos/<id>` | GESTIONAR_TURNOS | + `retenciones`, `pesajes` |
| GET | `/api/turnos/<id>/linea-tiempo` | GESTIONAR_TURNOS | eventos con `marca_tiempo`, `origen`, `descripcion`, `valores` |
| POST | `/api/turnos/<id>/retener` | GESTIONAR_TURNOS | RT06, `observacion?` |
| POST | `/api/turnos/<id>/anular` | GESTIONAR_TURNOS | `motivo` (si está Retenido, usar Rechazar) |
| POST | `/api/turnos/<id>/retencion-documental` | ORDENAR_RETENCION_DOCUMENTAL (AUTORIDAD) | RT05, `motivo` |
| GET | `/api/retenciones` | VER_RETENCIONES (AUTORIDAD: solo RT03/RT05) | `?estado=ABIERTA\|RESUELTA &causa=RT01` |
| GET | `/api/retenciones/<id>` | VER_RETENCIONES | |
| POST | `/api/retenciones/<id>/aclarar` | RESOLVER_RETENCION_OPERATIVA o _ADUANERA según causa | `observacion?` |
| POST | `/api/retenciones/<id>/corregir` | además CORREGIR_PESO (solo TERMINAL) | `observacion?` — solo RT01/RT02 |
| POST | `/api/retenciones/<id>/rechazar` | según causa | `motivo` (obligatorio) |
| GET | `/api/parqueo` | VER_SINOPTICO | 3 plazas con vehículo y tiempo |
| POST | `/api/parqueo/<plaza>/liberar` | EMITIR_COMANDOS | reenvía AgujaLiberar (plaza ocupada con retención resuelta) |
| GET | `/api/patio` | VER_SINOPTICO | `posiciones[]` + `inventario[]` (por permanencia desc.) |
| POST | `/api/patio/<pos>/bloquear` · `/liberar` | EMITIR_COMANDOS | envían PosicionBloquear / PosicionLiberar |
| GET | `/api/grua` | VER_SINOPTICO | `?limite=50\|100\|200` estado, trabajos, ciclos, promedio, fallas |
| GET | `/api/grua/exportar.csv` | VER_SINOPTICO | CSV de ciclos y fallas |

## Alarmas, citas, reportes, vinculación (TERMINAL)
| Método | Ruta | Permiso | Notas |
|---|---|---|---|
| GET | `/api/alarmas` | VER_ALARMAS | `?estado=activas\|historicas &severidad=` |
| POST | `/api/alarmas/<id>/reconocer` | RECONOCER_ALARMAS | `comentario?` |
| POST | `/api/alarmas/reconocer-todas` | RECONOCER_ALARMAS | solo BAJA y MEDIA |
| GET | `/api/citas/agenda` | VER_AGENDA_CITAS | `?fecha=YYYY-MM-DD` franjas + citas + `cumplimiento` |
| GET | `/api/citas/franjas-disponibles` | GESTIONAR_CITAS | para reprogramar |
| POST | `/api/citas/<id>/cancelar` | GESTIONAR_CITAS | `motivo?` → notifica |
| POST | `/api/citas/<id>/reprogramar` | GESTIONAR_CITAS | `franja_id` → notifica |
| POST | `/api/franjas/<id>/bloquear` · `/desbloquear` | GESTIONAR_CITAS | |
| POST | `/api/reportes` | GENERAR_REPORTE | `desde, hasta, etiqueta` → 8 métricas |
| GET | `/api/reportes` | GENERAR_REPORTE | reportes guardados |
| GET | `/api/reportes/<id>/exportar.csv` | GENERAR_REPORTE | métricas + detalle de turnos |
| POST | `/api/transportistas/<id\|codigo>/codigo-vinculacion` | GENERAR_CODIGO_VINCULACION | código de 6 car., 60 min, un uso |

## Bot del transportista (encabezado `X-Portus-Token`)
| Método | Ruta | Parámetros |
|---|---|---|
| POST | `/api/bot/vincular` | `chat_id, codigo` |
| GET | `/api/bot/yo` | `?chat_id=` |
| GET | `/api/bot/contenedores-para-cita` | `?chat_id=` |
| GET | `/api/bot/franjas-disponibles` | `?chat_id= &cantidad=6` |
| POST | `/api/bot/citas` | `chat_id, contenedor, franja_id` |
| GET | `/api/bot/citas` | `?chat_id=` (/miscitas) |
| GET | `/api/bot/contenedores/<codigo>` | `?chat_id=` (/estado) |
| GET | `/api/bot/turnos` | `?chat_id=` (/misturnos) |
| GET | `/api/bot/notificaciones/pendientes` | `?limite=50` |
| POST | `/api/bot/notificaciones/<id>/enviada` · `/error` | `error?` |

Chat no vinculado → `403 {"codigo": "NO_VINCULADO"}`.

## Interno (puente / simulador, encabezado `X-Portus-Token`)
| Método | Ruta | Notas |
|---|---|---|
| POST | `/api/interno/eventos` | `{"topico": "portus/evt/...", "mensaje": {id, ts, origen, tipo, seq, datos}}` — misma lógica que MQTT |
| GET | `/api/interno/publicados` | últimos 100 mensajes publicados por el servidor (depurar sin Mosquitto) |
