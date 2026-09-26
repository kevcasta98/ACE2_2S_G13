from abc import ABC, abstractmethod
from typing import Optional


class TransportistaRepository(ABC):
    @abstractmethod
    def vincular_chat(self, chat_id: int, codigo: str) -> tuple[Optional[dict], str]:
        """Retorna (transportista, resultado)."""
        raise NotImplementedError

    @abstractmethod
    def obtener_transportista_por_chat(self, chat_id: int) -> Optional[dict]:
        raise NotImplementedError

    @abstractmethod
    def obtener_chat_por_transportista(self, transportista_id: int) -> Optional[int]:
        raise NotImplementedError

    @abstractmethod
    def listar_contenedores_elegibles_cita(self, transportista_id: int) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def listar_franjas_disponibles(self, limite: int = 6) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def crear_cita(
        self,
        transportista_id: int,
        contenedor_id: str,
        franja_id: int
    ) -> dict:
        raise NotImplementedError

    @abstractmethod
    def listar_citas(self, transportista_id: int) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def obtener_estado_contenedor(
        self,
        transportista_id: int,
        contenedor_id: str
    ) -> Optional[dict]:
        raise NotImplementedError

    @abstractmethod
    def listar_turnos_activos(self, transportista_id: int) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def citas_para_recordatorio(self, now_iso: str) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def marcar_recordatorio_enviado(self, cita_id: int) -> None:
        raise NotImplementedError
