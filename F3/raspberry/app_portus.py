#!/usr/bin/env python3
# ============================================================
# PORTUS - Web v0.5.3
# Autenticación/RBAC + cadena documental + Citas + resolución física de Retenciones
# ============================================================

import os
import sqlite3
import json
import threading
import uuid

import paho.mqtt.client as mqtt
from datetime import date, datetime, timedelta, timezone
from functools import wraps

from flask import (
    Flask, abort, flash, jsonify, redirect, render_template,
    request, session, url_for
)
from werkzeug.security import check_password_hash

from db_portus import conectar, inicializar_bd

from citas_portus import (
    CAPACIDAD_FRANJA,
    MINUTOS_FRANJA,
    TZ_LOCAL,
    ErrorCita,
    actualizar_citas_vencidas,
    bloquear_franja,
    cancelar_cita,
    encolar_notificacion,
    generar_codigo_vinculacion,
    listar_franjas_disponibles,
    reprogramar_cita,
)


app = Flask(__name__)
app.secret_key = os.environ.get("PORTUS_SECRET_KEY", "PORTUS-DEMO-CAMBIAR-ESTA-CLAVE")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)



# ============================================================
# MQTT / comandos sincronizados con el controlador
# ============================================================
MQTT_HOST = os.environ.get("PORTUS_MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("PORTUS_MQTT_PORT", "1883"))
TOPIC_CMD_SOLICITUD = "portus/cmd/solicitud"
TOPIC_CMD_RESPUESTA = "portus/cmd/respuesta"


def enviar_comando_controlador(command, params=None, timeout=4.0):
    """Envía un comando por MQTT y espera el ACK/NACK real del Mega.

    La base de datos NO se modifica hasta recibir ACK. Esto evita marcar una
    plaza como libre si el controlador rechazó AgujaLiberar.
    """
    request_id = f"cmd-web-{uuid.uuid4()}"
    conectado = threading.Event()
    respondido = threading.Event()
    caja = {}

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"portus-web-{uuid.uuid4().hex[:10]}",
    )

    def on_connect(cli, userdata, flags, reason_code, properties):
        if reason_code == 0:
            cli.subscribe(TOPIC_CMD_RESPUESTA)
            conectado.set()
        else:
            caja["error"] = f"MQTT_CONEXION_{reason_code}"
            conectado.set()

    def on_message(cli, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            return
        data = payload.get("data") or {}
        if data.get("request_id") != request_id:
            return
        caja["respuesta"] = payload
        respondido.set()

    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(MQTT_HOST, MQTT_PORT, 30)
        client.loop_start()

        if not conectado.wait(2.0):
            return False, "MQTT_SIN_CONEXION", None
        if caja.get("error"):
            return False, caja["error"], None

        payload = {
            "id": request_id,
            "timestamp": datetime.now(TZ_LOCAL).isoformat(timespec="milliseconds"),
            "origin": "server",
            "type": "CMD",
            "data": {
                "command": str(command).upper(),
                "params": params or {},
            },
        }
        info = client.publish(
            TOPIC_CMD_SOLICITUD,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            qos=1,
            retain=False,
        )
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            return False, f"MQTT_PUBLICACION_{info.rc}", None

        if not respondido.wait(timeout):
            return False, "CONTROLADOR_SIN_RESPUESTA", None

        respuesta = caja.get("respuesta") or {}
        data = respuesta.get("data") or {}
        if str(respuesta.get("type", "")).upper() == "ACK":
            return True, str(data.get("msg") or "ACEPTADO"), respuesta

        return False, str(data.get("motivo") or "COMANDO_RECHAZADO"), respuesta

    except Exception as exc:
        return False, f"MQTT_ERROR: {exc}", None
    finally:
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass


TABS_POR_ROL = {
    "TERMINAL": [
        ("Operación", "terminal_operacion"),
        ("Turnos", "terminal_turnos"),
        ("Retenciones", "terminal_retenciones"),
        ("Patio", "terminal_patio"),
        ("Grúa", "terminal_grua"),
        ("Alarmas", "terminal_alarmas"),
        ("Citas", "terminal_citas"),
        ("Reportes", "terminal_reportes"),
    ],
    "NAVIERA": [
        ("Manifiestos", "naviera_manifiestos"),
        ("Mis contenedores", "naviera_contenedores"),
    ],
    "AGENTE": [
        ("Declaraciones", "agente_declaraciones"),
        ("Seguimiento", "agente_seguimiento"),
    ],
    "AUTORIDAD": [
        ("Solicitudes de levante", "autoridad_solicitudes"),
        ("Retenciones aduaneras", "autoridad_retenciones_aduaneras"),
        ("Consulta de carga", "autoridad_consulta_carga"),
    ],
}


def usuario_actual():
    user_id = session.get("user_id")
    if not user_id:
        return None

    conn = conectar()
    fila = conn.execute(
        """
        SELECT id, username, nombre, rol, naviera_id,
               transportista_id, activo
        FROM usuarios
        WHERE id = ?
        """,
        (user_id,),
    ).fetchone()
    conn.close()

    if not fila or not fila["activo"]:
        session.clear()
        return None

    return dict(fila)


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if usuario_actual() is None:
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "NO_AUTENTICADO"}), 401
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper


def roles_required(*roles):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            user = usuario_actual()
            if user is None:
                if request.path.startswith("/api/"):
                    return jsonify({"ok": False, "error": "NO_AUTENTICADO"}), 401
                return redirect(url_for("login"))

            if user["rol"] not in roles:
                if request.path.startswith("/api/"):
                    return jsonify({
                        "ok": False,
                        "error": "PERMISO_DENEGADO",
                        "rol": user["rol"],
                        "roles_permitidos": list(roles),
                    }), 403
                abort(403)
            return func(*args, **kwargs)
        return wrapper
    return decorator


def menu_para(user):
    return TABS_POR_ROL.get(user["rol"], [])


def siguiente_id_manifiesto(conn):
    filas = conn.execute("SELECT id FROM manifiestos WHERE id LIKE 'M%'").fetchall()
    mayor = 1000
    for fila in filas:
        texto = fila["id"][1:]
        if texto.isdigit():
            mayor = max(mayor, int(texto))
    return f"M{mayor + 1}"


def permanencia_texto(valor):
    if not valor:
        return "00 h 00 min"

    candidatos = [
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
    ]

    inicio = None
    for formato in candidatos:
        try:
            inicio = datetime.strptime(valor, formato)
            break
        except ValueError:
            continue

    if inicio is None:
        return "No disponible"

    if inicio.tzinfo is None:
        ahora = datetime.now()
    else:
        ahora = datetime.now(inicio.tzinfo)

    total_min = max(0, int((ahora - inicio).total_seconds() // 60))
    horas, minutos = divmod(total_min, 60)
    return f"{horas:02d} h {minutos:02d} min"


def _parse_fecha(valor):
    if not valor:
        return None

    candidatos = [
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
    ]
    for formato in candidatos:
        try:
            return datetime.strptime(valor, formato)
        except ValueError:
            continue
    return None


def duracion_texto(inicio_valor, fin_valor=None):
    inicio = _parse_fecha(inicio_valor)
    if inicio is None:
        return "No disponible"

    fin = _parse_fecha(fin_valor) if fin_valor else None
    if fin is None:
        fin = datetime.now(inicio.tzinfo) if inicio.tzinfo else datetime.now()

    total_min = max(0, int((fin - inicio).total_seconds() // 60))
    horas, minutos = divmod(total_min, 60)
    return f"{horas:02d} h {minutos:02d} min"


def diferencia_porcentual(peso_declarado, peso_medido):
    try:
        declarado = float(peso_declarado)
        medido = float(peso_medido)
    except (TypeError, ValueError):
        return None
    if declarado == 0:
        return None
    return abs(medido - declarado) * 100.0 / abs(declarado)


@app.context_processor
def inject_helpers():
    return {
        "permanencia_texto": permanencia_texto,
        "duracion_texto": duracion_texto,
        "diferencia_porcentual": diferencia_porcentual,
    }


@app.route("/")
def index():
    return redirect(url_for("dashboard" if usuario_actual() else "login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = conectar()
        fila = conn.execute(
            """
            SELECT id, username, password_hash, nombre, rol,
                   naviera_id, transportista_id, activo
            FROM usuarios
            WHERE username = ?
            """,
            (username,),
        ).fetchone()
        conn.close()

        if not fila or not fila["activo"] or not check_password_hash(
            fila["password_hash"], password
        ):
            error = "Usuario o contraseña incorrectos."
        elif fila["rol"] == "TRANSPORTISTA":
            error = (
                "El rol TRANSPORTISTA no utiliza la aplicación web. "
                "Debe operar desde el canal de mensajería."
            )
        else:
            session.clear()
            session["user_id"] = fila["id"]
            return redirect(url_for("dashboard"))

    return render_template("login.html", error=error)


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/dashboard")
@login_required
def dashboard():
    user = usuario_actual()

    if user["rol"] == "TRANSPORTISTA":
        session.clear()
        return redirect(url_for("login"))

    if user["rol"] == "NAVIERA":
        return redirect(url_for("naviera_manifiestos"))
    if user["rol"] == "AGENTE":
        return redirect(url_for("agente_declaraciones"))
    if user["rol"] == "AUTORIDAD":
        return redirect(url_for("autoridad_solicitudes"))

    return render_template(
        "dashboard.html",
        user=user,
        tabs=menu_para(user),
    )



# ============================================================
# TERMINAL - CITAS
# ============================================================

@app.get("/terminal/retenciones")
@roles_required("TERMINAL")
def terminal_retenciones():
    """Bandeja de retenciones del operador TERMINAL.

    Muestra retenciones activas y resueltas, con filtros por causa/estado.
    Las resoluciones de TERMINAL esperan el ACK real de AgujaLiberar antes
    de actualizar SQLite, evitando desincronizar la plaza lógica y la maqueta.
    """
    user = usuario_actual()
    estado = request.args.get("estado", "").strip().upper()
    causa = request.args.get("causa", "").strip().upper()

    causas_validas = ("RT01", "RT02", "RT03", "RT04", "RT05", "RT06", "RT07", "RT08")

    sql = """
        SELECT
            r.id,
            r.turno_id,
            r.causa,
            r.plaza,
            r.estado,
            r.resolucion,
            r.rol_resolutor,
            r.motivo,
            r.peso_declarado_g AS peso_total_esperado_g,
            r.peso_medido_g AS peso_total_medido_g,
            r.inicio,
            r.fin,
            r.estacion_origen,
            r.observacion_resolucion,
            r.motivo_resolucion,
            t.estado AS turno_estado,
            t.estado_previo_retencion,
            t.estacion AS turno_estacion,
            t.contenedor_id,
            t.manifiesto_id,
            c.placa AS vehiculo,
            c.tara_g,
            m.peso_declarado_g AS peso_contenedor_declarado_g,
            m.operacion,
            n.nombre AS naviera,
            tr.nombre AS transportista
        FROM retenciones r
        LEFT JOIN turnos t ON t.id = r.turno_id
        LEFT JOIN camiones c ON c.id = t.camion_id
        LEFT JOIN manifiestos m ON m.id = t.manifiesto_id
        LEFT JOIN navieras n ON n.id = m.naviera_id
        LEFT JOIN transportistas tr ON tr.id = m.transportista_id
        WHERE 1 = 1
    """
    params = []

    if estado in ("ACTIVA", "RESUELTA"):
        sql += " AND r.estado = ?"
        params.append(estado)
    if causa in causas_validas:
        sql += " AND r.causa = ?"
        params.append(causa)

    sql += " ORDER BY CASE WHEN r.estado = 'ACTIVA' THEN 0 ELSE 1 END, r.inicio DESC, r.id DESC"

    conn = conectar()
    filas = conn.execute(sql, params).fetchall()

    plazas = conn.execute(
        """
        SELECT p.numero, p.ocupada, p.turno_id, p.ocupada_desde,
               c.placa AS vehiculo, t.contenedor_id
        FROM plazas_retencion p
        LEFT JOIN turnos t ON t.id = p.turno_id
        LEFT JOIN camiones c ON c.id = t.camion_id
        ORDER BY p.numero
        """
    ).fetchall()
    conn.close()

    return render_template(
        "terminal_retenciones.html",
        user=user,
        tabs=menu_para(user),
        retenciones=filas,
        plazas=plazas,
        estado_filtro=estado,
        causa_filtro=causa,
    )



def _cargar_retencion_resoluble(conn, retencion_id, rol):
    return conn.execute(
        """
        SELECT
            r.*,
            t.estado AS turno_estado,
            t.estado_previo_retencion,
            t.estacion AS turno_estacion,
            t.manifiesto_id,
            t.contenedor_id,
            t.operacion,
            t.camion_id,
            c.placa AS vehiculo,
            c.tara_g,
            m.peso_declarado_g AS manifiesto_peso_declarado_g,
            m.tolerancia_pct,
            m.transportista_id,
            d.canal
        FROM retenciones r
        JOIN turnos t ON t.id = r.turno_id
        JOIN camiones c ON c.id = t.camion_id
        JOIN manifiestos m ON m.id = t.manifiesto_id
        LEFT JOIN declaraciones d ON d.manifiesto_id = m.id
        WHERE r.id = ? AND r.rol_resolutor = ?
        LIMIT 1
        """,
        (retencion_id, rol),
    ).fetchone()


def _destino_despues_retencion(retencion):
    previo = str(retencion["estado_previo_retencion"] or "")
    if previo in ("EnPesajeSalida", "EnSalida"):
        return "EnSalida", "SALIDA"
    return "EnRuta", "RUTA"


def _registrar_al14(conn, comando, causa, retencion_id):
    datos = json.dumps(
        {
            "comando": comando,
            "causa": causa,
            "retencion_id": retencion_id,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    conn.execute(
        """
        INSERT INTO alarmas(codigo, severidad, timestamp, datos_json)
        VALUES ('AL14', 'Media', ?, ?)
        """,
        (datetime.now(TZ_LOCAL).isoformat(timespec="seconds"), datos),
    )


def _peso_corregido_manifiesto(retencion):
    """Convierte el peso bruto medido al peso del contenedor usado por PORTUS.

    El modelo actual guarda en manifiestos.peso_declarado_g el peso del
    contenedor/carga, mientras el HX711 mide el vehículo completo. Por eso solo
    puede corregirse automáticamente cuando esa estación debe llevar carga:
    DEPOSITO/RT01 (entrada) o RETIRO/RT02 (salida).
    """
    causa = str(retencion["causa"] or "")
    operacion = str(retencion["operacion"] or "")
    es_pesaje_cargado = (
        (causa == "RT01" and operacion == "DEPOSITO")
        or (causa == "RT02" and operacion == "RETIRO")
    )
    if not es_pesaje_cargado:
        raise ValueError(
            "Corregir no puede inferir el peso del contenedor en este punto del flujo; "
            "use Aclarar o Rechazar."
        )

    medido = retencion["peso_medido_g"]
    tara = retencion["tara_g"]
    if medido is None or tara is None:
        raise ValueError("La retención no tiene peso medido o tara suficiente para Corregir.")

    nuevo = round(float(medido) - float(tara), 1)
    if nuevo <= 0:
        raise ValueError(
            "El peso medido no permite obtener un peso positivo del contenedor. "
            "En esta prueba el vehículo parece haber pasado sin carga; use Aclarar o Rechazar."
        )
    return nuevo


def _resolver_retencion_con_controlador(retencion_id, rol, resolucion, usuario, observacion=None, motivo=None):
    resolucion = str(resolucion).upper()
    if resolucion not in ("ACLARAR", "CORREGIR", "RECHAZAR"):
        return False, "Resolución no válida."
    if resolucion == "CORREGIR" and rol != "TERMINAL":
        return False, "Corregir está disponible únicamente para TERMINAL."
    if resolucion == "RECHAZAR" and not (motivo or "").strip():
        return False, "La resolución Rechazar requiere un motivo."

    conn = conectar()
    try:
        conn.execute("BEGIN IMMEDIATE")
        r = _cargar_retencion_resoluble(conn, retencion_id, rol)
        if r is None:
            conn.rollback()
            return False, "La retención no existe o este rol no está facultado para resolverla."
        if r["estado"] != "ACTIVA":
            conn.rollback()
            return False, "La retención ya fue resuelta y no puede volver a resolverse."
        if r["turno_estado"] != "Retenido":
            conn.rollback()
            return False, f"El turno {r['turno_id']} ya no está en estado Retenido."
        if r["plaza"] is None:
            conn.rollback()
            return False, "La retención no tiene una plaza física asignada para liberar."

        destino_db, destino_controlador = _destino_despues_retencion(r)
        if resolucion == "RECHAZAR":
            destino_controlador = "SALIDA"

        nuevo_peso = None
        if resolucion == "CORREGIR":
            if r["causa"] not in ("RT01", "RT02"):
                conn.rollback()
                return False, "Corregir solo aplica a retenciones por discrepancia de peso RT01/RT02."
            try:
                nuevo_peso = _peso_corregido_manifiesto(r)
            except ValueError as exc:
                conn.rollback()
                return False, str(exc)

        tolerancia_g = (
            float(r["manifiesto_peso_declarado_g"]) * float(r["tolerancia_pct"] or 0.0) / 100.0
        )
        params = {
            "turno": r["turno_id"],
            "plaza": int(r["plaza"]),
            "resolucion": resolucion,
            "destino": destino_controlador,
            # Datos de reconciliación: permiten liberar un turno retenido aun
            # si el Mega se reinició al cargar esta versión del firmware.
            "camion": r["vehiculo"],
            "manifiesto": r["manifiesto_id"],
            "contenedor": r["contenedor_id"],
            "operacion": r["operacion"],
            "peso": f"{float(r['manifiesto_peso_declarado_g']):.1f}",
            "tolerancia": f"{tolerancia_g:.3f}",
            "canal": str(r["canal"] or "VERDE"),
        }
        if nuevo_peso is not None:
            params["nuevo_peso"] = f"{nuevo_peso:.1f}"

        aceptado, respuesta, _ = enviar_comando_controlador(
            "AgujaLiberar",
            params,
            timeout=4.0,
        )
        if not aceptado:
            conn.rollback()
            # AL14 se persiste incluso si la operación principal se revierte.
            try:
                _registrar_al14(conn, "AgujaLiberar", respuesta, retencion_id)
                conn.commit()
            except Exception:
                conn.rollback()
            return False, f"El controlador rechazó AgujaLiberar: {respuesta}"

        if resolucion == "CORREGIR":
            anterior = float(r["manifiesto_peso_declarado_g"])
            conn.execute(
                """
                UPDATE manifiestos
                SET peso_declarado_g = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (nuevo_peso, r["manifiesto_id"]),
            )
            conn.execute(
                """
                INSERT INTO historial_manifiesto(
                    manifiesto_id, campo, valor_anterior, valor_nuevo,
                    motivo, usuario_id
                ) VALUES (?, 'PESO_DECLARADO_G', ?, ?, ?, ?)
                """,
                (
                    r["manifiesto_id"],
                    f"{anterior:.1f}",
                    f"{nuevo_peso:.1f}",
                    f"Resolución {r['causa']} mediante CORREGIR",
                    usuario["id"],
                ),
            )

        if resolucion == "RECHAZAR":
            conn.execute(
                """
                UPDATE turnos
                SET estado = 'Anulado', estado_previo_retencion = NULL,
                    estacion = 'SALIDA', cierre = COALESCE(cierre, datetime('now')),
                    updated_at = datetime('now')
                WHERE id = ? AND estado = 'Retenido'
                """,
                (r["turno_id"],),
            )
        else:
            estacion = "SALIDA" if destino_db == "EnSalida" else "RUTA"
            conn.execute(
                """
                UPDATE turnos
                SET estado = ?, estado_previo_retencion = NULL,
                    estacion = ?, updated_at = datetime('now')
                WHERE id = ? AND estado = 'Retenido'
                """,
                (destino_db, estacion, r["turno_id"]),
            )

        conn.execute(
            """
            UPDATE retenciones
            SET estado = 'RESUELTA', resolucion = ?,
                observacion_resolucion = ?, motivo_resolucion = ?,
                fin = datetime('now')
            WHERE id = ? AND estado = 'ACTIVA'
            """,
            (
                resolucion,
                (observacion or "").strip() or None,
                (motivo or "").strip() or None if resolucion == "RECHAZAR" else None,
                retencion_id,
            ),
        )
        _liberar_plaza_logica(conn, r)

        if r["transportista_id"]:
            if resolucion == "CORREGIR":
                mensaje = (
                    f"Vehículo {r['vehiculo']}, contenedor {r['contenedor_id']}: "
                    f"retención resuelta mediante Corregir. "
                    f"Nuevo peso declarado: {nuevo_peso:.1f} g."
                )
            elif resolucion == "RECHAZAR":
                mensaje = (
                    f"Vehículo {r['vehiculo']}, contenedor {r['contenedor_id']}: "
                    f"retención resuelta mediante Rechazar. Motivo: {(motivo or '').strip()}."
                )
            else:
                mensaje = (
                    f"Vehículo {r['vehiculo']}, contenedor {r['contenedor_id']}: "
                    "retención resuelta mediante Aclarar."
                )
            encolar_notificacion(conn, r["transportista_id"], "RETENCION_RESUELTA", mensaje)

        conn.commit()
        if resolucion == "RECHAZAR":
            return True, f"Retención R{retencion_id} rechazada. AgujaLiberar aceptado; el turno quedó Anulado y puede dirigirse a salida."
        if resolucion == "CORREGIR":
            return True, f"Retención R{retencion_id} corregida a {nuevo_peso:.1f} g. AgujaLiberar aceptado; turno reanudado en {destino_db}."
        return True, f"Retención R{retencion_id} aclarada. AgujaLiberar aceptado; turno reanudado en {destino_db}."

    except Exception as exc:
        conn.rollback()
        return False, f"No se pudo resolver la retención: {exc}"
    finally:
        conn.close()


@app.post("/terminal/retenciones/<int:retencion_id>/aclarar")
@roles_required("TERMINAL")
def terminal_retencion_aclarar(retencion_id):
    user = usuario_actual()
    ok, mensaje = _resolver_retencion_con_controlador(
        retencion_id,
        "TERMINAL",
        "ACLARAR",
        user,
        observacion=request.form.get("observacion", ""),
    )
    flash(mensaje, "ok" if ok else "error")
    return redirect(url_for("terminal_retenciones"))


@app.post("/terminal/retenciones/<int:retencion_id>/corregir")
@roles_required("TERMINAL")
def terminal_retencion_corregir(retencion_id):
    user = usuario_actual()
    ok, mensaje = _resolver_retencion_con_controlador(
        retencion_id,
        "TERMINAL",
        "CORREGIR",
        user,
        observacion=request.form.get("observacion", ""),
    )
    flash(mensaje, "ok" if ok else "error")
    return redirect(url_for("terminal_retenciones"))


@app.post("/terminal/retenciones/<int:retencion_id>/rechazar")
@roles_required("TERMINAL")
def terminal_retencion_rechazar(retencion_id):
    user = usuario_actual()
    ok, mensaje = _resolver_retencion_con_controlador(
        retencion_id,
        "TERMINAL",
        "RECHAZAR",
        user,
        motivo=request.form.get("motivo", ""),
    )
    flash(mensaje, "ok" if ok else "error")
    return redirect(url_for("terminal_retenciones"))


@app.get("/terminal/citas")
@roles_required("TERMINAL")
def terminal_citas():
    user = usuario_actual()
    actualizar_citas_vencidas()

    fecha_texto = request.args.get("fecha", "").strip()
    if not fecha_texto:
        fecha_obj = datetime.now(TZ_LOCAL).date()
        fecha_texto = fecha_obj.isoformat()
    else:
        try:
            fecha_obj = date.fromisoformat(fecha_texto)
        except ValueError:
            fecha_obj = datetime.now(TZ_LOCAL).date()
            fecha_texto = fecha_obj.isoformat()
            flash("La fecha indicada no es válida.", "error")

    inicio_dia = datetime.combine(fecha_obj, datetime.min.time(), tzinfo=TZ_LOCAL)
    fin_dia = inicio_dia + timedelta(days=1)
    inicio_db = inicio_dia.strftime("%Y-%m-%d %H:%M:%S")
    fin_db = fin_dia.strftime("%Y-%m-%d %H:%M:%S")

    conn = conectar()

    ahora = datetime.now(TZ_LOCAL)
    es_hoy = fecha_obj == ahora.date()

    # Las opciones de reprogramación usan exactamente la misma lógica que
    # el simulador del transportista: solo franjas futuras, no bloqueadas y
    # con capacidad disponible. Así la web no ofrece horarios imposibles.
    opciones_reprogramacion = listar_franjas_disponibles(
        conn,
        limite=32,
        desde=ahora,
    )

    citas = conn.execute(
        """
        SELECT
            c.id, c.manifiesto_id, c.contenedor_id, c.transportista_id,
            c.camion_id, c.inicio, c.fin, c.estado, c.dentro_ventana,
            t.nombre AS transportista,
            cam.placa AS vehiculo,
            d.canal
        FROM citas c
        JOIN transportistas t ON t.id = c.transportista_id
        LEFT JOIN camiones cam ON cam.id = c.camion_id
        LEFT JOIN declaraciones d ON d.manifiesto_id = c.manifiesto_id
        WHERE c.inicio >= ? AND c.inicio < ?
        ORDER BY c.inicio ASC, c.id ASC
        """,
        (inicio_db, fin_db),
    ).fetchall()

    bloqueos = conn.execute(
        """
        SELECT inicio, fin, motivo
        FROM franjas_citas
        WHERE bloqueada = 1 AND inicio >= ? AND inicio < ?
        """,
        (inicio_db, fin_db),
    ).fetchall()
    bloqueos_por_inicio = {b["inicio"]: dict(b) for b in bloqueos}

    citas_por_inicio = {}
    for cita in citas:
        citas_por_inicio.setdefault(cita["inicio"], []).append(dict(cita))

    agenda = []
    cursor = inicio_dia
    for _ in range((24 * 60) // MINUTOS_FRANJA):
        inicio_texto = cursor.strftime("%Y-%m-%d %H:%M:%S")
        fin_slot = cursor + timedelta(minutes=MINUTOS_FRANJA)
        lista = citas_por_inicio.get(inicio_texto, [])
        bloqueo = bloqueos_por_inicio.get(inicio_texto)
        es_pasada = fin_slot <= ahora if es_hoy else fecha_obj < ahora.date()
        agenda.append({
            "inicio_db": inicio_texto,
            "inicio_input": cursor.strftime("%Y-%m-%dT%H:%M"),
            "hora_inicio": cursor.strftime("%H:%M"),
            "hora_fin": fin_slot.strftime("%H:%M"),
            "ocupadas": sum(1 for c in lista if c["estado"] == "PROGRAMADA"),
            "capacidad": CAPACIDAD_FRANJA,
            "bloqueada": bloqueo is not None,
            "motivo_bloqueo": bloqueo["motivo"] if bloqueo else None,
            "pasada": es_pasada,
            "citas": lista,
        })
        cursor = fin_slot

    cumplidas = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN dentro_ventana = 1 THEN 1 ELSE 0 END) AS dentro
        FROM citas
        WHERE inicio >= ? AND inicio < ?
          AND estado = 'CUMPLIDA'
        """,
        (inicio_db, fin_db),
    ).fetchone()
    porcentaje_cumplimiento = None
    if cumplidas["total"]:
        porcentaje_cumplimiento = round(
            100.0 * (cumplidas["dentro"] or 0) / cumplidas["total"], 1
        )

    transportistas = conn.execute(
        """
        SELECT t.id, t.nombre,
               mv.cuenta_id AS telegram_cuenta,
               mv.vinculada_at
        FROM transportistas t
        LEFT JOIN mensajeria_vinculos mv
               ON mv.transportista_id = t.id AND mv.canal = 'TELEGRAM'
        WHERE t.activo = 1
        ORDER BY t.nombre
        """
    ).fetchall()

    codigos = conn.execute(
        """
        SELECT cv.codigo, cv.transportista_id, cv.expira_at, cv.usado,
               t.nombre AS transportista
        FROM codigos_vinculacion cv
        JOIN transportistas t ON t.id = cv.transportista_id
        ORDER BY cv.created_at DESC
        LIMIT 12
        """
    ).fetchall()

    conn.close()

    return render_template(
        "terminal_citas.html",
        user=user,
        tabs=menu_para(user),
        fecha=fecha_texto,
        agenda=agenda,
        porcentaje_cumplimiento=porcentaje_cumplimiento,
        transportistas=transportistas,
        codigos=codigos,
        opciones_reprogramacion=opciones_reprogramacion,
        ahora_local=ahora.strftime("%Y-%m-%d %H:%M"),
    )


@app.post("/terminal/citas/<int:cita_id>/cancelar")
@roles_required("TERMINAL")
def terminal_cita_cancelar(cita_id):
    user = usuario_actual()
    fecha = request.form.get("fecha", "").strip()
    try:
        cancelar_cita(cita_id, usuario_id=user["id"])
        flash(f"Cita {cita_id} cancelada correctamente.", "ok")
    except ErrorCita as exc:
        flash(str(exc), "error")
    return redirect(url_for("terminal_citas", fecha=fecha) if fecha else url_for("terminal_citas"))


@app.post("/terminal/citas/<int:cita_id>/reprogramar")
@roles_required("TERMINAL")
def terminal_cita_reprogramar(cita_id):
    user = usuario_actual()
    fecha = request.form.get("fecha", "").strip()
    nuevo_inicio = request.form.get("nuevo_inicio", "").strip()
    try:
        reprogramar_cita(cita_id, nuevo_inicio, usuario_id=user["id"])
        flash(f"Cita {cita_id} reprogramada correctamente.", "ok")
    except ErrorCita as exc:
        flash(str(exc), "error")
    return redirect(url_for("terminal_citas", fecha=fecha) if fecha else url_for("terminal_citas"))


@app.post("/terminal/citas/bloquear")
@roles_required("TERMINAL")
def terminal_cita_bloquear():
    user = usuario_actual()
    fecha = request.form.get("fecha", "").strip()
    inicio = request.form.get("inicio", "").strip()
    motivo = request.form.get("motivo", "").strip()
    try:
        resultado = bloquear_franja(inicio, usuario_id=user["id"], motivo=motivo)
        flash(f"Franja {resultado['inicio']} bloqueada para nuevas citas.", "ok")
    except ErrorCita as exc:
        flash(str(exc), "error")
    return redirect(url_for("terminal_citas", fecha=fecha) if fecha else url_for("terminal_citas"))


@app.post("/terminal/citas/codigo-vinculacion")
@roles_required("TERMINAL")
def terminal_codigo_vinculacion():
    fecha = request.form.get("fecha", "").strip()
    transportista_texto = request.form.get("transportista_id", "").strip()
    try:
        transportista_id = int(transportista_texto)
    except ValueError:
        flash("Seleccione un transportista válido.", "error")
        return redirect(url_for("terminal_citas", fecha=fecha) if fecha else url_for("terminal_citas"))

    conn = conectar()
    transportista = conn.execute(
        "SELECT id, nombre FROM transportistas WHERE id = ? AND activo = 1",
        (transportista_id,),
    ).fetchone()
    conn.close()
    if transportista is None:
        flash("El transportista no existe o está inactivo.", "error")
        return redirect(url_for("terminal_citas", fecha=fecha) if fecha else url_for("terminal_citas"))

    codigo, expira_at = generar_codigo_vinculacion(transportista_id)
    flash(
        f"Código para {transportista['nombre']}: {codigo}. Expira en 60 minutos.",
        "ok",
    )
    return redirect(url_for("terminal_citas", fecha=fecha) if fecha else url_for("terminal_citas"))


# ============================================================
# NAVIERA - MANIFIESTOS
# ============================================================

@app.route("/naviera/manifiestos", methods=["GET", "POST"])
@roles_required("NAVIERA")
def naviera_manifiestos():
    user = usuario_actual()
    conn = conectar()

    if request.method == "POST":
        contenedor_id = request.form.get("contenedor_id", "").strip()
        operacion = request.form.get("operacion", "").strip().upper()
        peso_texto = request.form.get("peso_declarado_g", "").strip()
        tolerancia_texto = request.form.get("tolerancia_pct", "").strip()
        transportista_texto = request.form.get("transportista_id", "").strip()
        observaciones = request.form.get("observaciones", "").strip()

        errores = []

        contenedor = conn.execute(
            """
            SELECT id, naviera_id
            FROM contenedores
            WHERE id = ?
            """,
            (contenedor_id,),
        ).fetchone()

        if contenedor is None:
            errores.append("El contenedor no existe en el catálogo.")
        elif contenedor["naviera_id"] != user["naviera_id"]:
            errores.append("El contenedor no pertenece a esta naviera.")

        if operacion not in ("DEPOSITO", "RETIRO"):
            errores.append("Seleccione una operación válida.")

        try:
            peso = int(peso_texto)
            if peso <= 0:
                raise ValueError
        except ValueError:
            peso = None
            errores.append("El peso declarado debe ser un entero mayor que cero.")

        if tolerancia_texto == "":
            tolerancia = 5.0
        else:
            try:
                tolerancia = float(tolerancia_texto)
                if tolerancia < 0:
                    raise ValueError
            except ValueError:
                tolerancia = None
                errores.append("La tolerancia debe ser un porcentaje válido.")

        try:
            transportista_id = int(transportista_texto)
        except ValueError:
            transportista_id = None
            errores.append("Seleccione un transportista.")

        transportista = None
        if transportista_id is not None:
            transportista = conn.execute(
                """
                SELECT id
                FROM transportistas
                WHERE id = ? AND activo = 1
                """,
                (transportista_id,),
            ).fetchone()
            if transportista is None:
                errores.append("El transportista seleccionado no está registrado o está inactivo.")

        pendiente = None
        if contenedor_id:
            pendiente = conn.execute(
                """
                SELECT id
                FROM manifiestos
                WHERE contenedor_id = ?
                  AND estado_operativo = 'PENDIENTE'
                  AND anulado = 0
                """,
                (contenedor_id,),
            ).fetchone()

        if pendiente is not None:
            errores.append(
                f"El contenedor ya tiene el manifiesto pendiente {pendiente['id']}."
            )

        if errores:
            for error in errores:
                flash(error, "error")
        else:
            manifiesto_id = siguiente_id_manifiesto(conn)

            try:
                conn.execute("BEGIN IMMEDIATE")

                # Revalidación dentro de la transacción.
                existente = conn.execute(
                    """
                    SELECT id
                    FROM manifiestos
                    WHERE contenedor_id = ?
                      AND estado_operativo = 'PENDIENTE'
                      AND anulado = 0
                    """,
                    (contenedor_id,),
                ).fetchone()

                if existente:
                    raise ValueError(
                        f"El contenedor ya tiene el manifiesto pendiente {existente['id']}."
                    )

                conn.execute(
                    """
                    INSERT INTO manifiestos(
                        id,
                        naviera_id,
                        contenedor_id,
                        operacion,
                        peso_declarado_g,
                        tolerancia_pct,
                        transportista_id,
                        observaciones,
                        estado_documental,
                        estado_operativo
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'DECLARADO', 'PENDIENTE')
                    """,
                    (
                        manifiesto_id,
                        user["naviera_id"],
                        contenedor_id,
                        operacion,
                        peso,
                        tolerancia,
                        transportista_id,
                        observaciones or None,
                    ),
                )

                conn.execute(
                    """
                    INSERT INTO historial_manifiesto(
                        manifiesto_id,
                        campo,
                        valor_anterior,
                        valor_nuevo,
                        motivo,
                        usuario_id
                    )
                    VALUES (?, 'CREACION', NULL, 'DECLARADO', 'Nuevo manifiesto', ?)
                    """,
                    (manifiesto_id, user["id"]),
                )

                conn.commit()
                flash(f"Manifiesto {manifiesto_id} creado correctamente.", "ok")
                conn.close()
                return redirect(url_for("naviera_manifiestos"))

            except (sqlite3.IntegrityError, ValueError) as exc:
                conn.rollback()
                flash(str(exc), "error")

    manifiestos = conn.execute(
        """
        SELECT
            m.id,
            m.contenedor_id,
            m.operacion,
            m.peso_declarado_g,
            m.tolerancia_pct,
            m.estado_documental,
            m.estado_operativo,
            m.anulado,
            t.nombre AS transportista
        FROM manifiestos m
        JOIN transportistas t ON t.id = m.transportista_id
        WHERE m.naviera_id = ?
        ORDER BY m.created_at DESC, m.id DESC
        """,
        (user["naviera_id"],),
    ).fetchall()

    contenedores = conn.execute(
        """
        SELECT id
        FROM contenedores
        WHERE naviera_id = ?
        ORDER BY id
        """,
        (user["naviera_id"],),
    ).fetchall()

    transportistas = conn.execute(
        """
        SELECT id, nombre
        FROM transportistas
        WHERE activo = 1
        ORDER BY nombre
        """
    ).fetchall()

    conn.close()

    return render_template(
        "naviera_manifiestos.html",
        user=user,
        tabs=menu_para(user),
        manifiestos=manifiestos,
        contenedores=contenedores,
        transportistas=transportistas,
    )


@app.get("/naviera/manifiestos/<manifiesto_id>")
@roles_required("NAVIERA")
def naviera_manifiesto_detalle(manifiesto_id):
    user = usuario_actual()
    conn = conectar()

    manifiesto = conn.execute(
        """
        SELECT
            m.*,
            t.nombre AS transportista,
            n.nombre AS naviera
        FROM manifiestos m
        JOIN transportistas t ON t.id = m.transportista_id
        JOIN navieras n ON n.id = m.naviera_id
        WHERE m.id = ? AND m.naviera_id = ?
        """,
        (manifiesto_id, user["naviera_id"]),
    ).fetchone()

    if manifiesto is None:
        conn.close()
        abort(404)

    historial = conn.execute(
        """
        SELECT
            h.campo,
            h.valor_anterior,
            h.valor_nuevo,
            h.motivo,
            h.created_at,
            u.username
        FROM historial_manifiesto h
        LEFT JOIN usuarios u ON u.id = h.usuario_id
        WHERE h.manifiesto_id = ?
        ORDER BY h.id ASC
        """,
        (manifiesto_id,),
    ).fetchall()

    turno = conn.execute(
        "SELECT id, estado FROM turnos WHERE manifiesto_id = ? LIMIT 1",
        (manifiesto_id,),
    ).fetchone()

    conn.close()

    return render_template(
        "naviera_manifiesto_detalle.html",
        user=user,
        tabs=menu_para(user),
        manifiesto=manifiesto,
        historial=historial,
        turno=turno,
    )


@app.post("/naviera/manifiestos/<manifiesto_id>/anular")
@roles_required("NAVIERA")
def naviera_manifiesto_anular(manifiesto_id):
    user = usuario_actual()
    conn = conectar()

    manifiesto = conn.execute(
        """
        SELECT id, estado_operativo, anulado
        FROM manifiestos
        WHERE id = ? AND naviera_id = ?
        """,
        (manifiesto_id, user["naviera_id"]),
    ).fetchone()

    if manifiesto is None:
        conn.close()
        abort(404)

    turno = conn.execute(
        "SELECT id FROM turnos WHERE manifiesto_id = ? LIMIT 1",
        (manifiesto_id,),
    ).fetchone()

    if turno is not None:
        flash(
            f"No se puede anular: el manifiesto ya tiene el turno {turno['id']} asociado.",
            "error",
        )
    elif manifiesto["anulado"]:
        flash("El manifiesto ya está anulado.", "error")
    else:
        conn.execute(
            """
            UPDATE manifiestos
            SET anulado = 1,
                estado_operativo = 'ANULADO',
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (manifiesto_id,),
        )
        conn.execute(
            """
            INSERT INTO historial_manifiesto(
                manifiesto_id, campo, valor_anterior,
                valor_nuevo, motivo, usuario_id
            )
            VALUES (?, 'ESTADO_OPERATIVO', ?, 'ANULADO', 'Anulado por NAVIERA', ?)
            """,
            (manifiesto_id, manifiesto["estado_operativo"], user["id"]),
        )
        conn.commit()
        flash(f"Manifiesto {manifiesto_id} anulado.", "ok")

    conn.close()
    return redirect(url_for("naviera_manifiestos"))


# ============================================================
# NAVIERA - MIS CONTENEDORES
# ============================================================

@app.get("/naviera/contenedores")
@roles_required("NAVIERA")
def naviera_contenedores():
    user = usuario_actual()

    busqueda = request.args.get("q", "").strip()
    estado = request.args.get("estado", "").strip()

    conn = conectar()

    sql = """
        SELECT DISTINCT
            c.id,
            c.estado,
            c.ubicacion,
            c.nivel,
            c.permanencia_inicio,
            m.id AS manifiesto_id,
            m.estado_documental,
            m.estado_operativo,
            d.levante_estado,
            d.canal
        FROM contenedores c
        JOIN manifiestos m
          ON m.contenedor_id = c.id
         AND m.naviera_id = ?
        LEFT JOIN declaraciones d
          ON d.manifiesto_id = m.id
        WHERE c.naviera_id = ?
    """
    params = [user["naviera_id"], user["naviera_id"]]

    if busqueda:
        sql += " AND c.id LIKE ?"
        params.append(f"%{busqueda}%")

    if estado:
        sql += " AND c.estado = ?"
        params.append(estado)

    sql += " ORDER BY c.id"

    filas = conn.execute(sql, params).fetchall()

    estados = conn.execute(
        """
        SELECT DISTINCT c.estado
        FROM contenedores c
        JOIN manifiestos m ON m.contenedor_id = c.id
        WHERE c.naviera_id = ? AND m.naviera_id = ?
        ORDER BY c.estado
        """,
        (user["naviera_id"], user["naviera_id"]),
    ).fetchall()

    conn.close()

    return render_template(
        "naviera_contenedores.html",
        user=user,
        tabs=menu_para(user),
        contenedores=filas,
        estados=estados,
        q=busqueda,
        estado_filtro=estado,
    )


# ============================================================
# AGENTE - DECLARACIONES Y SEGUIMIENTO
# ============================================================

@app.get("/agente/declaraciones")
@roles_required("AGENTE")
def agente_declaraciones():
    user = usuario_actual()
    conn = conectar()

    filas = conn.execute(
        """
        SELECT
            m.id AS manifiesto_id,
            m.contenedor_id,
            m.operacion,
            m.peso_declarado_g,
            m.estado_documental,
            n.nombre AS naviera,
            d.id AS declaracion_id,
            d.numero AS numero_declaracion,
            d.estado AS declaracion_estado,
            d.levante_estado,
            d.canal,
            d.observacion,
            d.agente_usuario_id,
            (SELECT COUNT(*) FROM notas_declaracion nd WHERE nd.declaracion_id = d.id) AS notas_count
        FROM manifiestos m
        JOIN navieras n ON n.id = m.naviera_id
        LEFT JOIN declaraciones d ON d.manifiesto_id = m.id
        WHERE m.anulado = 0
          AND m.estado_operativo = 'PENDIENTE'
          AND (d.id IS NULL OR d.levante_estado IN ('NO_SOLICITADO','SOLICITADO','RETENIDO'))
        ORDER BY m.created_at ASC, m.id ASC
        """
    ).fetchall()
    conn.close()

    return render_template(
        "agente_declaraciones.html",
        user=user,
        tabs=menu_para(user),
        manifiestos=filas,
    )


@app.post("/agente/manifiestos/<manifiesto_id>/presentar-declaracion")
@roles_required("AGENTE")
def agente_presentar_declaracion(manifiesto_id):
    user = usuario_actual()
    numero = request.form.get("numero", "").strip()
    regimen = request.form.get("regimen", "").strip().upper()
    descripcion = request.form.get("descripcion", "").strip()
    valor_texto = request.form.get("valor_declarado", "").strip()

    errores = []
    if not numero:
        errores.append("El número de declaración es obligatorio.")
    if regimen not in ("IMPORTACION_DEFINITIVA", "DEPOSITO_TEMPORAL"):
        errores.append("Seleccione un régimen válido.")
    if len(descripcion) < 10:
        errores.append("La descripción de la mercancía debe tener al menos diez caracteres.")
    try:
        valor = float(valor_texto)
        if valor <= 0:
            raise ValueError
    except ValueError:
        valor = None
        errores.append("El valor declarado debe ser un número mayor que cero.")

    conn = conectar()
    manifiesto = conn.execute(
        """
        SELECT id, estado_documental, estado_operativo, anulado
        FROM manifiestos
        WHERE id = ?
        """,
        (manifiesto_id,),
    ).fetchone()

    if manifiesto is None or manifiesto["anulado"] or manifiesto["estado_operativo"] != "PENDIENTE":
        errores.append("El manifiesto no existe o ya no está disponible para declaración.")

    existente = conn.execute(
        "SELECT id FROM declaraciones WHERE manifiesto_id = ?",
        (manifiesto_id,),
    ).fetchone()
    if existente is not None:
        errores.append("Ese manifiesto ya tiene una declaración presentada.")

    repetida = conn.execute(
        "SELECT id FROM declaraciones WHERE numero = ?",
        (numero,),
    ).fetchone() if numero else None
    if repetida is not None:
        errores.append("El número de declaración ya existe en el sistema.")

    if errores:
        conn.close()
        for error in errores:
            flash(error, "error")
        return redirect(url_for("agente_declaraciones"))

    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO declaraciones(
                numero, manifiesto_id, agente_usuario_id, regimen,
                descripcion, valor_declarado, estado, levante_estado
            )
            VALUES (?, ?, ?, ?, ?, ?, 'PRESENTADA', 'NO_SOLICITADO')
            """,
            (numero, manifiesto_id, user["id"], regimen, descripcion, valor),
        )
        conn.execute(
            """
            UPDATE manifiestos
            SET estado_documental = 'DECLARACION_PRESENTADA',
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (manifiesto_id,),
        )
        conn.execute(
            """
            INSERT INTO historial_manifiesto(
                manifiesto_id, campo, valor_anterior, valor_nuevo, motivo, usuario_id
            ) VALUES (?, 'ESTADO_DOCUMENTAL', ?, 'DECLARACION_PRESENTADA', ?, ?)
            """,
            (
                manifiesto_id,
                manifiesto["estado_documental"],
                f"Declaración {numero} presentada por AGENTE",
                user["id"],
            ),
        )
        conn.commit()
        flash(f"Declaración {numero} presentada para el manifiesto {manifiesto_id}.", "ok")
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        flash(f"No fue posible presentar la declaración: {exc}", "error")
    finally:
        conn.close()

    return redirect(url_for("agente_declaraciones"))


@app.post("/agente/declaraciones/<int:declaracion_id>/solicitar-levante")
@roles_required("AGENTE")
def agente_solicitar_levante(declaracion_id):
    user = usuario_actual()
    conn = conectar()
    fila = conn.execute(
        """
        SELECT d.id, d.numero, d.manifiesto_id, d.agente_usuario_id,
               d.levante_estado, m.estado_documental, m.anulado
        FROM declaraciones d
        JOIN manifiestos m ON m.id = d.manifiesto_id
        WHERE d.id = ?
        """,
        (declaracion_id,),
    ).fetchone()

    if fila is None:
        conn.close()
        abort(404)
    if fila["agente_usuario_id"] != user["id"]:
        conn.close()
        abort(403)
    if fila["anulado"]:
        conn.close()
        flash("El manifiesto está anulado.", "error")
        return redirect(url_for("agente_declaraciones"))
    if fila["levante_estado"] != "NO_SOLICITADO":
        conn.close()
        flash("El levante de esta declaración ya fue solicitado o resuelto.", "error")
        return redirect(url_for("agente_declaraciones"))

    conn.execute(
        """
        UPDATE declaraciones
        SET levante_estado = 'SOLICITADO',
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (declaracion_id,),
    )
    conn.execute(
        """
        UPDATE manifiestos
        SET estado_documental = 'LEVANTE_SOLICITADO',
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (fila["manifiesto_id"],),
    )
    conn.execute(
        """
        INSERT INTO historial_manifiesto(
            manifiesto_id, campo, valor_anterior, valor_nuevo, motivo, usuario_id
        ) VALUES (?, 'ESTADO_DOCUMENTAL', ?, 'LEVANTE_SOLICITADO', ?, ?)
        """,
        (
            fila["manifiesto_id"],
            fila["estado_documental"],
            f"Levante solicitado para declaración {fila['numero']}",
            user["id"],
        ),
    )
    conn.commit()
    conn.close()
    flash(f"Levante solicitado para la declaración {fila['numero']}.", "ok")
    return redirect(url_for("agente_declaraciones"))


@app.post("/agente/declaraciones/<int:declaracion_id>/observacion")
@roles_required("AGENTE")
def agente_adjuntar_observacion(declaracion_id):
    user = usuario_actual()
    texto = request.form.get("observacion", "").strip()

    if not texto:
        flash("La observación no puede estar vacía.", "error")
        return redirect(url_for("agente_declaraciones"))

    conn = conectar()
    fila = conn.execute(
        """
        SELECT d.id, d.manifiesto_id, d.agente_usuario_id, d.observacion,
               d.levante_estado, m.anulado
        FROM declaraciones d
        JOIN manifiestos m ON m.id = d.manifiesto_id
        WHERE d.id = ?
        """,
        (declaracion_id,),
    ).fetchone()

    if fila is None:
        conn.close()
        abort(404)
    if fila["agente_usuario_id"] != user["id"]:
        conn.close()
        abort(403)
    if fila["anulado"]:
        conn.close()
        flash("No puede adjuntarse una observación a un manifiesto anulado.", "error")
        return redirect(url_for("agente_declaraciones"))

    conn.execute(
        """
        INSERT INTO notas_declaracion(declaracion_id, usuario_id, texto)
        VALUES (?, ?, ?)
        """,
        (declaracion_id, user["id"], texto),
    )
    conn.execute(
        """
        UPDATE declaraciones
        SET observacion = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (texto, declaracion_id),
    )
    conn.execute(
        """
        INSERT INTO historial_manifiesto(
            manifiesto_id, campo, valor_anterior, valor_nuevo, motivo, usuario_id
        ) VALUES (?, 'OBSERVACION_DOCUMENTAL', ?, ?, 'Observación adjuntada por AGENTE', ?)
        """,
        (fila["manifiesto_id"], fila["observacion"], texto, user["id"]),
    )
    conn.commit()
    conn.close()

    flash("Observación documental adjuntada y visible para la autoridad.", "ok")
    return redirect(url_for("agente_declaraciones"))


@app.get("/agente/seguimiento")
@roles_required("AGENTE")
def agente_seguimiento():
    user = usuario_actual()
    estado = request.args.get("estado", "").strip().upper()
    q = request.args.get("q", "").strip()

    sql = """
        SELECT
            d.id, d.numero, d.manifiesto_id, d.regimen, d.estado,
            d.levante_estado, d.canal, d.motivo_retencion,
            m.contenedor_id, n.nombre AS naviera
        FROM declaraciones d
        JOIN manifiestos m ON m.id = d.manifiesto_id
        JOIN navieras n ON n.id = m.naviera_id
        WHERE d.agente_usuario_id = ?
    """
    params = [user["id"]]
    if estado:
        sql += " AND d.levante_estado = ?"
        params.append(estado)
    if q:
        sql += " AND d.numero LIKE ?"
        params.append(f"%{q}%")
    sql += " ORDER BY d.created_at DESC, d.id DESC"

    conn = conectar()
    filas = conn.execute(sql, params).fetchall()
    conn.close()

    return render_template(
        "agente_seguimiento.html",
        user=user,
        tabs=menu_para(user),
        declaraciones=filas,
        estado_filtro=estado,
        q=q,
    )


# ============================================================
# AUTORIDAD - SOLICITUDES DE LEVANTE
# ============================================================

@app.get("/autoridad/solicitudes")
@roles_required("AUTORIDAD")
def autoridad_solicitudes():
    user = usuario_actual()
    conn = conectar()
    filas = conn.execute(
        """
        SELECT
            d.id AS declaracion_id,
            d.numero,
            d.regimen,
            d.descripcion,
            d.valor_declarado,
            d.levante_estado,
            d.canal,
            d.motivo_retencion,
            d.observacion,
            d.created_at,
            m.id AS manifiesto_id,
            m.contenedor_id,
            m.operacion,
            m.peso_declarado_g,
            n.nombre AS naviera,
            u.nombre AS agente
        FROM declaraciones d
        JOIN manifiestos m ON m.id = d.manifiesto_id
        JOIN navieras n ON n.id = m.naviera_id
        LEFT JOIN usuarios u ON u.id = d.agente_usuario_id
        WHERE m.anulado = 0
          AND d.levante_estado IN ('SOLICITADO','RETENIDO')
        ORDER BY d.updated_at ASC, d.id ASC
        """
    ).fetchall()
    conn.close()

    return render_template(
        "autoridad_solicitudes.html",
        user=user,
        tabs=menu_para(user),
        solicitudes=filas,
    )


@app.get("/autoridad/declaraciones/<int:declaracion_id>")
@roles_required("AUTORIDAD")
def autoridad_declaracion_detalle(declaracion_id):
    user = usuario_actual()
    conn = conectar()
    fila = conn.execute(
        """
        SELECT
            d.*, m.contenedor_id, m.operacion, m.peso_declarado_g,
            m.tolerancia_pct, m.estado_documental, m.estado_operativo,
            n.nombre AS naviera, t.nombre AS transportista,
            u.nombre AS agente
        FROM declaraciones d
        JOIN manifiestos m ON m.id = d.manifiesto_id
        JOIN navieras n ON n.id = m.naviera_id
        JOIN transportistas t ON t.id = m.transportista_id
        LEFT JOIN usuarios u ON u.id = d.agente_usuario_id
        WHERE d.id = ?
        """,
        (declaracion_id,),
    ).fetchone()
    if fila is None:
        conn.close()
        abort(404)

    notas = conn.execute(
        """
        SELECT nd.id, nd.texto, nd.created_at, u.nombre AS autor, u.rol
        FROM notas_declaracion nd
        JOIN usuarios u ON u.id = nd.usuario_id
        WHERE nd.declaracion_id = ?
        ORDER BY nd.created_at ASC, nd.id ASC
        """,
        (declaracion_id,),
    ).fetchall()
    conn.close()

    return render_template(
        "autoridad_declaracion_detalle.html",
        user=user,
        tabs=menu_para(user),
        declaracion=fila,
        notas=notas,
    )


@app.post("/autoridad/declaraciones/<int:declaracion_id>/otorgar")
@roles_required("AUTORIDAD")
def autoridad_otorgar_levante(declaracion_id):
    user = usuario_actual()
    canal = request.form.get("canal", "").strip().upper()
    if canal not in ("VERDE", "ROJO"):
        flash("Debe seleccionar un canal válido: VERDE o ROJO.", "error")
        return redirect(url_for("autoridad_solicitudes"))

    conn = conectar()
    fila = conn.execute(
        """
        SELECT d.id, d.numero, d.manifiesto_id, d.levante_estado,
               m.estado_documental, m.anulado,
               m.transportista_id, m.contenedor_id
        FROM declaraciones d
        JOIN manifiestos m ON m.id = d.manifiesto_id
        WHERE d.id = ?
        """,
        (declaracion_id,),
    ).fetchone()

    if fila is None:
        conn.close()
        abort(404)
    if fila["anulado"]:
        conn.close()
        flash("No puede otorgarse levante a un manifiesto anulado.", "error")
        return redirect(url_for("autoridad_solicitudes"))
    if fila["levante_estado"] not in ("SOLICITADO", "RETENIDO"):
        conn.close()
        flash("La solicitud ya fue resuelta y no puede volver a otorgarse.", "error")
        return redirect(url_for("autoridad_solicitudes"))

    conn.execute(
        """
        UPDATE declaraciones
        SET levante_estado = 'OTORGADO',
            canal = ?,
            motivo_retencion = NULL,
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (canal, declaracion_id),
    )
    conn.execute(
        """
        UPDATE manifiestos
        SET estado_documental = 'LEVANTE_OTORGADO',
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (fila["manifiesto_id"],),
    )
    conn.execute(
        """
        INSERT INTO historial_manifiesto(
            manifiesto_id, campo, valor_anterior, valor_nuevo, motivo, usuario_id
        ) VALUES (?, 'ESTADO_DOCUMENTAL', ?, 'LEVANTE_OTORGADO', ?, ?)
        """,
        (
            fila["manifiesto_id"],
            fila["estado_documental"],
            f"Levante otorgado. Canal {canal}",
            user["id"],
        ),
    )
    extra = " El vehículo será enviado a verificación después del pesaje de entrada." if canal == "ROJO" else ""
    encolar_notificacion(
        conn,
        fila["transportista_id"],
        "LEVANTE_OTORGADO",
        f"Contenedor {fila['contenedor_id']}: levante otorgado. Canal {canal}.{extra}",
    )
    conn.commit()
    conn.close()

    flash(f"Levante otorgado para {fila['numero']} con canal {canal}.", "ok")
    return redirect(url_for("autoridad_solicitudes"))


@app.post("/autoridad/declaraciones/<int:declaracion_id>/retener")
@roles_required("AUTORIDAD")
def autoridad_retener_levante(declaracion_id):
    user = usuario_actual()
    motivo = request.form.get("motivo", "").strip()
    if not motivo:
        flash("Debe indicar la causa de la retención del levante.", "error")
        return redirect(url_for("autoridad_solicitudes"))

    conn = conectar()
    fila = conn.execute(
        """
        SELECT d.id, d.numero, d.manifiesto_id, d.levante_estado,
               m.estado_documental, m.anulado,
               m.transportista_id, m.contenedor_id
        FROM declaraciones d
        JOIN manifiestos m ON m.id = d.manifiesto_id
        WHERE d.id = ?
        """,
        (declaracion_id,),
    ).fetchone()

    if fila is None:
        conn.close()
        abort(404)
    if fila["anulado"]:
        conn.close()
        flash("No puede retenerse el levante de un manifiesto anulado.", "error")
        return redirect(url_for("autoridad_solicitudes"))
    if fila["levante_estado"] not in ("SOLICITADO", "RETENIDO"):
        conn.close()
        flash("La solicitud ya fue resuelta.", "error")
        return redirect(url_for("autoridad_solicitudes"))

    conn.execute(
        """
        UPDATE declaraciones
        SET levante_estado = 'RETENIDO',
            canal = NULL,
            motivo_retencion = ?,
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (motivo, declaracion_id),
    )
    conn.execute(
        """
        UPDATE manifiestos
        SET estado_documental = 'LEVANTE_RETENIDO',
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (fila["manifiesto_id"],),
    )
    conn.execute(
        """
        INSERT INTO historial_manifiesto(
            manifiesto_id, campo, valor_anterior, valor_nuevo, motivo, usuario_id
        ) VALUES (?, 'ESTADO_DOCUMENTAL', ?, 'LEVANTE_RETENIDO', ?, ?)
        """,
        (
            fila["manifiesto_id"],
            fila["estado_documental"],
            f"Levante retenido: {motivo}",
            user["id"],
        ),
    )
    encolar_notificacion(
        conn,
        fila["transportista_id"],
        "LEVANTE_RETENIDO",
        f"Contenedor {fila['contenedor_id']}: levante retenido. Motivo: {motivo}",
    )
    conn.commit()
    conn.close()

    flash(f"Levante retenido para {fila['numero']}.", "ok")
    return redirect(url_for("autoridad_solicitudes"))


@app.get("/autoridad/retenciones-aduaneras")
@roles_required("AUTORIDAD")
def autoridad_retenciones_aduaneras():
    user = usuario_actual()
    estado = request.args.get("estado", "").strip().upper()
    causa = request.args.get("causa", "").strip().upper()

    sql = """
        SELECT
            r.id,
            r.turno_id,
            r.causa,
            r.plaza,
            r.estado,
            r.resolucion,
            r.rol_resolutor,
            r.motivo,
            r.peso_declarado_g,
            r.peso_medido_g,
            r.inicio,
            r.fin,
            r.estacion_origen,
            r.observacion_resolucion,
            r.motivo_resolucion,
            t.estado AS turno_estado,
            t.estado_previo_retencion,
            t.estacion AS turno_estacion,
            t.contenedor_id,
            c.placa AS vehiculo,
            m.id AS manifiesto_id,
            d.numero AS numero_declaracion,
            d.canal
        FROM retenciones r
        LEFT JOIN turnos t ON t.id = r.turno_id
        LEFT JOIN camiones c ON c.id = t.camion_id
        LEFT JOIN manifiestos m ON m.id = t.manifiesto_id
        LEFT JOIN declaraciones d ON d.manifiesto_id = m.id
        WHERE r.causa IN ('RT03','RT05','RT08')
    """
    params = []

    if estado in ("ACTIVA", "RESUELTA"):
        sql += " AND r.estado = ?"
        params.append(estado)
    if causa in ("RT03", "RT05", "RT08"):
        sql += " AND r.causa = ?"
        params.append(causa)

    sql += " ORDER BY CASE WHEN r.estado = 'ACTIVA' THEN 0 ELSE 1 END, r.inicio DESC, r.id DESC"

    conn = conectar()
    filas = conn.execute(sql, params).fetchall()
    conn.close()

    return render_template(
        "autoridad_retenciones_aduaneras.html",
        user=user,
        tabs=menu_para(user),
        retenciones=filas,
        estado_filtro=estado,
        causa_filtro=causa,
    )


def _cargar_retencion_aduanera(conn, retencion_id):
    return conn.execute(
        """
        SELECT r.*, t.estado AS turno_estado, t.estado_previo_retencion,
               t.estacion AS turno_estacion, t.manifiesto_id,
               t.contenedor_id
        FROM retenciones r
        LEFT JOIN turnos t ON t.id = r.turno_id
        WHERE r.id = ? AND r.causa IN ('RT03','RT05','RT08')
        """,
        (retencion_id,),
    ).fetchone()


def _liberar_plaza_logica(conn, retencion):
    if retencion["plaza"] is None:
        return
    conn.execute(
        """
        UPDATE plazas_retencion
        SET ocupada = 0, turno_id = NULL, ocupada_desde = NULL
        WHERE numero = ?
          AND (turno_id = ? OR turno_id IS NULL)
        """,
        (retencion["plaza"], retencion["turno_id"]),
    )


# v0.5.3: las resoluciones de TERMINAL y AUTORIDAD usan AgujaLiberar real
# y esperan ACK/NACK del controlador antes de modificar SQLite.

@app.post("/autoridad/retenciones/<int:retencion_id>/aclarar")
@roles_required("AUTORIDAD")
def autoridad_retencion_aclarar(retencion_id):
    user = usuario_actual()
    ok, mensaje = _resolver_retencion_con_controlador(
        retencion_id,
        "AUTORIDAD",
        "ACLARAR",
        user,
        observacion=request.form.get("observacion", ""),
    )
    flash(mensaje, "ok" if ok else "error")
    return redirect(url_for("autoridad_retenciones_aduaneras"))


@app.post("/autoridad/retenciones/<int:retencion_id>/rechazar")
@roles_required("AUTORIDAD")
def autoridad_retencion_rechazar(retencion_id):
    user = usuario_actual()
    ok, mensaje = _resolver_retencion_con_controlador(
        retencion_id,
        "AUTORIDAD",
        "RECHAZAR",
        user,
        motivo=request.form.get("motivo", ""),
    )
    flash(mensaje, "ok" if ok else "error")
    return redirect(url_for("autoridad_retenciones_aduaneras"))


@app.get("/autoridad/consulta-carga")
@roles_required("AUTORIDAD")
def autoridad_consulta_carga():
    user = usuario_actual()
    q = request.args.get("q", "").strip()
    naviera_id = request.args.get("naviera_id", "").strip()
    autorizacion = request.args.get("autorizacion", "").strip().upper()

    base = """
        SELECT
            c.id,
            c.estado,
            c.ubicacion,
            c.nivel,
            c.permanencia_inicio,
            n.id AS naviera_id,
            n.nombre AS naviera,
            m.id AS manifiesto_id,
            m.operacion,
            m.estado_documental,
            m.estado_operativo,
            d.numero AS numero_declaracion,
            d.levante_estado,
            d.canal,
            d.motivo_retencion,
            CASE
                WHEN d.levante_estado = 'OTORGADO' AND d.canal = 'VERDE' THEN 'LEVANTE_VERDE'
                WHEN d.levante_estado = 'OTORGADO' AND d.canal = 'ROJO' THEN 'LEVANTE_ROJO'
                WHEN d.levante_estado = 'RETENIDO' THEN 'RETENIDO'
                WHEN d.levante_estado = 'SOLICITADO' THEN 'SOLICITADO'
                WHEN d.id IS NOT NULL THEN 'DECLARACION_PRESENTADA'
                WHEN m.id IS NOT NULL THEN 'SIN_DECLARACION'
                ELSE 'SIN_MANIFIESTO'
            END AS autorizacion
        FROM contenedores c
        LEFT JOIN navieras n ON n.id = c.naviera_id
        LEFT JOIN manifiestos m ON m.id = (
            SELECT m2.id
            FROM manifiestos m2
            WHERE m2.contenedor_id = c.id
              AND m2.anulado = 0
            ORDER BY
                CASE WHEN m2.estado_operativo = 'PENDIENTE' THEN 0 ELSE 1 END,
                m2.updated_at DESC,
                m2.rowid DESC
            LIMIT 1
        )
        LEFT JOIN declaraciones d ON d.manifiesto_id = m.id
    """

    filtros = []
    params = []
    if q:
        filtros.append("id LIKE ?")
        params.append(f"%{q}%")
    if naviera_id.isdigit():
        filtros.append("naviera_id = ?")
        params.append(int(naviera_id))
    autorizaciones_validas = {
        "LEVANTE_VERDE", "LEVANTE_ROJO", "RETENIDO", "SOLICITADO",
        "DECLARACION_PRESENTADA", "SIN_DECLARACION", "SIN_MANIFIESTO",
    }
    if autorizacion in autorizaciones_validas:
        filtros.append("autorizacion = ?")
        params.append(autorizacion)

    sql = f"SELECT * FROM ({base}) consulta"
    if filtros:
        sql += " WHERE " + " AND ".join(filtros)
    sql += " ORDER BY id"

    conn = conectar()
    filas = conn.execute(sql, params).fetchall()
    navieras = conn.execute(
        "SELECT id, nombre FROM navieras WHERE activo = 1 ORDER BY nombre"
    ).fetchall()
    conn.close()

    return render_template(
        "autoridad_consulta_carga.html",
        user=user,
        tabs=menu_para(user),
        contenedores=filas,
        navieras=navieras,
        q=q,
        naviera_filtro=naviera_id,
        autorizacion_filtro=autorizacion,
    )


# ============================================================
# API / BASE EXISTENTE
# ============================================================

@app.get("/api/health")
def api_health():
    return jsonify({"ok": True, "service": "PORTUS", "database": "sqlite"})


@app.get("/api/me")
@login_required
def api_me():
    return jsonify({"ok": True, "user": usuario_actual()})


@app.get("/api/terminal/resumen")
@roles_required("TERMINAL")
def api_terminal_resumen():
    conn = conectar()

    turnos_activos = conn.execute(
        "SELECT COUNT(*) AS n FROM turnos WHERE estado NOT IN ('Cerrado','Anulado')"
    ).fetchone()["n"]
    retenciones = conn.execute(
        "SELECT COUNT(*) AS n FROM retenciones WHERE estado = 'ACTIVA'"
    ).fetchone()["n"]
    alarmas = conn.execute(
        "SELECT COUNT(*) AS n FROM alarmas WHERE estado = 'ACTIVA'"
    ).fetchone()["n"]
    citas = conn.execute(
        "SELECT COUNT(*) AS n FROM citas WHERE estado = 'PROGRAMADA'"
    ).fetchone()["n"]
    heartbeat = conn.execute(
        """
        SELECT timestamp, secuencia, estado_general
        FROM telemetria
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()

    conn.close()

    return jsonify({
        "ok": True,
        "turnos_activos": turnos_activos,
        "retenciones_activas": retenciones,
        "alarmas_activas": alarmas,
        "citas_programadas": citas,
        "ultimo_heartbeat": dict(heartbeat) if heartbeat else None,
    })


@app.get("/api/naviera/manifiestos")
@roles_required("NAVIERA")
def api_naviera_manifiestos():
    user = usuario_actual()
    conn = conectar()
    filas = conn.execute(
        """
        SELECT id, contenedor_id, operacion, peso_declarado_g,
               tolerancia_pct, estado_documental, estado_operativo
        FROM manifiestos
        WHERE naviera_id = ?
        ORDER BY created_at DESC
        """,
        (user["naviera_id"],),
    ).fetchall()
    conn.close()
    return jsonify({"ok": True, "manifiestos": [dict(f) for f in filas]})


@app.get("/api/agente/declaraciones")
@roles_required("AGENTE")
def api_agente_declaraciones():
    user = usuario_actual()
    conn = conectar()
    filas = conn.execute(
        """
        SELECT numero, manifiesto_id, regimen, estado,
               levante_estado, canal, motivo_retencion, observacion
        FROM declaraciones
        WHERE agente_usuario_id = ?
        ORDER BY created_at DESC
        """,
        (user["id"],),
    ).fetchall()
    conn.close()
    return jsonify({"ok": True, "declaraciones": [dict(f) for f in filas]})


@app.get("/api/autoridad/solicitudes")
@roles_required("AUTORIDAD")
def api_autoridad_solicitudes():
    conn = conectar()
    filas = conn.execute(
        """
        SELECT d.numero, d.manifiesto_id, d.regimen,
               d.valor_declarado, d.levante_estado, d.observacion,
               m.contenedor_id, m.peso_declarado_g
        FROM declaraciones d
        JOIN manifiestos m ON m.id = d.manifiesto_id
        WHERE d.levante_estado IN ('SOLICITADO','RETENIDO')
        ORDER BY d.created_at ASC
        """
    ).fetchall()
    conn.close()
    return jsonify({"ok": True, "solicitudes": [dict(f) for f in filas]})


@app.errorhandler(403)
def forbidden(error):
    user = usuario_actual()
    if user:
        return render_template(
            "error.html",
            user=user,
            tabs=menu_para(user),
            titulo="Acceso denegado",
            mensaje="Tu rol no tiene permiso para ejecutar esta acción.",
        ), 403
    return "Acceso denegado", 403


@app.errorhandler(404)
def not_found(error):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "RUTA_NO_ENCONTRADA"}), 404

    user = usuario_actual()
    if user:
        return render_template(
            "error.html",
            user=user,
            tabs=menu_para(user),
            titulo="No encontrado",
            mensaje="El recurso solicitado no existe o no pertenece a tu usuario.",
        ), 404
    return "Página no encontrada", 404


from fase3_db import migrar as migrar_fase3
from fase3_web import instalar as instalar_fase3_web
inicializar_bd()
migrar_fase3()
TABS_POR_ROL['TERMINAL'].extend([('Accesos','terminal_accesos'),('Parámetros F3','terminal_parametros_fase3')])
TABS_POR_ROL['AUTORIDAD'].append(('Placas restringidas','autoridad_placas_restringidas'))
instalar_fase3_web(app, roles_required, usuario_actual, menu_para)

from web_supervision_portus import instalar as instalar_supervision
instalar_supervision(app, roles_required, usuario_actual, menu_para, enviar_comando_controlador)


def main():
    inicializar_bd()

    if app.secret_key == "PORTUS-DEMO-CAMBIAR-ESTA-CLAVE":
        print("[ADVERTENCIA] PORTUS_SECRET_KEY no está definida.")

    print("PORTUS Fase 3 v1.0 - Accesos, OCR, clima, iluminación, operación")
    print("Escuchando en http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)


if __name__ == "__main__":
    main()
