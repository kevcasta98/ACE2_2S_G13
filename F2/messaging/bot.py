from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from config import DATA_FILE, TELEGRAM_BOT_TOKEN
from handlers import (
    ayuda,
    cita,
    cita_callback,
    comando_desconocido,
    estado,
    inicio,
    miscitas,
    misturnos,
    vincular,
)
from mock_repository import MockRepository
from notifications import revisar_recordatorios_cita

import asyncio

def main():
    repo = MockRepository(DATA_FILE)

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    app.bot_data["repo"] = repo

    app.add_handler(CommandHandler("inicio", inicio))
    app.add_handler(CommandHandler("start", inicio))
    app.add_handler(CommandHandler("vincular", vincular))
    app.add_handler(CommandHandler("cita", cita))
    app.add_handler(CommandHandler("miscitas", miscitas))
    app.add_handler(CommandHandler("estado", estado))
    app.add_handler(CommandHandler("misturnos", misturnos))
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(CommandHandler("help", ayuda))

    app.add_handler(
        CallbackQueryHandler(cita_callback, pattern=r"^cita_(contenedor|franja):")
    )

    # Cualquier comando o texto no reconocido recibe respuesta.
    app.add_handler(
        MessageHandler(filters.ALL, comando_desconocido)
    )

    # Revisa cada minuto si alguna cita necesita el recordatorio de una hora.
    if app.job_queue is not None:
        app.job_queue.run_repeating(
            revisar_recordatorios_cita,
            interval=60,
            first=10
        )

    print("PORTUS - Bot de transportista iniciado")
    print("Modo actual: datos simulados")
    print("Presiona Ctrl+C para detenerlo.")


    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    app.run_polling()


if __name__ == "__main__":
    main()
