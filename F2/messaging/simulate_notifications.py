"""
Envía las nueve notificaciones automáticas a un transportista vinculado.
Úsalo SOLO para probar el módulo messaging/ mientras el backend no existe.

Ejemplo:
    python simulate_notifications.py 1
"""

import asyncio
import sys

from telegram import Bot

from config import DATA_FILE, TELEGRAM_BOT_TOKEN
from mock_repository import MockRepository
from notifications import NotificationService


EVENTOS = [
    (
        "LEVANTE_OTORGADO",
        {
            "contenedor": "CONT-001",
            "canal": "Rojo"
        }
    ),
    (
        "LEVANTE_RETENIDO",
        {
            "contenedor": "CONT-001",
            "motivo": "Documentación pendiente"
        }
    ),
    (
        "CITA_ASIGNADA",
        {
            "contenedor": "CONT-001",
            "fecha": "05/10/2026",
            "hora_inicio": "10:00",
            "hora_fin": "10:15"
        }
    ),
    (
        "RECORDATORIO_CITA_1H",
        {
            "contenedor": "CONT-001",
            "hora_inicio": "10:00",
            "hora_fin": "10:15"
        }
    ),
    (
        "VEHICULO_RETENIDO",
        {
            "vehiculo": "C123ABC",
            "contenedor": "CONT-001",
            "causa": "Peso",
            "peso_declarado": "1200 g",
            "peso_medido": "1310 g",
            "diferencia": "110 g"
        }
    ),
    (
        "RETENCION_RESUELTA",
        {
            "vehiculo": "C123ABC",
            "contenedor": "CONT-001",
            "resolucion": "Corregir",
            "nuevo_peso_declarado": "1310 g"
        }
    ),
    (
        "CITA_ACTUALIZADA",
        {
            "contenedor": "CONT-001",
            "situacion": "Reprogramada",
            "hora_inicio": "11:00",
            "hora_fin": "11:15"
        }
    ),
    (
        "TURNO_CERRADO",
        {
            "vehiculo": "C123ABC",
            "contenedor": "CONT-001",
            "tipo_operacion": "Retiro",
            "tiempo_total": "42 min"
        }
    ),
    (
        "TURNO_ANULADO",
        {
            "vehiculo": "C123ABC",
            "contenedor": "CONT-001",
            "causa": "Operación cancelada por la terminal"
        }
    )
]


async def main():
    transportista_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1

    repo = MockRepository(DATA_FILE)
    chat_id = repo.obtener_chat_por_transportista(transportista_id)

    if chat_id is None:
        print(
            "Ese transportista todavía no está vinculado a Telegram.\n"
            "Primero ejecuta el bot y usa /vincular con su código."
        )
        return

    bot = Bot(TELEGRAM_BOT_TOKEN)
    service = NotificationService(bot, repo)

    async with bot:
        for event_type, payload in EVENTOS:
            print(f"Enviando {event_type}...")
            await service.process_event(
                event_type,
                transportista_id,
                payload
            )
            await asyncio.sleep(0.7)

    print("Listo: se enviaron las nueve notificaciones de prueba.")


if __name__ == "__main__":
    asyncio.run(main())
