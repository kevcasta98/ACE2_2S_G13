from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from messages import MENSAJE_VINCULACION_REQUERIDA, lista_comandos
from notifications import NotificationService
from repository import TransportistaRepository


def _repo(context: ContextTypes.DEFAULT_TYPE) -> TransportistaRepository:
    return context.application.bot_data["repo"]


async def _require_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    transportista = _repo(context).obtener_transportista_por_chat(
        update.effective_chat.id
    )
    if not transportista:
        if update.message:
            await update.message.reply_text(MENSAJE_VINCULACION_REQUERIDA)
        elif update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(
                MENSAJE_VINCULACION_REQUERIDA
            )
        return None
    return transportista


async def inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    transportista = await _require_link(update, context)
    if not transportista:
        return

    await update.message.reply_text(
        f"🚢 PORTUS — Terminal Portuaria\n\n"
        f"Hola, {transportista['nombre']}.\n\n"
        f"Comandos disponibles:\n{lista_comandos()}"
    )


async def vincular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text(
            "Uso correcto:\n/vincular CODIGO\n\n"
            "El código debe tener seis caracteres."
        )
        return

    codigo = context.args[0].strip().upper()
    if len(codigo) != 6:
        await update.message.reply_text(
            "❌ Código inválido. El código de vinculación debe tener seis caracteres."
        )
        return

    transportista, resultado = _repo(context).vincular_chat(
        update.effective_chat.id,
        codigo
    )

    if resultado == "VENCIDO":
        await update.message.reply_text(
            "❌ El código de vinculación está vencido. Solicita uno nuevo al operador."
        )
        return

    if resultado == "USADO":
        await update.message.reply_text(
            "❌ El código de vinculación ya fue utilizado."
        )
        return

    if not transportista:
        await update.message.reply_text(
            "❌ Código de vinculación inválido."
        )
        return

    await update.message.reply_text(
        "✅ Vinculación completada.\n\n"
        f"Transportista: {transportista['nombre']}\n\n"
        f"Usa /inicio para ver todos los comandos."
    )


async def cita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    transportista = await _require_link(update, context)
    if not transportista:
        return

    contenedores = _repo(context).listar_contenedores_elegibles_cita(
        transportista["id"]
    )

    if not contenedores:
        await update.message.reply_text(
            "No tienes contenedores con levante otorgado que estén pendientes de cita."
        )
        return

    keyboard = [
        [InlineKeyboardButton(
            f"{c['id']} · Canal {c.get('canal', 'N/D')}",
            callback_data=f"cita_contenedor:{c['id']}"
        )]
        for c in contenedores
    ]

    await update.message.reply_text(
        "📦 Selecciona el contenedor para el que deseas solicitar una cita:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def cita_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    transportista = await _require_link(update, context)
    if not transportista:
        return

    data = query.data

    if data.startswith("cita_contenedor:"):
        contenedor = data.split(":", 1)[1]
        franjas = _repo(context).listar_franjas_disponibles(limite=6)

        if not franjas:
            await query.edit_message_text(
                "No hay franjas con capacidad disponible en este momento."
            )
            return

        context.user_data["cita_contenedor"] = contenedor

        keyboard = []
        for f in franjas:
            inicio = datetime.fromisoformat(f["inicio"])
            fin = datetime.fromisoformat(f["fin"])
            label = (
                f"{inicio.strftime('%d/%m %H:%M')} - {fin.strftime('%H:%M')} "
                f"({f['ocupadas']}/{f['capacidad']})"
            )
            keyboard.append([
                InlineKeyboardButton(
                    label,
                    callback_data=f"cita_franja:{f['id']}"
                )
            ])

        await query.edit_message_text(
            f"📅 Contenedor: {contenedor}\n\n"
            "Selecciona una franja con capacidad disponible:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data.startswith("cita_franja:"):
        contenedor = context.user_data.get("cita_contenedor")
        if not contenedor:
            await query.edit_message_text(
                "La solicitud de cita expiró. Ejecuta /cita nuevamente."
            )
            return

        franja_id = int(data.split(":", 1)[1])

        try:
            nueva = _repo(context).crear_cita(
                transportista["id"],
                contenedor,
                franja_id
            )
        except ValueError as exc:
            await query.edit_message_text(f"❌ {exc}")
            return

        inicio = datetime.fromisoformat(nueva["inicio"])
        fin = datetime.fromisoformat(nueva["fin"])

        await query.edit_message_text(
            "✅ CITA CONFIRMADA\n\n"
            f"Contenedor: {nueva['contenedor']}\n"
            f"Fecha: {inicio.strftime('%d/%m/%Y')}\n"
            f"Hora de inicio: {inicio.strftime('%H:%M')}\n"
            f"Hora de fin: {fin.strftime('%H:%M')}"
        )

        # La asignación de cita es una de las nueve notificaciones obligatorias.
        service = NotificationService(context.bot, _repo(context))
        await service.process_event(
            "CITA_ASIGNADA",
            transportista["id"],
            {
                "contenedor": nueva["contenedor"],
                "fecha": inicio.strftime("%d/%m/%Y"),
                "hora_inicio": inicio.strftime("%H:%M"),
                "hora_fin": fin.strftime("%H:%M"),
            }
        )


async def miscitas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    transportista = await _require_link(update, context)
    if not transportista:
        return

    citas = _repo(context).listar_citas(transportista["id"])

    if not citas:
        await update.message.reply_text("No tienes citas registradas.")
        return

    lines = ["📅 MIS CITAS", ""]
    for c in citas:
        inicio = datetime.fromisoformat(c["inicio"])
        fin = datetime.fromisoformat(c["fin"])
        lines.extend([
            f"Contenedor: {c['contenedor']}",
            f"Fecha: {inicio.strftime('%d/%m/%Y')}",
            f"Ventana: {inicio.strftime('%H:%M')} - {fin.strftime('%H:%M')}",
            f"Estado: {c['estado']}",
            ""
        ])

    await update.message.reply_text("\n".join(lines).rstrip())


async def estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    transportista = await _require_link(update, context)
    if not transportista:
        return

    if len(context.args) != 1:
        await update.message.reply_text(
            "Uso correcto:\n/estado CONTENEDOR\n\n"
            "Ejemplo:\n/estado CONT-001"
        )
        return

    contenedor_id = context.args[0]
    c = _repo(context).obtener_estado_contenedor(
        transportista["id"],
        contenedor_id
    )

    if not c:
        await update.message.reply_text(
            "No tienes carga asociada a ese identificador."
        )
        return

    ubicacion = c["ubicacion"] or "No se encuentra en patio"
    canal = c.get("canal") or "Sin asignar"

    await update.message.reply_text(
        "📦 ESTADO DEL CONTENEDOR\n\n"
        f"Contenedor: {c['id']}\n"
        f"Estado actual: {c['estado']}\n"
        f"Ubicación: {ubicacion}\n"
        f"Permanencia: {c['permanencia']}\n"
        f"Autorización: {c['levante']}\n"
        f"Canal asignado: {canal}"
    )


async def misturnos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    transportista = await _require_link(update, context)
    if not transportista:
        return

    turnos = _repo(context).listar_turnos_activos(transportista["id"])

    if not turnos:
        await update.message.reply_text(
            "No tienes operaciones en curso."
        )
        return

    lines = ["🎫 MIS TURNOS ACTIVOS", ""]
    for t in turnos:
        lines.extend([
            f"Vehículo: {t['vehiculo']}",
            f"Contenedor: {t['contenedor']}",
            f"Operación: {t['tipo_operacion']}",
            f"Estado: {t['estado']}",
            f"Estación: {t['estacion']}",
            ""
        ])

    await update.message.reply_text("\n".join(lines).rstrip())


async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    transportista = await _require_link(update, context)
    if not transportista:
        return

    await update.message.reply_text(
        "ℹ️ COMANDOS DE PORTUS\n\n" + lista_comandos()
    )


async def comando_desconocido(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # La regla del enunciado exige que el servicio nunca quede sin responder.
    transportista = _repo(context).obtener_transportista_por_chat(
        update.effective_chat.id
    )

    if not transportista:
        await update.message.reply_text(MENSAJE_VINCULACION_REQUERIDA)
        return

    await update.message.reply_text(
        "❓ Comando no reconocido.\n\n"
        "Usa /ayuda para consultar la lista de comandos disponibles."
    )
