# PORTUS Fase 2 — Backend (Compañero 1)

Servidor Flask + SQLite + MQTT: usuarios, sesiones, permisos por rol validados en el servidor, cadena
documental, turnos, retenciones, parqueo, patio, grúa, alarmas, citas, reportes, API del bot e ingesta
de eventos del controlador.

```
server/
├── run.py              arranque y comandos (init-db, crear-usuario)
├── config.py           variables de entorno
├── app/                create_app(): registra rutas, errores, MQTT y tareas
├── auth/               sesion.py (login, hash), permisos.py (matriz 2.3, @requiere)
├── models/             constantes.py (NOMBRES OFICIALES), db.py, errores.py, semilla.py
├── routes/             API JSON /api/... (auth, documental, operacion, gestion, bot, interno, catalogos)
├── services/           lógica: turnos, retenciones, parqueo, patio, citas, cadena_documental,
│                       operacion (eventos del controlador), comandos, alarmas, notificaciones, metricas, tareas
└── tests/              test_flujo_completo.py (escenarios E01–E15 sin hardware)
```

## Arranque
```bash
cd F2/server
python3 -m venv .venv
source .venv/bin/activate          # fish: source .venv/bin/activate.fish
pip install -r requirements.txt
python run.py init-db --demo       # crea ../database/portus.db con los usuarios de prueba (clave 1234)
python run.py                      # http://0.0.0.0:5000
python tests/test_flujo_completo.py
```

Variables de entorno: `PORTUS_DB`, `PORTUS_SECRET_KEY`, `PORTUS_TOKEN_INTERNO`, `PORTUS_MQTT` (1/0),
`PORTUS_MQTT_HOST`, `PORTUS_MQTT_PORT`, `PORTUS_PORT`, `PORTUS_TAREAS` (1/0), `PORTUS_AGENDA_APERTURA`, `PORTUS_AGENDA_CIERRE`.
En la Raspberry cambiar `PORTUS_SECRET_KEY` y `PORTUS_TOKEN_INTERNO`.

Documentación para el equipo: [`../docs/VARIABLES_EQUIPO.md`](../docs/VARIABLES_EQUIPO.md),
[`../docs/API_ENDPOINTS.md`](../docs/API_ENDPOINTS.md), [`../docs/BASE_DE_DATOS.md`](../docs/BASE_DE_DATOS.md).
