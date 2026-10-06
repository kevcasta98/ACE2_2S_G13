import tempfile
import unittest
from pathlib import Path

from mock_repository import MockRepository


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "mock.json"
        self.repo = MockRepository(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_codigo_es_de_un_solo_uso(self):
        t, resultado = self.repo.vincular_chat(123, "ABC123")
        self.assertEqual(resultado, "OK")
        self.assertIsNotNone(t)

        t2, resultado2 = self.repo.vincular_chat(456, "ABC123")
        self.assertIsNone(t2)
        self.assertEqual(resultado2, "USADO")

    def test_aislamiento_de_contenedor(self):
        self.repo.vincular_chat(123, "ABC123")
        c = self.repo.obtener_estado_contenedor(1, "CONT-900")
        self.assertIsNone(c)

    def test_cita_solo_con_levante_y_sin_cita(self):
        elegibles = self.repo.listar_contenedores_elegibles_cita(1)
        self.assertTrue(any(c["id"] == "CONT-001" for c in elegibles))

        franja = self.repo.listar_franjas_disponibles()[0]
        cita = self.repo.crear_cita(1, "CONT-001", franja["id"])

        self.assertEqual(cita["estado"], "Programada")

        elegibles2 = self.repo.listar_contenedores_elegibles_cita(1)
        self.assertFalse(any(c["id"] == "CONT-001" for c in elegibles2))


if __name__ == "__main__":
    unittest.main()
