from datetime import datetime
from typing import Any

from repository import TransportistaRepository


class NotificationService:
    """
    Implementa las nueve notificaciones automáticas exigidas por PORTUS Fase 2.

    El backend real deberá llamar a process_event() cuando ocurra el evento.
    """

    def __init__(self, bot, repo: TransportistaRepository):
        self.bot = bot
        self.repo = repo

    async def _send(self, transportista_id: int, text: str) -> bool:
        chat_id = self.repo.obtener_chat_por_transportista(transportista_id)
        if chat_id is None:
            return False

        await self.bot.send_message(chat_id=chat_id, text=text)
        return True

    async def process_event(
        self,
        event_type: str,
        transportista_id: int,
        payload: dict[str, Any]
    ) -> bool:
        e = event_type.upper()

        if e == "LEVANTE_OTORGADO":
            canal = payload["canal"]
            extra = (
                "\n⚠️ Canal rojo: el vehículo será enviado a verificación."
                if str(canal).lower() == "rojo"
                else ""
            )
            text = (
                "✅ LEVANTE OTORGADO\n\n"
                f"Contenedor: {payload['contenedor']}\n"
                "Autorización: otorgada\n"
                f"Canal asignado: {canal}"
                f"{extra}"
            )

        elif e == "LEVANTE_RETENIDO":
            text = (
                "⛔ LEVANTE RETENIDO\n\n"
                f"Contenedor: {payload['contenedor']}\n"
                f"Motivo: {payload['motivo']}"
            )

        elif e == "CITA_ASIGNADA":
            text = (
                "📅 CITA ASIGNADA\n\n"
                f"Contenedor: {payload['contenedor']}\n"
                f"Fecha: {payload['fecha']}\n"
                f"Ventana: {payload['hora_inicio']} - {payload['hora_fin']}"
            )

        elif e == "RECORDATORIO_CITA_1H":
            text = (
                "⏰ RECORDATORIO DE CITA\n\n"
                "Falta aproximadamente una hora para tu ventana.\n"
                f"Contenedor: {payload['contenedor']}\n"
                f"Ventana: {payload['hora_inicio']} - {payload['hora_fin']}"
            )

        elif e == "VEHICULO_RETENIDO":
            text = (
                "⚠️ VEHÍCULO RETENIDO\n\n"
                f"Vehículo: {payload['vehiculo']}\n"
                f"Contenedor: {payload['contenedor']}\n"
                f"Causa: {payload['causa']}"
            )
            if str(payload.get("causa", "")).lower() == "peso":
                text += (
                    f"\nPeso declarado: {payload['peso_declarado']}"
                    f"\nPeso medido: {payload['peso_medido']}"
                    f"\nDiferencia: {payload['diferencia']}"
                )

        elif e == "RETENCION_RESUELTA":
            resolucion = payload["resolucion"]
            text = (
                "✅ RETENCIÓN RESUELTA\n\n"
                f"Vehículo: {payload['vehiculo']}\n"
                f"Contenedor: {payload['contenedor']}\n"
                f"Resolución: {resolucion}"
            )
            if str(resolucion).lower() == "corregir":
                text += f"\nNuevo peso declarado: {payload['nuevo_peso_declarado']}"
            elif str(resolucion).lower() == "rechazar":
                text += f"\nMotivo: {payload['motivo']}"

        elif e == "CITA_ACTUALIZADA":
            situacion = payload["situacion"]
            text = (
                "📅 CITA ACTUALIZADA\n\n"
                f"Contenedor: {payload['contenedor']}\n"
                f"Situación: {situacion}"
            )
            if str(situacion).lower() == "reprogramada":
                text += (
                    f"\nNueva ventana: {payload['hora_inicio']} - "
                    f"{payload['hora_fin']}"
                )

        elif e == "TURNO_CERRADO":
            text = (
                "🏁 TURNO CERRADO\n\n"
                f"Vehículo: {payload['vehiculo']}\n"
                f"Contenedor: {payload['contenedor']}\n"
                f"Operación: {payload['tipo_operacion']}\n"
                f"Tiempo total en terminal: {payload['tiempo_total']}"
            )

        elif e == "TURNO_ANULADO":
            text = (
                "❌ TURNO ANULADO\n\n"
                f"Vehículo: {payload['vehiculo']}\n"
                f"Contenedor: {payload['contenedor']}"
            )
            if payload.get("causa"):
                text += f"\nCausa: {payload['causa']}"

        else:
            raise ValueError(f"Evento de notificación desconocido: {event_type}")

        return await self._send(transportista_id, text)


async def revisar_recordatorios_cita(context):
    """
    Job periódico: envía el aviso obligatorio cuando falta una hora
    para la ventana asignada.
    """
    repo = context.application.bot_data["repo"]
    service = NotificationService(context.bot, repo)

    now = datetime.now().replace(second=0, microsecond=0)

    for cita in repo.citas_para_recordatorio(now.isoformat(timespec="minutes")):
        inicio = datetime.fromisoformat(cita["inicio"])
        fin = datetime.fromisoformat(cita["fin"])

        enviado = await service.process_event(
            "RECORDATORIO_CITA_1H",
            cita["transportista_id"],
            {
                "contenedor": cita["contenedor"],
                "hora_inicio": inicio.strftime("%H:%M"),
                "hora_fin": fin.strftime("%H:%M")
            }
        )

        if enviado:
            repo.marcar_recordatorio_enviado(cita["id"])
