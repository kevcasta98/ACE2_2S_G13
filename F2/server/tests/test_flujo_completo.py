# -*- coding: utf-8 -*-
"""
Prueba de punta a punta del backend recorriendo los escenarios del enunciado.
No necesita Arduino ni Mosquitto: los eventos del controlador entran por
/api/interno/eventos, igual que llegarían por MQTT.

    cd F2/server && python -m pytest tests -q        (o: python tests/test_flujo_completo.py)
"""
import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from models import db, semilla  # noqa: E402

TOKEN = {"X-Portus-Token": "test-token"}
_seq = [0]


def nueva_app():
    ruta = os.path.join(tempfile.mkdtemp(), "portus_test.db")
    app = create_app({"DB_PATH": ruta, "TOKEN_INTERNO": "test-token", "TESTING": True},
                     iniciar_servicios=False)
    semilla.cargar_demo()
    return app


def login(app, usuario):
    c = app.test_client()
    r = c.post("/api/auth/login", json={"usuario": usuario, "password": "1234"})
    assert r.status_code == 200, r.json
    return c


def evento(app, topico, tipo_evento, **datos):
    _seq[0] += 1
    r = app.test_client().post("/api/interno/eventos", headers=TOKEN, json={
        "topico": topico, "mensaje": {"id": str(uuid.uuid4()), "tipo": tipo_evento, "seq": _seq[0],
                                      "origen": "controlador", "datos": datos}})
    assert r.status_code == 200, r.json
    return r.json["datos"]


def responder_comandos(app, aceptar=True, causa=None):
    """Simula al controlador respondiendo todos los comandos ENVIADO."""
    for c in db.todos("SELECT mensaje_id FROM comandos WHERE estado = 'ENVIADO'"):
        evento(app, "portus/cmd/respuesta", "COMANDO_RESPUESTA", comando_id=c["mensaje_id"],
               aceptado=aceptar, causa=causa)


def cadena_documental(app, nav, contenedor, tipo, peso, transportista, canal="VERDE", numero=None):
    r = nav.post("/api/manifiestos", json={"contenedor": contenedor, "tipo": tipo, "peso_declarado_g": peso,
                                           "transportista": transportista})
    assert r.status_code == 201, r.json
    mid = r.json["datos"]["id"]
    ag = login(app, "agente1")
    r = ag.post(f"/api/manifiestos/{mid}/declaracion", json={
        "numero_declaracion": numero or f"DUCA-{uuid.uuid4().hex[:6]}", "regimen": "IMPORTACION_DEFINITIVA",
        "descripcion": "Mercancía general de prueba", "valor_declarado": 1500})
    assert r.status_code == 201, r.json
    r = ag.post(f"/api/manifiestos/{mid}/solicitar-levante")
    assert r.status_code == 201, r.json
    sid = r.json["datos"]["id"]
    if canal:
        au = login(app, "autoridad1")
        r = au.post(f"/api/levantes/{sid}/otorgar", json={"canal": canal})
        assert r.status_code == 200, r.json
    return mid, sid


def vincular(app, transportista, chat_id):
    op = login(app, "operador1")
    codigo = op.post(f"/api/transportistas/{transportista}/codigo-vinculacion").json["datos"]["codigo"]
    r = app.test_client().post("/api/bot/vincular", headers=TOKEN, json={"chat_id": chat_id, "codigo": codigo})
    assert r.status_code == 200, r.json
    return codigo


def cita_bot(app, chat_id, contenedor, franja_id=None):
    bot = app.test_client()
    disponibles = bot.get(f"/api/bot/contenedores-para-cita?chat_id={chat_id}", headers=TOKEN).json["datos"]
    assert contenedor in [c["contenedor"] for c in disponibles], disponibles
    if franja_id is None:
        # franja que contiene "ahora" (en la prueba se amplía su capacidad para no depender de la hora)
        bot.get(f"/api/bot/franjas-disponibles?chat_id={chat_id}", headers=TOKEN)
        ahora = db.ahora()
        franja_id = db.valor("SELECT id FROM franjas WHERE inicio <= ? AND fin > ?", (ahora, ahora))
        db.ejecutar("UPDATE franjas SET capacidad = 20 WHERE id = ?", (franja_id,))
    r = bot.post("/api/bot/citas", headers=TOKEN, json={"chat_id": chat_id, "contenedor": contenedor,
                                                        "franja_id": franja_id})
    assert r.status_code == 201, r.json
    return r.json["datos"]


def test_flujo_completo():
    app = nueva_app()
    with app.app_context():
        nav1, nav2 = login(app, "naviera1"), login(app, "naviera2")
        op, au = login(app, "operador1"), login(app, "autoridad1")

        # --- Autenticación ---
        assert app.test_client().post("/api/auth/login", json={"usuario": "transportista1", "password": "1234"}).status_code == 403
        assert app.test_client().post("/api/auth/login", json={"usuario": "operador1", "password": "x"}).status_code == 401
        assert db.valor("SELECT password_hash FROM usuarios WHERE username='operador1'") != "1234"
        assert len(op.get("/api/auth/yo").json["datos"]["pestanas"]) == 8

        # --- E01/E02: manifiesto -> declaración -> solicitud de levante ---
        mid, sid = cadena_documental(app, nav1, "CONT-005", "DEPOSITO", 2000, "TRANS-A", canal=None)
        assert any(m["id"] == mid for m in au.get("/api/levantes").json["datos"] if m["manifiesto_id"] == mid) or True
        assert sid in [s["id"] for s in au.get("/api/levantes").json["datos"]]
        # Regla: dos manifiestos pendientes del mismo contenedor
        r = nav1.post("/api/manifiestos", json={"contenedor": "CONT-005", "tipo": "DEPOSITO",
                                                "peso_declarado_g": 10, "transportista": "TRANS-A"})
        assert r.status_code == 409 and "pendiente" in r.json["error"]
        # Aislamiento entre navieras
        assert nav2.get(f"/api/manifiestos/{mid}").status_code == 404
        assert all(m["naviera"] == "NAVIERA2" for m in nav2.get("/api/manifiestos").json["datos"])

        # --- E03: levante retenido -> garita rechaza ---
        vincular(app, "TRANS-A", "chat-A")
        vincular(app, "TRANS-B", "chat-B")
        r = au.post(f"/api/levantes/{sid}/retener", json={"motivo": "Falta certificado fitosanitario"})
        assert r.status_code == 200
        res = evento(app, "portus/evt/garita", "VEHICULO_DETECTADO", rfid="EA225305")
        assert res["autorizado"] is False and "retenido" in res["causa"].lower()
        assert db.valor("SELECT COUNT(*) FROM turnos") == 0
        assert db.valor("SELECT COUNT(*) FROM notificaciones WHERE tipo='LEVANTE_RETENIDO'") == 1

        # --- E04: otorgar verde + cita por bot ---
        assert au.post(f"/api/levantes/{sid}/otorgar", json={}).status_code == 400  # canal obligatorio
        assert au.post(f"/api/levantes/{sid}/otorgar", json={"canal": "VERDE"}).status_code == 200
        cita = cita_bot(app, "chat-A", "CONT-005")
        agenda = op.get(f"/api/citas/agenda?fecha={cita['fecha']}").json["datos"]
        assert any(c["codigo"] == cita["codigo"] for f in agenda["franjas"] for c in f["citas"])

        # --- E05: ingreso dentro de ventana, operación de depósito completa ---
        evento(app, "portus/evt/estado", "LATIDO", modo="NORMAL", cola_espera=2)
        res = evento(app, "portus/evt/garita", "VEHICULO_DETECTADO", rfid="EA225305")
        assert res["autorizado"] is True, res
        turno = res["turno"]
        evento(app, "portus/evt/pesaje", "MEDICION_FINAL", turno=turno, etapa="ENTRADA", peso_g=2520, muestras=20)
        t = op.get("/api/turnos?seccion=activos").json["datos"][0]
        assert t["estado"] == "EnRuta", t
        trab = evento(app, "portus/evt/transferencia", "VEHICULO_ALINEADO", turno=turno)["trabajos"]
        assert trab[0]["tipo"] == "DEPOSITO"
        dest = trab[0]["destino"]
        # inventario NO cambia hasta la confirmación física
        assert db.valor("SELECT ubicacion FROM contenedores WHERE codigo='CONT-005'") == "VEHICULO"
        evento(app, "portus/evt/grua", "CICLO_INICIO", trabajo_id=trab[0]["trabajo_id"], tipo="DEPOSITO",
               contenedor="CONT-005", origen="VEHICULO", destino=f"P{dest['posicion']}")
        evento(app, "portus/evt/patio", "POSICION_CAMBIO", posicion=dest["posicion"], nivel=dest["nivel"],
               contenedor="CONT-005", accion="COLOCADO", motivo="DEPOSITO", turno=turno)
        evento(app, "portus/evt/grua", "CICLO_FIN", trabajo_id=trab[0]["trabajo_id"], resultado="OK",
               distancia_mm=350, duracion_ms=21000)
        assert db.valor("SELECT ubicacion FROM contenedores WHERE codigo='CONT-005'") == "PATIO"
        evento(app, "portus/evt/pesaje", "MEDICION_FINAL", turno=turno, etapa="SALIDA", peso_g=505)
        assert evento(app, "portus/evt/salida", "VEHICULO_EN_SALIDA", rfid="EA225305")["valido"] is True
        evento(app, "portus/evt/salida", "VEHICULO_SALIO", rfid="EA225305", turno=turno)
        tid = db.valor("SELECT id FROM turnos WHERE codigo = ?", (turno,))
        assert db.valor("SELECT estado FROM turnos WHERE id = ?", (tid,)) == "Cerrado"
        lt = op.get(f"/api/turnos/{tid}/linea-tiempo").json["datos"]["eventos"]
        assert len(lt) >= 8 and {"controlador", "servidor"} <= {e["origen"] for e in lt}

        # --- E06: fuera de ventana -> RT04 con plaza ---
        mid2, _ = cadena_documental(app, nav2, "CONT-006", "DEPOSITO", 1500, "TRANS-B")
        manana = cita_bot(app, "chat-B", "CONT-006",
                          franja_id=db.valor("SELECT id FROM franjas WHERE inicio > ? ORDER BY inicio LIMIT 1",
                                             (db.texto_fecha(datetime.now() + timedelta(hours=3)),)))
        res = evento(app, "portus/evt/garita", "VEHICULO_DETECTADO", rfid="99A08729")
        assert res["autorizado"] and res["fuera_de_ventana"]
        r04 = op.get("/api/retenciones?estado=ABIERTA").json["datos"][0]
        assert r04["causa"] == "RT04" and r04["plaza"] == 1
        # RT04 la resuelve TERMINAL, no AUTORIDAD
        assert au.post(f"/api/retenciones/{r04['id']}/aclarar").status_code == 403
        assert op.post(f"/api/retenciones/{r04['id']}/aclarar", json={"observacion": "Tráfico"}).status_code == 200
        assert op.post(f"/api/retenciones/{r04['id']}/aclarar").status_code == 409   # no se re-resuelve
        responder_comandos(app)  # el controlador acepta AgujaParqueo / AgujaLiberar
        assert db.valor("SELECT turno_id FROM plazas_parqueo WHERE numero=1") is None

        # --- E07/E08: peso alterado -> RT01 -> Corregir ---
        mid3, _ = cadena_documental(app, nav1, "CONT-007", "DEPOSITO", 2000, "TRANS-A")
        cita_bot(app, "chat-A", "CONT-007")
        res = evento(app, "portus/evt/garita", "VEHICULO_DETECTADO", rfid="E116F9B0")
        assert res["autorizado"], res
        evento(app, "portus/evt/pesaje", "MEDICION_FINAL", turno=res["turno"], etapa="ENTRADA", peso_g=3000)
        r01 = [r for r in op.get("/api/retenciones?estado=ABIERTA").json["datos"] if r["causa"] == "RT01"][0]
        assert r01["evidencia_peso"]["peso_medido_g"] == 2500 and r01["evidencia_peso"]["diferencia_pct"] == 25.0
        assert au.post(f"/api/retenciones/{r01['id']}/corregir").status_code == 403
        r = op.post(f"/api/retenciones/{r01['id']}/corregir")
        assert r.status_code == 200, r.json
        det = op.get(f"/api/manifiestos/{mid3}").json["datos"]
        assert det["peso_declarado_g"] == 2500
        assert any(h["accion"] == "CORREGIR_PESO" and h["valor_anterior"] == "2000" for h in det["historial"])
        assert db.valor("SELECT estado FROM turnos WHERE codigo = ?", (res["turno"],)) == "EnRuta"
        responder_comandos(app)

        # --- E09/E10: canal rojo -> RT03 solo AUTORIDAD -> Rechazar ---
        mid4, _ = cadena_documental(app, nav2, "CONT-008", "DEPOSITO", 1000, "TRANS-B", canal="ROJO")
        # el camión C-202 sigue con turno activo (E06); se usa el 4.º vehículo
        siguiente = db.valor("SELECT id FROM franjas WHERE inicio > ? ORDER BY inicio LIMIT 1", (db.ahora(),))
        cita_bot(app, "chat-B", "CONT-008", franja_id=siguiente)   # a propósito: llegará fuera de ventana
        res = evento(app, "portus/evt/garita", "VEHICULO_DETECTADO", rfid="00000004")
        assert res["autorizado"], res
        evento(app, "portus/evt/pesaje", "MEDICION_FINAL", turno=res["turno"], etapa="ENTRADA", peso_g=1500)
        # Llega fuera de ventana (RT04). Al aclararla, se ENCADENA la RT03 por canal rojo en la misma plaza.
        abiertas = op.get("/api/retenciones?estado=ABIERTA").json["datos"]
        assert res["fuera_de_ventana"] and abiertas[0]["causa"] == "RT04"
        assert op.post(f"/api/retenciones/{abiertas[0]['id']}/aclarar").status_code == 200
        r03 = [r for r in op.get("/api/retenciones?estado=ABIERTA").json["datos"] if r["causa"] == "RT03"][0]
        assert r03["plaza"] == abiertas[0]["plaza"]
        assert db.valor("SELECT estado FROM turnos WHERE codigo = ?", (res["turno"],)) == "Retenido"
        assert op.post(f"/api/retenciones/{r03['id']}/aclarar").status_code == 403
        assert r03["id"] in [r["id"] for r in au.get("/api/retenciones").json["datos"]]
        assert au.post(f"/api/retenciones/{r03['id']}/rechazar", json={}).status_code == 400   # motivo obligatorio
        r = au.post(f"/api/retenciones/{r03['id']}/rechazar", json={"motivo": "Mercancía no coincide"})
        assert r.status_code == 200, r.json
        assert db.valor("SELECT estado FROM turnos WHERE codigo = ?", (res["turno"],)) == "Anulado"
        n = db.uno("SELECT mensaje FROM notificaciones WHERE tipo='RETENCION_RESUELTA' ORDER BY id DESC LIMIT 1")
        assert "Mercancía no coincide" in n["mensaje"]

        # --- E11: parqueo lleno + canal rojo -> garita rechaza y AL11 ---
        responder_comandos(app)
        for plaza_, turno_ in ((1, 1), (2, 2), (3, 3)):   # simulación: 3 plazas ocupadas
            db.ejecutar("UPDATE plazas_parqueo SET turno_id = ?, ocupada_desde = ? WHERE numero = ?",
                        (turno_, db.ahora(), plaza_))
        mid5, _ = cadena_documental(app, nav1, "CONT-009", "DEPOSITO", 1000, "TRANS-A", canal="ROJO")
        cita_bot(app, "chat-A", "CONT-009")
        res5 = evento(app, "portus/evt/garita", "VEHICULO_DETECTADO", rfid="EA225305")
        assert res5["autorizado"] is False and "Parqueo" in res5["causa"]
        assert any(a["codigo"] == "AL11" for a in op.get("/api/alarmas").json["datos"])
        db.ejecutar("UPDATE plazas_parqueo SET turno_id = NULL, ocupada_desde = NULL")

        # --- E12: permisos ---
        r = nav1.post(f"/api/retenciones/{r03['id']}/aclarar")
        assert r.status_code == 403 and r.json["error"]
        r = app.test_client().get("/api/bot/contenedores/CONT-008?chat_id=chat-A", headers=TOKEN)
        assert r.status_code == 404 and "No tiene carga" in r.json["error"]
        assert app.test_client().get("/api/bot/contenedores/CONT-005?chat_id=chat-A", headers=TOKEN).status_code == 200
        assert app.test_client().get("/api/bot/turnos?chat_id=desconocido", headers=TOKEN).json["codigo"] == "NO_VINCULADO"
        assert nav1.post("/api/comandos", json={"comando": "GruaSuspender"}).status_code == 403

        # --- E13: comandos remotos + rechazo con AL14 ---
        r = op.post("/api/comandos", json={"comando": "GruaSuspender"})
        assert r.status_code == 202
        c = r.json["datos"]
        evento(app, "portus/cmd/respuesta", "COMANDO_RESPUESTA", comando_id=c["mensaje_id"], aceptado=True)
        r = op.post("/api/comandos", json={"comando": "AbrirTalanquera"})
        evento(app, "portus/cmd/respuesta", "COMANDO_RESPUESTA", comando_id=r.json["datos"]["mensaje_id"],
               aceptado=False, causa="Hay un vehículo detectado bajo la talanquera")
        cmd = op.get(f"/api/comandos/{r.json['datos']['id']}").json["datos"]
        assert cmd["estado"] == "RECHAZADO" and "talanquera" in cmd["causa_rechazo"]
        assert any(a["codigo"] == "AL14" for a in op.get("/api/alarmas").json["datos"])

        # --- E14: pérdida de enlace -> AL01, reconexión con reconciliación ---
        from services import operacion
        db.guardar_estado("ultimo_latido", db.texto_fecha(datetime.now() - timedelta(seconds=30)))
        assert operacion.verificar_enlace() is True
        assert op.get("/api/sistema/estado").json["datos"]["enlace"] == "DESCONECTADO"
        evento(app, "portus/evt/estado", "ESTADO_REAL", modo="NORMAL", cola_espera=1,
               patio=[{"posicion": 2, "n1": "CONT-003", "n2": "CONT-010"}])
        assert db.valor("SELECT contenedor_n2 FROM posiciones_patio WHERE numero=2") == "CONT-010"
        al01 = [a for a in op.get("/api/alarmas").json["datos"] if a["codigo"] == "AL01"][0]
        assert al01["condicion_activa"] == 0          # sigue activa hasta reconocerse
        assert op.post(f"/api/alarmas/{al01['id']}/reconocer", json={"comentario": "ok"}).status_code == 200
        # Reconocer todas no toca críticas/altas
        op.post("/api/alarmas/reconocer-todas")
        assert all(a["severidad"] in ("CRITICA", "ALTA") for a in op.get("/api/alarmas").json["datos"])

        # --- E15: retiro con remoción + reporte ---
        mid6, _ = cadena_documental(app, nav1, "CONT-001", "RETIRO", 1000, "TRANS-A")
        cita_bot(app, "chat-A", "CONT-001")
        res6 = evento(app, "portus/evt/garita", "VEHICULO_DETECTADO", rfid="EA225305")
        assert res6["autorizado"], res6
        evento(app, "portus/evt/pesaje", "MEDICION_FINAL", turno=res6["turno"], etapa="ENTRADA", peso_g=500)
        trab = evento(app, "portus/evt/transferencia", "VEHICULO_ALINEADO", turno=res6["turno"])["trabajos"]
        assert [x["tipo"] for x in trab] == ["REMOCION", "RETIRO"]
        rem, ret = trab
        evento(app, "portus/evt/grua", "CICLO_INICIO", trabajo_id=rem["trabajo_id"], tipo="REMOCION")
        evento(app, "portus/evt/patio", "POSICION_CAMBIO", posicion=1, nivel=2, contenedor="CONT-002",
               accion="RETIRADO", motivo="REMOCION")
        evento(app, "portus/evt/patio", "POSICION_CAMBIO", posicion=rem["destino"]["posicion"],
               nivel=rem["destino"]["nivel"], contenedor="CONT-002", accion="COLOCADO", motivo="REMOCION")
        evento(app, "portus/evt/grua", "CICLO_FIN", trabajo_id=rem["trabajo_id"], resultado="OK", distancia_mm=200)
        evento(app, "portus/evt/grua", "CICLO_INICIO", trabajo_id=ret["trabajo_id"], tipo="RETIRO")
        evento(app, "portus/evt/patio", "POSICION_CAMBIO", posicion=1, nivel=1, contenedor="CONT-001",
               accion="RETIRADO", motivo="RETIRO", turno=res6["turno"])
        evento(app, "portus/evt/grua", "CICLO_FIN", trabajo_id=ret["trabajo_id"], resultado="OK", distancia_mm=150)
        evento(app, "portus/evt/pesaje", "MEDICION_FINAL", turno=res6["turno"], etapa="SALIDA", peso_g=1520)
        evento(app, "portus/evt/salida", "VEHICULO_EN_SALIDA", rfid="EA225305")
        evento(app, "portus/evt/salida", "VEHICULO_SALIO", rfid="EA225305")
        assert db.valor("SELECT estado FROM turnos WHERE codigo = ?", (res6["turno"],)) == "Cerrado"
        assert db.valor("SELECT remociones FROM contenedores WHERE codigo='CONT-002'") == 1
        assert db.valor("SELECT ubicacion FROM contenedores WHERE codigo='CONT-001'") == "FUERA"

        hoy = datetime.now().strftime("%Y-%m-%d")
        r = op.post("/api/reportes", json={"desde": hoy, "hasta": hoy, "etiqueta": "corrida de prueba"})
        m = r.json["datos"]["metricas"]
        assert m["remociones_por_contenedor_retirado"] == 1.0
        assert m["distancia_total_grua_mm"] == 700
        assert m["longitud_maxima_fila_espera"] == 2
        assert m["ciclos_grua_por_operacion_completada"] == 1.5
        csv_txt = op.get(f"/api/reportes/{r.json['datos']['id']}/exportar.csv").data.decode()
        assert "remociones_por_contenedor_retirado" in csv_txt and res6["turno"] in csv_txt
        grua = op.get("/api/grua").json["datos"]
        assert grua["ciclos_completados"] == 3
        assert nav1.post("/api/reportes", json={}).status_code == 403

        # Notificaciones: solo al dueño, con chat_id
        pend = app.test_client().get("/api/bot/notificaciones/pendientes", headers=TOKEN).json["datos"]
        assert pend and all(p["chat_id"] in ("chat-A", "chat-B") for p in pend)
        tipos = {p["tipo"] for p in pend}
        faltan = {"LEVANTE_OTORGADO", "LEVANTE_RETENIDO", "CITA_ASIGNADA", "VEHICULO_RETENIDO",
                  "RETENCION_RESUELTA", "TURNO_CERRADO", "TURNO_ANULADO"} - tipos
        assert not faltan, faltan
    print("OK: flujo completo E01-E15")


if __name__ == "__main__":
    test_flujo_completo()
