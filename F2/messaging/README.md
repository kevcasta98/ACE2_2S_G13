# PORTUS – Bot del Transportista
## Manual de instalación, configuración, uso y pruebas

Este documento reúne todas las instrucciones necesarias para trabajar con el módulo `messaging/` del proyecto **PORTUS – Fase 2**.

El objetivo de este módulo es implementar el canal de mensajería del rol **TRANSPORTISTA**, el cual opera exclusivamente desde una plataforma de mensajería y no desde la aplicación web.

---

# 1. Ubicación dentro del proyecto

La estructura general del proyecto es:

```text
PORTUS/
├── controller/
├── bridge/
├── server/
├── web/
├── messaging/
├── simulator/
├── database/
└── docs/
```

La parte correspondiente al bot se encuentra en:

```text
PORTUS/
└── messaging/
```

La versión desarrollada contiene:

```text
messaging/
├── bot.py
├── config.py
├── handlers.py
├── messages.py
├── mock_repository.py
├── notifications.py
├── repository.py
├── requirements.txt
├── reset_mock.py
├── simulate_notifications.py
├── .env.example
├── .gitignore
├── README.md
└── tests/
    └── test_repository.py
```

---

# 2. Funcionamiento general

Durante el desarrollo, el bot funciona sin depender todavía del backend real.

Flujo actual:

```text
Telegram
   ↓
handlers.py
   ↓
TransportistaRepository
   ↓
MockRepository
   ↓
Datos simulados
```

Cuando el backend esté listo, el flujo deberá cambiar a:

```text
Telegram
   ↓
handlers.py
   ↓
TransportistaRepository
   ↓
ApiRepository
   ↓
server/
   ↓
Base de datos
```

La ventaja de esta estructura es que no será necesario reescribir los comandos del bot al momento de integrar el backend real.

---

# 3. Crear el bot en Telegram

Abrir Telegram y buscar:

```text
@BotFather
```

Enviar:

```text
/newbot
```

BotFather solicitará:

1. Nombre del bot.
2. Nombre de usuario del bot.

Ejemplo:

```text
Nombre:
PORTUS Transportista

Usuario:
portus_transportista_bot
```

El nombre de usuario debe terminar en:

```text
bot
```

BotFather entregará un token similar a:

```text
1234567890:AAxxxxxxxxxxxxxxxxxxxxxxxx
```

Ese token es privado.

No debe:

- subirse a GitHub;
- incluirse en capturas públicas;
- compartirse en documentación;
- colocarse directamente dentro de `bot.py`.

---

# 4. Preparar el entorno

Abrir una terminal dentro del módulo:

```bash
cd PORTUS/messaging
```

Crear el entorno virtual:

```bash
python3 -m venv .venv
```

Activarlo en Linux o macOS:

```bash
source .venv/bin/activate
```

En Windows:

```powershell
.venv\Scripts\activate
```

Instalar dependencias:

```bash
pip install -r requirements.txt
```

---

# 5. Configurar variables de entorno

Copiar el archivo de ejemplo:

```bash
cp .env.example .env
```

Editar:

```text
.env
```

Colocar:

```env
TELEGRAM_BOT_TOKEN=TU_TOKEN_REAL
PORTUS_DATA_FILE=data/mock_db.json
PORTUS_TIMEZONE=America/Guatemala
```

Ejemplo:

```env
TELEGRAM_BOT_TOKEN=1234567890:AAxxxxxxxxxxxxxxxx
PORTUS_DATA_FILE=data/mock_db.json
PORTUS_TIMEZONE=America/Guatemala
```

El archivo `.env` está incluido en `.gitignore`, por lo que no debe subirse al repositorio.

---

# 6. Reiniciar los datos simulados

Cuando se actualice la estructura del módulo o se quieran generar datos nuevos:

```bash
python reset_mock.py
```

Después ejecutar nuevamente:

```bash
python bot.py
```

Al iniciar por primera vez se generan datos simulados y códigos de vinculación.

Ejemplo:

```text
ABC123 -> Transportes Quetzal
XYZ789 -> Carga del Pacífico
```

Los códigos se utilizan únicamente para pruebas.

---

# 7. Ejecutar el bot

Dentro de:

```text
PORTUS/messaging/
```

ejecutar:

```bash
python bot.py
```

La terminal debería mostrar:

```text
PORTUS - Bot de transportista iniciado
Modo actual: datos simulados
Presiona Ctrl+C para detenerlo.
```

Mientras se realizan pruebas, esta terminal debe permanecer abierta.

---

# 8. Vinculación del transportista

El usuario debe vincular su cuenta de Telegram con un transportista registrado.

Formato:

```text
/vincular CODIGO
```

Ejemplo:

```text
/vincular ABC123
```

El código debe cumplir:

- seis caracteres;
- solo puede utilizarse una vez;
- expira después de 60 minutos;
- está asociado a un transportista específico.

Respuesta esperada:

```text
✅ Vinculación completada.

Transportista: Transportes Quetzal

Usa /inicio para ver todos los comandos.
```

Si el código no existe:

```text
❌ Código de vinculación inválido.
```

Si ya fue utilizado:

```text
❌ El código de vinculación ya fue utilizado.
```

Si expiró:

```text
❌ El código de vinculación está vencido.
Solicita uno nuevo al operador.
```

---

# 9. Usuario no vinculado

Un usuario que todavía no se haya vinculado no debe poder utilizar las funciones del bot.

Si intenta usar cualquier comando, el bot responde:

```text
🔐 Tu cuenta de mensajería aún no está vinculada a PORTUS.

Usa:
/vincular CODIGO
```

Esto evita que usuarios no autorizados consulten información.

---

# 10. Comandos obligatorios

El bot implementa siete comandos principales.

```text
/inicio
/vincular CODIGO
/cita
/miscitas
/estado CONTENEDOR
/misturnos
/ayuda
```

---

# 11. Comando /inicio

Uso:

```text
/inicio
```

Muestra:

- saludo;
- nombre de PORTUS;
- nombre del transportista;
- lista completa de comandos.

Ejemplo:

```text
🚢 PORTUS — Terminal Portuaria

Hola, Transportes Quetzal.

Comandos disponibles:
/inicio
/vincular CODIGO
/cita
/miscitas
/estado CONTENEDOR
/misturnos
/ayuda
```

---

# 12. Comando /cita

Uso:

```text
/cita
```

No recibe fecha ni hora manualmente.

El flujo es:

```text
/cita
   ↓
Contenedores con levante otorgado
   ↓
Seleccionar contenedor
   ↓
Mostrar franjas disponibles
   ↓
Seleccionar franja
   ↓
Confirmar cita
```

Solo aparecen contenedores:

- pertenecientes al transportista;
- con levante otorgado;
- que todavía no tengan cita.

Ejemplo:

```text
📦 Selecciona el contenedor para el que deseas solicitar una cita:

[ CONT-001 · Canal Verde ]
[ CONT-002 · Canal Rojo ]
```

Después se muestran franjas de 15 minutos:

```text
[ 26/09 16:15 - 16:30 (0/2) ]
[ 26/09 16:30 - 16:45 (0/2) ]
[ 26/09 16:45 - 17:00 (0/2) ]
```

El valor:

```text
(0/2)
```

significa:

```text
0 citas asignadas / capacidad máxima 2
```

Al seleccionar una franja:

```text
✅ CITA CONFIRMADA

Contenedor: CONT-001
Fecha: 26/09/2026
Hora de inicio: 16:15
Hora de fin: 16:30
```

También se genera automáticamente la notificación de cita asignada.

---

# 13. Comando /miscitas

Uso:

```text
/miscitas
```

Muestra las citas del transportista.

Para cada cita debe mostrarse:

- contenedor;
- fecha;
- hora de inicio;
- hora de fin;
- estado.

Ejemplo:

```text
📅 MIS CITAS

Contenedor: CONT-001
Fecha: 26/09/2026
Ventana: 16:15 - 16:30
Estado: Programada
```

Los estados contemplados son:

```text
Programada
Cumplida
Vencida
Cancelada
```

---

# 14. Comando /estado

Uso:

```text
/estado CONTENEDOR
```

Ejemplo:

```text
/estado CONT-001
```

Debe mostrar:

- identificador;
- estado actual;
- ubicación;
- reloj de permanencia;
- estado de autorización;
- canal asignado.

Ejemplo:

```text
📦 ESTADO DEL CONTENEDOR

Contenedor: CONT-001
Estado actual: En patio
Ubicación: P2-N1
Permanencia: 3 h 18 min
Autorización: Otorgado
Canal asignado: Verde
```

---

# 15. Seguridad entre transportistas

Un transportista nunca debe poder consultar información perteneciente a otro.

Ejemplo:

```text
Transportista 1:
CONT-001
CONT-002

Transportista 2:
CONT-900
```

Si el transportista 1 ejecuta:

```text
/estado CONT-900
```

debe responder:

```text
No tienes carga asociada a ese identificador.
```

Nunca debe mostrar:

- ubicación;
- peso;
- autorización;
- citas;
- turnos;
- información documental

de cargas de otro transportista.

---

# 16. Comando /misturnos

Uso:

```text
/misturnos
```

Muestra únicamente las operaciones activas del transportista.

Para cada turno:

- vehículo;
- contenedor;
- tipo de operación;
- estado;
- estación.

Ejemplo:

```text
🎫 MIS TURNOS ACTIVOS

Vehículo: C123ABC
Contenedor: CONT-001
Operación: Retiro
Estado: EnRuta
Estación: Ruta interna
```

---

# 17. Comando /ayuda

Uso:

```text
/ayuda
```

Muestra nuevamente todos los comandos disponibles con su descripción.

---

# 18. Comandos o mensajes desconocidos

El bot nunca debe dejar un mensaje sin respuesta.

Por ejemplo:

```text
/hola
```

o:

```text
que onda
```

Respuesta:

```text
❓ Comando no reconocido.

Usa /ayuda para consultar la lista de comandos disponibles.
```

---

# 19. Notificaciones automáticas

PORTUS Fase 2 exige nueve notificaciones automáticas.

Estas notificaciones se envían directamente al chat privado de Telegram del transportista vinculado.

Flujo:

```text
Evento de PORTUS
      ↓
Backend
      ↓
Transportista propietario
      ↓
chat_id de Telegram
      ↓
Bot PORTUS
      ↓
Teléfono del transportista
```

---

# 20. Notificación 1 – Levante otorgado

Evento:

```text
La autoridad otorga el levante
```

Ejemplo:

```text
✅ LEVANTE OTORGADO

Contenedor: CONT-001
Autorización: otorgada
Canal asignado: Verde
```

Si el canal es rojo:

```text
✅ LEVANTE OTORGADO

Contenedor: CONT-001
Autorización: otorgada
Canal asignado: Rojo

⚠️ Canal rojo: el vehículo será enviado a verificación.
```

---

# 21. Notificación 2 – Levante retenido

Ejemplo:

```text
⛔ LEVANTE RETENIDO

Contenedor: CONT-001
Motivo: Documentación pendiente
```

---

# 22. Notificación 3 – Cita asignada

Ejemplo:

```text
📅 CITA ASIGNADA

Contenedor: CONT-001
Fecha: 05/10/2026
Ventana: 10:00 - 10:15
```

---

# 23. Notificación 4 – Falta una hora para la cita

El bot revisa periódicamente las citas programadas.

Cuando falta aproximadamente una hora:

```text
⏰ RECORDATORIO DE CITA

Falta aproximadamente una hora para tu ventana.

Contenedor: CONT-001
Ventana: 10:00 - 10:15
```

Cada recordatorio debe enviarse una sola vez.

---

# 24. Notificación 5 – Vehículo retenido

Ejemplo:

```text
⚠️ VEHÍCULO RETENIDO

Vehículo: C123ABC
Contenedor: CONT-001
Causa: Peso
Peso declarado: 1200 g
Peso medido: 1310 g
Diferencia: 110 g
```

Cuando la causa no sea peso, no es obligatorio mostrar los tres valores de peso.

---

# 25. Notificación 6 – Retención resuelta

Ejemplo con corrección:

```text
✅ RETENCIÓN RESUELTA

Vehículo: C123ABC
Contenedor: CONT-001
Resolución: Corregir
Nuevo peso declarado: 1310 g
```

Ejemplo con rechazo:

```text
✅ RETENCIÓN RESUELTA

Vehículo: C123ABC
Contenedor: CONT-001
Resolución: Rechazar
Motivo: Peso no autorizado
```

---

# 26. Notificación 7 – Cita cancelada o reprogramada

Cancelada:

```text
📅 CITA ACTUALIZADA

Contenedor: CONT-001
Situación: Cancelada
```

Reprogramada:

```text
📅 CITA ACTUALIZADA

Contenedor: CONT-001
Situación: Reprogramada
Nueva ventana: 11:00 - 11:15
```

---

# 27. Notificación 8 – Turno cerrado

Ejemplo:

```text
🏁 TURNO CERRADO

Vehículo: C123ABC
Contenedor: CONT-001
Operación: Retiro
Tiempo total en terminal: 42 min
```

---

# 28. Notificación 9 – Turno anulado

Ejemplo:

```text
❌ TURNO ANULADO

Vehículo: C123ABC
Contenedor: CONT-001
Causa: Operación cancelada por la terminal
```

---

# 29. Cómo probar las 9 notificaciones

Primero el transportista debe estar vinculado.

Ejemplo:

```text
/vincular ABC123
```

Dejar corriendo:

```bash
python bot.py
```

Abrir una segunda terminal.

Activar el entorno:

```bash
cd PORTUS/messaging
source .venv/bin/activate
```

Ejecutar:

```bash
python simulate_notifications.py 1
```

El número:

```text
1
```

corresponde al:

```text
transportista_id = 1
```

El teléfono vinculado a ese transportista recibirá las nueve notificaciones.

---

# 30. Qué hace simulate_notifications.py

Este archivo existe únicamente para desarrollo.

Actualmente:

```text
simulate_notifications.py
          ↓
NotificationService
          ↓
Telegram
```

Cuando el backend real esté listo:

```text
server/
   ↓
Evento real
   ↓
NotificationService
   ↓
Telegram
```

Por lo tanto, `simulate_notifications.py` no formará parte del flujo real de producción.

---

# 31. Archivo notifications.py

Este archivo contiene:

```text
NotificationService
```

El backend deberá llamar al servicio cuando ocurra uno de los eventos.

La función principal es:

```python
process_event(
    event_type,
    transportista_id,
    payload
)
```

Ejemplo conceptual:

```python
await notification_service.process_event(
    "LEVANTE_OTORGADO",
    1,
    {
        "contenedor": "CONT-001",
        "canal": "Verde"
    }
)
```

El módulo de mensajería se encarga de:

1. buscar el chat asociado al transportista;
2. construir el mensaje;
3. enviar la notificación correcta.

---

# 32. Archivo repository.py

Define el contrato entre `messaging/` y el sistema PORTUS.

Algunas funciones principales son:

```python
vincular_chat(...)
obtener_transportista_por_chat(...)
obtener_chat_por_transportista(...)
listar_contenedores_elegibles_cita(...)
listar_franjas_disponibles(...)
crear_cita(...)
listar_citas(...)
obtener_estado_contenedor(...)
listar_turnos_activos(...)
```

Los handlers no deben consultar directamente SQLite.

La idea correcta es:

```text
handlers
   ↓
repository
   ↓
implementación
```

---

# 33. Archivo mock_repository.py

Actualmente implementa:

```text
TransportistaRepository
```

utilizando datos simulados.

Sirve para:

- desarrollar el bot sin backend;
- probar comandos;
- probar citas;
- probar permisos;
- probar aislamiento;
- probar notificaciones.

Posteriormente deberá crearse:

```text
api_repository.py
```

o una implementación equivalente conectada al backend.

---

# 34. Integración futura con server/

Cuando el compañero encargado del backend termine sus servicios, deberán definirse endpoints equivalentes a las operaciones del repositorio.

Ejemplo conceptual:

```text
POST /api/messaging/vincular

GET /api/transportistas/{id}/contenedores-elegibles

GET /api/citas/franjas

POST /api/citas

GET /api/transportistas/{id}/citas

GET /api/transportistas/{id}/contenedores/{contenedor}

GET /api/transportistas/{id}/turnos
```

Los nombres finales de las rutas deberán acordarse con el equipo.

No es obligatorio usar exactamente estos nombres; lo importante es conservar el contrato funcional.

---

# 35. Pruebas unitarias

Ejecutar:

```bash
python -m unittest discover -s tests -v
```

Actualmente se prueban condiciones como:

- código de vinculación de un solo uso;
- aislamiento entre transportistas;
- creación de citas;
- contenedor con levante;
- contenedor sin cita previa.

---

# 36. Prueba completa recomendada

## Paso 1

Iniciar:

```bash
python bot.py
```

## Paso 2

Vincular:

```text
/vincular ABC123
```

## Paso 3

Probar:

```text
/inicio
```

## Paso 4

Solicitar cita:

```text
/cita
```

Seleccionar un contenedor y una franja.

## Paso 5

Consultar:

```text
/miscitas
```

## Paso 6

Consultar contenedor propio:

```text
/estado CONT-001
```

## Paso 7

Intentar consultar carga ajena:

```text
/estado CONT-900
```

Debe ser rechazada.

## Paso 8

Consultar:

```text
/misturnos
```

## Paso 9

Probar:

```text
/ayuda
```

## Paso 10

Probar comando inválido:

```text
/hola
```

Debe responder.

## Paso 11

En una segunda terminal:

```bash
python simulate_notifications.py 1
```

Verificar que lleguen las nueve notificaciones.