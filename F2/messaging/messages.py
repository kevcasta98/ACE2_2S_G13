COMANDOS = [
    ("/inicio", "Presenta PORTUS y lista los comandos disponibles."),
    ("/vincular CODIGO", "Vincula tu cuenta de mensajería con tu transportista."),
    ("/cita", "Inicia la solicitud de una cita."),
    ("/miscitas", "Lista tus citas vigentes."),
    ("/estado CONTENEDOR", "Consulta el estado de uno de tus contenedores."),
    ("/misturnos", "Lista tus operaciones en curso."),
    ("/ayuda", "Muestra nuevamente esta lista de comandos."),
]


def lista_comandos() -> str:
    return "\n".join(f"{cmd} — {desc}" for cmd, desc in COMANDOS)


MENSAJE_VINCULACION_REQUERIDA = (
    "🔐 Tu cuenta de mensajería aún no está vinculada a PORTUS.\n\n"
    "Usa:\n/vincular CODIGO\n\n"
    "El código debe ser generado por el operador de terminal, "
    "solo puede utilizarse una vez y vence después de 60 minutos."
)
