import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from repository import TransportistaRepository


ESTADOS_CITA = {"Programada", "Cumplida", "Vencida", "Cancelada"}
ESTADOS_TURNO_CERRADOS = {"Finalizado", "Anulado"}


class MockRepository(TransportistaRepository):
    """
    Persistencia simulada para desarrollar messaging/ sin depender de server/.
    """

    def __init__(self, data_file: Path):
        self.data_file = Path(data_file)
        self._ensure_file()

    def _ensure_file(self):
        if self.data_file.exists():
            return

        now = datetime.now()
        franjas = []
        slot_id = 1

        # Crea franjas futuras de prueba de 15 minutos.
        start = (now + timedelta(hours=2)).replace(second=0, microsecond=0)
        minute = (start.minute // 15 + 1) * 15
        if minute == 60:
            start = start.replace(minute=0) + timedelta(hours=1)
        else:
            start = start.replace(minute=minute)

        for i in range(12):
            ini = start + timedelta(minutes=15 * i)
            fin = ini + timedelta(minutes=15)
            franjas.append({
                "id": slot_id,
                "inicio": ini.isoformat(timespec="minutes"),
                "fin": fin.isoformat(timespec="minutes"),
                "capacidad": 2,
                "ocupadas": 0,
                "bloqueada": False
            })
            slot_id += 1

        db = {
            "transportistas": [
                {
                    "id": 1,
                    "nombre": "Transportes Quetzal",
                    "placas": ["C123ABC"],
                },
                {
                    "id": 2,
                    "nombre": "Carga del Pacífico",
                    "placas": ["C456DEF"],
                }
            ],
            "codigos_vinculacion": [
                {
                    "codigo": "ABC123",
                    "transportista_id": 1,
                    "creado_en": now.isoformat(timespec="seconds"),
                    "usado": False
                },
                {
                    "codigo": "XYZ789",
                    "transportista_id": 2,
                    "creado_en": now.isoformat(timespec="seconds"),
                    "usado": False
                }
            ],
            "vinculaciones": [],
            "contenedores": [
                {
                    "id": "CONT-001",
                    "transportista_id": 1,
                    "levante": "Otorgado",
                    "canal": "Verde",
                    "estado": "En patio",
                    "ubicacion": "P2-N1",
                    "ingreso_en": (now - timedelta(hours=3, minutes=18)).isoformat(timespec="minutes"),
                    "tiene_cita": False
                },
                {
                    "id": "CONT-002",
                    "transportista_id": 1,
                    "levante": "Otorgado",
                    "canal": "Rojo",
                    "estado": "Pendiente de cita",
                    "ubicacion": None,
                    "ingreso_en": None,
                    "tiene_cita": False
                },
                {
                    "id": "CONT-900",
                    "transportista_id": 2,
                    "levante": "Otorgado",
                    "canal": "Verde",
                    "estado": "En patio",
                    "ubicacion": "P4-N1",
                    "ingreso_en": (now - timedelta(hours=1, minutes=5)).isoformat(timespec="minutes"),
                    "tiene_cita": False
                }
            ],
            "franjas": franjas,
            "citas": [],
            "turnos": [
                {
                    "id": 101,
                    "transportista_id": 1,
                    "vehiculo": "C123ABC",
                    "contenedor": "CONT-001",
                    "tipo_operacion": "Retiro",
                    "estado": "EnRuta",
                    "estacion": "Ruta interna"
                }
            ]
        }

        self._save(db)

    def _load(self) -> dict:
        return json.loads(self.data_file.read_text(encoding="utf-8"))

    def _save(self, db: dict):
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        self.data_file.write_text(
            json.dumps(db, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    def vincular_chat(self, chat_id: int, codigo: str) -> tuple[Optional[dict], str]:
        db = self._load()
        codigo = codigo.strip().upper()

        registro = next(
            (c for c in db["codigos_vinculacion"] if c["codigo"].upper() == codigo),
            None
        )

        if not registro:
            return None, "INVALIDO"

        if registro["usado"]:
            return None, "USADO"

        creado = datetime.fromisoformat(registro["creado_en"])
        if datetime.now() - creado > timedelta(minutes=60):
            return None, "VENCIDO"

        transportista = next(
            (t for t in db["transportistas"] if t["id"] == registro["transportista_id"]),
            None
        )
        if not transportista:
            return None, "INVALIDO"

        # Un chat se asocia a un solo transportista.
        db["vinculaciones"] = [
            v for v in db["vinculaciones"] if v["chat_id"] != chat_id
        ]
        db["vinculaciones"].append({
            "chat_id": chat_id,
            "transportista_id": transportista["id"]
        })

        registro["usado"] = True
        self._save(db)
        return transportista, "OK"

    def obtener_transportista_por_chat(self, chat_id: int) -> Optional[dict]:
        db = self._load()
        vinculo = next(
            (v for v in db["vinculaciones"] if v["chat_id"] == chat_id),
            None
        )
        if not vinculo:
            return None

        return next(
            (t for t in db["transportistas"] if t["id"] == vinculo["transportista_id"]),
            None
        )

    def obtener_chat_por_transportista(self, transportista_id: int) -> Optional[int]:
        db = self._load()
        vinculo = next(
            (v for v in db["vinculaciones"] if v["transportista_id"] == transportista_id),
            None
        )
        return None if not vinculo else int(vinculo["chat_id"])

    def listar_contenedores_elegibles_cita(self, transportista_id: int) -> list[dict]:
        db = self._load()
        return [
            c for c in db["contenedores"]
            if c["transportista_id"] == transportista_id
            and c["levante"] == "Otorgado"
            and not c["tiene_cita"]
        ]

    def listar_franjas_disponibles(self, limite: int = 6) -> list[dict]:
        db = self._load()
        now = datetime.now()
        disponibles = []

        for f in db["franjas"]:
            inicio = datetime.fromisoformat(f["inicio"])
            if (
                inicio > now
                and not f["bloqueada"]
                and f["ocupadas"] < f["capacidad"]
            ):
                disponibles.append(f)

        return disponibles[:limite]

    def crear_cita(
        self,
        transportista_id: int,
        contenedor_id: str,
        franja_id: int
    ) -> dict:
        db = self._load()

        contenedor = next(
            (
                c for c in db["contenedores"]
                if c["id"] == contenedor_id
                and c["transportista_id"] == transportista_id
            ),
            None
        )
        if not contenedor:
            raise ValueError("El contenedor no pertenece al transportista.")

        if contenedor["levante"] != "Otorgado":
            raise ValueError("El contenedor no tiene levante otorgado.")

        if contenedor["tiene_cita"]:
            raise ValueError("El contenedor ya tiene una cita.")

        franja = next((f for f in db["franjas"] if f["id"] == franja_id), None)
        if not franja:
            raise ValueError("La franja ya no existe.")

        if franja["bloqueada"] or franja["ocupadas"] >= franja["capacidad"]:
            raise ValueError("La franja ya no tiene capacidad disponible.")

        cita_id = max([c["id"] for c in db["citas"]], default=0) + 1
        cita = {
            "id": cita_id,
            "transportista_id": transportista_id,
            "contenedor": contenedor_id,
            "inicio": franja["inicio"],
            "fin": franja["fin"],
            "estado": "Programada",
            "recordatorio_1h_enviado": False
        }
        db["citas"].append(cita)
        franja["ocupadas"] += 1
        contenedor["tiene_cita"] = True

        self._save(db)
        return cita

    def listar_citas(self, transportista_id: int) -> list[dict]:
        db = self._load()
        return [
            c for c in db["citas"]
            if c["transportista_id"] == transportista_id
            and c["estado"] in ESTADOS_CITA
        ]

    def obtener_estado_contenedor(
        self,
        transportista_id: int,
        contenedor_id: str
    ) -> Optional[dict]:
        db = self._load()
        c = next(
            (
                item for item in db["contenedores"]
                if item["id"].upper() == contenedor_id.upper()
                and item["transportista_id"] == transportista_id
            ),
            None
        )
        if not c:
            return None

        permanencia = "No ha ingresado al patio"
        if c.get("ingreso_en"):
            ingreso = datetime.fromisoformat(c["ingreso_en"])
            delta = datetime.now() - ingreso
            minutos = max(0, int(delta.total_seconds() // 60))
            permanencia = f"{minutos // 60} h {minutos % 60} min"

        return {
            **c,
            "permanencia": permanencia
        }

    def listar_turnos_activos(self, transportista_id: int) -> list[dict]:
        db = self._load()
        return [
            t for t in db["turnos"]
            if t["transportista_id"] == transportista_id
            and t["estado"] not in ESTADOS_TURNO_CERRADOS
        ]

    def citas_para_recordatorio(self, now_iso: str) -> list[dict]:
        db = self._load()
        now = datetime.fromisoformat(now_iso)
        salida = []

        for c in db["citas"]:
            if c["estado"] != "Programada" or c["recordatorio_1h_enviado"]:
                continue

            inicio = datetime.fromisoformat(c["inicio"])
            segundos = (inicio - now).total_seconds()

            # El job corre cada minuto. La ventana de 55-65 min evita perder el aviso.
            if 55 * 60 <= segundos <= 65 * 60:
                salida.append(c)

        return salida

    def marcar_recordatorio_enviado(self, cita_id: int) -> None:
        db = self._load()
        cita = next((c for c in db["citas"] if c["id"] == cita_id), None)
        if cita:
            cita["recordatorio_1h_enviado"] = True
            self._save(db)
