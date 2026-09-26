# -*- coding: utf-8 -*-
"""
PORTUS - Fase 2 - Interfaces web (Compañero 2)
Aplicación con datos ficticios (mock_data.py) y validaciones de servidor.

Ejecutar:
    pip install flask
    python app.py
Abrir http://localhost:5000
"""
import csv
import io
import secrets
import string
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, Response
)

import mock_data as db

app = Flask(__name__)
app.secret_key = "clave-de-desarrollo-portus-fase2"


# ---------------------------------------------------------------------------
# Sesión y control de permisos por rol
# ---------------------------------------------------------------------------
def login_required(*roles_permitidos):
    def decorador(f):
        @wraps(f)
        def envoltura(*args, **kwargs):
            if "usuario" not in session:
                flash("Debes iniciar sesión.", "warning")
                return redirect(url_for("login"))
            if roles_permitidos and session.get("rol") not in roles_permitidos:
                flash("No tienes permiso para realizar esta acción.", "danger")
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return envoltura
    return decorador


@app.context_processor
def inject_usuario():
    return {
        "usuario_sesion": session.get("usuario"),
        "rol_sesion": session.get("rol"),
        "nombre_sesion": session.get("nombre"),
        "entidad_sesion": session.get("entidad"),
    }


# ---------------------------------------------------------------------------
# Validación fina por causa de retención (PDF 8.2 / 8.3)
# ---------------------------------------------------------------------------
ROLES_POR_CAUSA = {
    "RT01": {"TERMINAL"},
    "RT02": {"TERMINAL"},
    "RT03": {"AUTORIDAD"},
    "RT04": {"TERMINAL"},
    "RT05": {"AUTORIDAD"},
    "RT06": {"TERMINAL"},
}

ACCIONES_POR_ROL = {
    "TERMINAL":  {"Aclarar", "Corregir", "Rechazar"},
    "AUTORIDAD": {"Aclarar", "Rechazar"},   # sin "Corregir"
}


def codigo_causa(retencion):
    causa = (retencion or {}).get("causa", "")
    return causa.split(" ")[0].split("-")[0].strip().upper()


def puede_resolver(retencion, rol, accion):
    if not retencion:
        return False, "Retención no encontrada."
    if retencion.get("estado") == "Resuelta":
        return False, "Esta retención ya fue resuelta."

    codigo = codigo_causa(retencion)
    if rol not in ROLES_POR_CAUSA.get(codigo, set()):
        return False, f"El rol {rol} no puede resolver retenciones de causa {codigo}."
    if accion not in ACCIONES_POR_ROL.get(rol, set()):
        return False, f"El rol {rol} no puede ejecutar la acción '{accion}'."
    return True, None


# ---------------------------------------------------------------------------
# Utilidades para códigos de vinculación
# ---------------------------------------------------------------------------
def generar_codigo(longitud=6):
    """Código de 6 caracteres alfanuméricos en mayúsculas, seguro."""
    alfabeto = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alfabeto) for _ in range(longitud))


# ---------------------------------------------------------------------------
# LOGIN / LOGOUT / HOME
# ---------------------------------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        password = request.form.get("password", "")
        datos = db.USUARIOS.get(usuario)
        if datos and datos["password"] == password:
            session["usuario"] = usuario
            session["rol"] = datos["rol"]
            session["nombre"] = datos["nombre"]
            session["entidad"] = datos.get("entidad")
            return redirect(url_for("home"))
        flash("Usuario o contraseña incorrectos.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/home")
@login_required()
def home():
    rol = session.get("rol")
    destino = {
        "TERMINAL": "terminal_operacion",
        "NAVIERA": "naviera_manifiestos",
        "AGENTE": "agente_declaraciones",
        "AUTORIDAD": "autoridad_levante",
    }.get(rol, "login")
    return redirect(url_for(destino))


# ---------------------------------------------------------------------------
# ROL: TERMINAL
# ---------------------------------------------------------------------------
@app.route("/terminal/operacion")
@login_required("TERMINAL")
def terminal_operacion():
    return render_template(
        "terminal/operacion.html",
        turnos=db.TURNOS,
        grua=db.GRUA,
        retenciones=[r for r in db.RETENCIONES if r["estado"] == "Abierta"],
    )


@app.route("/terminal/turnos")
@login_required("TERMINAL")
def terminal_turnos():
    filtro_estado = request.args.get("estado", "")
    filtro_tipo = request.args.get("tipo", "")
    turnos = db.TURNOS
    if filtro_estado:
        turnos = [t for t in turnos if t["estado"] == filtro_estado]
    if filtro_tipo:
        turnos = [t for t in turnos if t["tipo"] == filtro_tipo]
    return render_template(
        "terminal/turnos.html",
        turnos=turnos,
        filtro_estado=filtro_estado,
        filtro_tipo=filtro_tipo,
    )


@app.route("/terminal/turnos/<turno_id>")
@login_required("TERMINAL")
def terminal_turno_detalle(turno_id):
    turno = next((t for t in db.TURNOS if t["id"] == turno_id), None)
    linea_tiempo = [
        {"hora": "08:15:02", "origen": "controlador", "evento": "Vehículo identificado en garita"},
        {"hora": "08:15:40", "origen": "controlador", "evento": "Pesaje de entrada", "valor": "24700 g"},
        {"hora": "08:16:10", "origen": "servidor", "evento": "Ruta autorizada hacia transferencia"},
        {"hora": "08:20:05", "origen": "controlador", "evento": "Grúa deposita contenedor", "valor": "A1-1"},
    ]
    return render_template("terminal/turno_detalle.html", turno=turno, linea_tiempo=linea_tiempo)


@app.route("/terminal/retenciones", methods=["GET", "POST"])
@login_required("TERMINAL")
def terminal_retenciones():
    if request.method == "POST":
        ret_id = request.form.get("ret_id")
        accion = request.form.get("accion")
        motivo = (request.form.get("motivo") or "").strip()
        observacion = (request.form.get("observacion") or "").strip()

        ret = next((r for r in db.RETENCIONES if r["id"] == ret_id), None)

        ok, error = puede_resolver(ret, session.get("rol"), accion)
        if not ok:
            flash(error, "danger")
            return redirect(url_for("terminal_retenciones"))

        if accion == "Rechazar" and not motivo:
            flash("Debe indicar el motivo al rechazar.", "danger")
            return redirect(url_for("terminal_retenciones"))

        ret["estado"] = "Resuelta"
        ret["resolucion"] = accion
        ret["motivo"] = motivo if accion == "Rechazar" else None
        ret["observacion"] = observacion or None

        flash(f"Retención {ret_id} resuelta mediante '{accion}'.", "success")
        return redirect(url_for("terminal_retenciones"))

    return render_template("terminal/retenciones.html", retenciones=db.RETENCIONES)


@app.route("/terminal/patio")
@login_required("TERMINAL")
def terminal_patio():
    return render_template("terminal/patio.html", contenedores=db.CONTENEDORES)


@app.route("/terminal/grua")
@login_required("TERMINAL")
def terminal_grua():
    return render_template("terminal/grua.html", grua=db.GRUA)


@app.route("/terminal/alarmas", methods=["GET", "POST"])
@login_required("TERMINAL")
def terminal_alarmas():
    if request.method == "POST":
        alarma_id = request.form.get("alarma_id")
        alarma = next((a for a in db.ALARMAS if a["id"] == alarma_id), None)
        if alarma:
            alarma["reconocida"] = True
        return redirect(url_for("terminal_alarmas"))
    activas = [a for a in db.ALARMAS if not a["reconocida"]]
    historicas = [a for a in db.ALARMAS if a["reconocida"]]
    return render_template("terminal/alarmas.html", activas=activas, historicas=historicas)


@app.route("/terminal/citas", methods=["GET", "POST"])
@login_required("TERMINAL")
def terminal_citas():
    nuevo_codigo = None

    if request.method == "POST":
        accion = request.form.get("accion")

        if accion == "generar_codigo":
            transportista = request.form.get("transportista", "").strip()
            if not transportista:
                flash("Debe seleccionar un transportista.", "danger")
            else:
                # Invalida códigos previos activos del mismo transportista
                for c in db.CODIGOS_VINCULACION:
                    if c["transportista"] == transportista and not c["usado"]:
                        c["usado"] = True

                nuevo_codigo = generar_codigo(6)
                db.CODIGOS_VINCULACION.append({
                    "codigo": nuevo_codigo,
                    "transportista": transportista,
                    "creado": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "expira_en_min": 60,
                    "usado": False,
                })
                flash(f"Código generado para {transportista}: {nuevo_codigo}", "success")

    return render_template(
        "terminal/citas.html",
        agenda=db.CITAS,
        transportistas=db.TRANSPORTISTAS,
        codigos=db.CODIGOS_VINCULACION,
        nuevo_codigo=nuevo_codigo,
    )


@app.route("/terminal/reportes", methods=["GET", "POST"])
@login_required("TERMINAL")
def terminal_reportes():
    metricas = None
    etiqueta = ""
    desde = ""
    hasta = ""

    if request.method == "POST":
        etiqueta = request.form.get("etiqueta", "").strip()
        desde = request.form.get("desde", "")
        hasta = request.form.get("hasta", "")

        if request.form.get("accion") == "exportar":
            salida = io.StringIO()
            writer = csv.writer(salida)
            writer.writerow(["Metrica", "Valor"])
            for k, v in db.METRICAS_MOCK.items():
                writer.writerow([k, str(v)])
            writer.writerow([])
            writer.writerow(["Turno", "Vehiculo", "Contenedor", "Tipo", "Estado", "Tiempo"])
            for t in db.TURNOS:
                writer.writerow([t["id"], t["vehiculo"], t["contenedor"],
                                 t["tipo"], t["estado"], t["tiempo"]])
            return Response(
                salida.getvalue(),
                mimetype="text/csv",
                headers={
                    "Content-Disposition": f"attachment; filename=portus_{etiqueta or 'corrida'}.csv"
                },
            )

        metricas = db.METRICAS_MOCK

    return render_template(
        "terminal/reportes.html",
        metricas=metricas,
        etiqueta=etiqueta,
        desde=desde,
        hasta=hasta,
    )


# ---------------------------------------------------------------------------
# ROL: NAVIERA (con aislamiento estricto)
# ---------------------------------------------------------------------------
@app.route("/naviera/manifiestos", methods=["GET", "POST"])
@login_required("NAVIERA")
def naviera_manifiestos():
    entidad = session.get("entidad")   # "NAVIERA1" o "NAVIERA2"

    if request.method == "POST":
        contenedor = request.form.get("contenedor", "").strip()
        tipo = request.form.get("tipo", "").strip()
        peso = request.form.get("peso_declarado", "").strip()
        tolerancia = request.form.get("tolerancia", "").strip() or "5"
        transportista = request.form.get("transportista", "").strip()
        observaciones = request.form.get("observaciones", "").strip()

        existente = next(
            (m for m in db.MANIFIESTOS
             if m["contenedor"] == contenedor
             and m["estado"] == "Pendiente declaración"),
            None,
        )
        if existente:
            flash(f"El contenedor {contenedor} ya tiene un manifiesto pendiente.", "danger")
            return redirect(url_for("naviera_manifiestos"))

        if not contenedor or not tipo or not peso or not transportista:
            flash("Todos los campos obligatorios deben estar completos.", "danger")
            return redirect(url_for("naviera_manifiestos"))

        nuevo = {
            "id": f"MAN-{1000 + len(db.MANIFIESTOS) + 1}",
            "contenedor": contenedor,
            "naviera": entidad,
            "tipo": tipo,
            "peso_declarado": int(peso),
            "tolerancia": float(tolerancia),
            "transportista": transportista,
            "observaciones": observaciones,
            "estado": "Pendiente declaración",
            "canal": None,
        }
        db.MANIFIESTOS.append(nuevo)
        flash(f"Manifiesto {nuevo['id']} creado.", "success")
        return redirect(url_for("naviera_manifiestos"))

    propios = [m for m in db.MANIFIESTOS if m["naviera"] == entidad]
    return render_template(
        "naviera/manifiestos.html",
        manifiestos=propios,
        transportistas=db.TRANSPORTISTAS,
    )


@app.route("/naviera/contenedores")
@login_required("NAVIERA")
def naviera_contenedores():
    entidad = session.get("entidad")
    q = request.args.get("q", "").strip().lower()
    estado_filtro = request.args.get("estado", "").strip()

    propios = [c for c in db.CONTENEDORES if c["naviera"] == entidad]

    if q:
        propios = [c for c in propios if q in c["id"].lower()]
    if estado_filtro:
        propios = [c for c in propios if c["estado"] == estado_filtro]

    return render_template(
        "naviera/contenedores.html",
        contenedores=propios,
        q=q,
        estado_filtro=estado_filtro,
    )


# ---------------------------------------------------------------------------
# ROL: AGENTE
# ---------------------------------------------------------------------------
@app.route("/agente/declaraciones", methods=["GET", "POST"])
@login_required("AGENTE")
def agente_declaraciones():
    if request.method == "POST":
        man_id = request.form.get("man_id")
        accion = request.form.get("accion")
        man = next((m for m in db.MANIFIESTOS if m["id"] == man_id), None)
        if man:
            if accion == "presentar" and man["estado"] == "Pendiente declaración":
                man["estado"] = "Declaración presentada"
                flash(f"Declaración presentada para {man_id}.", "success")
            elif accion == "solicitar_levante" and man["estado"] == "Declaración presentada":
                man["estado"] = "Levante solicitado"
                flash(f"Levante solicitado para {man_id}.", "success")
        return redirect(url_for("agente_declaraciones"))

    pendientes = [m for m in db.MANIFIESTOS if m["estado"] != "Levante otorgado"]
    return render_template("agente/declaraciones.html", manifiestos=pendientes)


@app.route("/agente/seguimiento")
@login_required("AGENTE")
def agente_seguimiento():
    return render_template("agente/seguimiento.html", manifiestos=db.MANIFIESTOS)


# ---------------------------------------------------------------------------
# ROL: AUTORIDAD
# ---------------------------------------------------------------------------
@app.route("/autoridad/levante", methods=["GET", "POST"])
@login_required("AUTORIDAD")
def autoridad_levante():
    if request.method == "POST":
        man_id = request.form.get("man_id")
        accion = request.form.get("accion")
        canal = request.form.get("canal")
        motivo = (request.form.get("motivo") or "").strip()

        man = next((m for m in db.MANIFIESTOS if m["id"] == man_id), None)
        if man:
            if accion == "otorgar" and canal in ("Verde", "Rojo"):
                man["estado"] = "Levante otorgado"
                man["canal"] = canal
                flash(f"Levante otorgado para {man_id} (canal {canal}).", "success")
            elif accion == "retener":
                if not motivo:
                    flash("Debe indicar el motivo de la retención documental.", "danger")
                else:
                    man["estado"] = "Retenido"
                    man["canal"] = None
                    man["motivo_retencion"] = motivo
                    flash(f"Levante retenido para {man_id}.", "warning")
        return redirect(url_for("autoridad_levante"))

    solicitudes = [m for m in db.MANIFIESTOS if m["estado"] == "Levante solicitado"]
    return render_template("autoridad/levante.html", manifiestos=solicitudes)


@app.route("/autoridad/retenciones", methods=["GET", "POST"])
@login_required("AUTORIDAD")
def autoridad_retenciones():
    if request.method == "POST":
        ret_id = request.form.get("ret_id")
        accion = request.form.get("accion")
        motivo = (request.form.get("motivo") or "").strip()
        observacion = (request.form.get("observacion") or "").strip()

        ret = next((r for r in db.RETENCIONES if r["id"] == ret_id), None)

        ok, error = puede_resolver(ret, session.get("rol"), accion)
        if not ok:
            flash(error, "danger")
            return redirect(url_for("autoridad_retenciones"))

        if accion == "Rechazar" and not motivo:
            flash("Debe indicar el motivo al rechazar.", "danger")
            return redirect(url_for("autoridad_retenciones"))

        ret["estado"] = "Resuelta"
        ret["resolucion"] = accion
        ret["motivo"] = motivo if accion == "Rechazar" else None
        ret["observacion"] = observacion or None

        flash(f"Retención {ret_id} resuelta mediante '{accion}'.", "success")
        return redirect(url_for("autoridad_retenciones"))

    aduaneras = [r for r in db.RETENCIONES if codigo_causa(r) in ("RT03", "RT05")]
    return render_template("autoridad/retenciones.html", retenciones=aduaneras)


@app.route("/autoridad/consulta")
@login_required("AUTORIDAD")
def autoridad_consulta():
    return render_template("autoridad/consulta.html", contenedores=db.CONTENEDORES)


if __name__ == "__main__":
    app.run(debug=True, port=5000)