# -*- coding: utf-8 -*-
"""
PORTUS - Fase 2 - Interfaces web (Compañero 2)
Aplicación de referencia con datos ficticios (mock_data.py).

Cómo correrlo:
    pip install flask
    python app.py
Luego abrir http://localhost:5000

Usuarios de prueba (ver mock_data.USUARIOS):
    operador1 / 1234   -> TERMINAL
    naviera1  / 1234   -> NAVIERA (NAVIERA1)
    naviera2  / 1234   -> NAVIERA (NAVIERA2)
    agente1   / 1234   -> AGENTE
    autoridad1/ 1234   -> AUTORIDAD

IMPORTANTE: este archivo NO reemplaza el backend real. Cuando el compañero 1
tenga listos los endpoints, las funciones de este archivo marcadas con
"TODO: conectar backend real" deben reemplazar el acceso a mock_data por
llamadas HTTP/DB reales. La estructura de rutas y roles ya queda lista.
"""
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash

import mock_data as db

app = Flask(__name__)
app.secret_key = "clave-de-desarrollo-portus-fase2"  # cambiar en producción


# ---------------------------------------------------------------------------
# Utilidades de sesión / control de permisos (server-side, como exige el doc)
# ---------------------------------------------------------------------------
def login_required(*roles_permitidos):
    """Decorador: exige sesión iniciada y, opcionalmente, un rol específico.
    El documento exige que el control de permisos se aplique en el servidor
    y no solo ocultando botones en la interfaz."""
    def decorador(f):
        @wraps(f)
        def envoltura(*args, **kwargs):
            if "usuario" not in session:
                flash("Debes iniciar sesión.", "warning")
                return redirect(url_for("login"))
            if roles_permitidos and session.get("rol") not in roles_permitidos:
                flash("No tienes permiso para realizar esta acción (rol no autorizado).", "danger")
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
    }


# ---------------------------------------------------------------------------
# LOGIN / LOGOUT
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
# ROL: TERMINAL (8 pestañas obligatorias)
# ---------------------------------------------------------------------------
@app.route("/terminal/operacion")
@login_required("TERMINAL")
def terminal_operacion():
    return render_template("terminal/operacion.html", turnos=db.TURNOS, grua=db.GRUA,
                            retenciones=[r for r in db.RETENCIONES if r["estado"] == "Abierta"])


@app.route("/terminal/turnos")
@login_required("TERMINAL")
def terminal_turnos():
    filtro_estado = request.args.get("estado", "")
    turnos = db.TURNOS
    if filtro_estado:
        turnos = [t for t in turnos if t["estado"] == filtro_estado]
    return render_template("terminal/turnos.html", turnos=turnos, filtro_estado=filtro_estado)


@app.route("/terminal/turnos/<turno_id>")
@login_required("TERMINAL")
def terminal_turno_detalle(turno_id):
    turno = next((t for t in db.TURNOS if t["id"] == turno_id), None)
    # Línea de tiempo ficticia; en el sistema real viene de la BD de eventos
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
        ret = next((r for r in db.RETENCIONES if r["id"] == ret_id), None)
        if ret:
            # TODO: conectar backend real (validar rol facultado en servidor)
            ret["estado"] = "Resuelta"
            ret["resolucion"] = accion
            flash(f"Retención {ret_id} resuelta mediante '{accion}' (simulado).", "success")
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


@app.route("/terminal/citas")
@login_required("TERMINAL")
def terminal_citas():
    return render_template("terminal/citas.html", agenda=db.CITAS)


@app.route("/terminal/reportes", methods=["GET", "POST"])
@login_required("TERMINAL")
def terminal_reportes():
    metricas = None
    if request.method == "POST":
        # TODO: conectar backend real: calcular métricas para el rango pedido
        metricas = db.METRICAS_MOCK
    return render_template("terminal/reportes.html", metricas=metricas)


# ---------------------------------------------------------------------------
# ROL: NAVIERA
# ---------------------------------------------------------------------------
@app.route("/naviera/manifiestos", methods=["GET", "POST"])
@login_required("NAVIERA")
def naviera_manifiestos():
    entidad = session.get("entidad")
    if request.method == "POST":
        nuevo = {
            "id": f"MAN-{1000 + len(db.MANIFIESTOS) + 1}",
            "contenedor": request.form.get("contenedor"),
            "naviera": entidad,
            "tipo": request.form.get("tipo"),
            "peso_declarado": int(request.form.get("peso_declarado") or 0),
            "tolerancia": float(request.form.get("tolerancia") or 5),
            "transportista": request.form.get("transportista"),
            "observaciones": request.form.get("observaciones", ""),
            "estado": "Pendiente declaración",
            "canal": None,
        }
        db.MANIFIESTOS.append(nuevo)
        flash("Manifiesto creado (simulado).", "success")
        return redirect(url_for("naviera_manifiestos"))
    propios = [m for m in db.MANIFIESTOS if m["naviera"] == entidad]
    return render_template("naviera/manifiestos.html", manifiestos=propios)


@app.route("/naviera/contenedores")
@login_required("NAVIERA")
def naviera_contenedores():
    entidad = session.get("entidad")
    propios = [c for c in db.CONTENEDORES if c["naviera"] == entidad]
    return render_template("naviera/contenedores.html", contenedores=propios)


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
            if accion == "presentar":
                man["estado"] = "Declaración presentada"
            elif accion == "solicitar_levante" and man["estado"] == "Declaración presentada":
                man["estado"] = "Levante solicitado"
        return redirect(url_for("agente_declaraciones"))
    pendientes = [m for m in db.MANIFIESTOS if m["estado"] not in ("Levante otorgado",)]
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
        man = next((m for m in db.MANIFIESTOS if m["id"] == man_id), None)
        if man:
            if accion == "otorgar" and canal in ("Verde", "Rojo"):
                man["estado"] = "Levante otorgado"
                man["canal"] = canal
                flash(f"Levante otorgado para {man_id} con canal {canal}.", "success")
            elif accion == "retener":
                man["estado"] = "Retenido"
                man["canal"] = None
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
        ret = next((r for r in db.RETENCIONES if r["id"] == ret_id), None)
        if ret:
            ret["estado"] = "Resuelta"
            ret["resolucion"] = accion
        return redirect(url_for("autoridad_retenciones"))
    # Solo causas de origen aduanero (RT03, RT05)
    aduaneras = [r for r in db.RETENCIONES if r["causa"].startswith(("RT03", "RT05"))]
    return render_template("autoridad/retenciones.html", retenciones=aduaneras)


@app.route("/autoridad/consulta")
@login_required("AUTORIDAD")
def autoridad_consulta():
    return render_template("autoridad/consulta.html", contenedores=db.CONTENEDORES)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
