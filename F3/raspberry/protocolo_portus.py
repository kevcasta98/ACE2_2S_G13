# ============================================================
# PORTUS - Protocolo Serial
# Raspberry Pi <-> Arduino Mega
# ============================================================

PREFIJO = "$PORTUS"
SEPARADOR = "|"


def crc16_ccitt(texto: str) -> int:
    """
    CRC-16/CCITT-FALSE
    Polinomio: 0x1021
    Valor inicial: 0xFFFF
    """
    crc = 0xFFFF

    for byte in texto.encode("utf-8"):
        crc ^= byte << 8

        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF

    return crc


def construir_trama(
    origen: str,
    secuencia: int,
    tipo: str,
    nombre: str,
    datos: str = ""
) -> str:
    cuerpo = (
        f"PORTUS|"
        f"{origen}|"
        f"{secuencia}|"
        f"{tipo}|"
        f"{nombre}|"
        f"{datos}"
    )

    crc = crc16_ccitt(cuerpo)
    return f"${cuerpo}|{crc:04X}\n"


def analizar_trama(trama: str):
    trama = trama.strip()

    if not trama.startswith("$PORTUS|"):
        return {
            "valida": False,
            "error": "PREFIJO_INVALIDO"
        }

    partes = trama[1:].split("|")

    if len(partes) != 7:
        return {
            "valida": False,
            "error": "FORMATO_INVALIDO"
        }

    protocolo = partes[0]
    origen = partes[1]
    secuencia_texto = partes[2]
    tipo = partes[3]
    nombre = partes[4]
    datos = partes[5]
    crc_recibido = partes[6]

    try:
        secuencia = int(secuencia_texto)
    except ValueError:
        return {
            "valida": False,
            "error": "SECUENCIA_INVALIDA"
        }

    cuerpo = (
        f"{protocolo}|"
        f"{origen}|"
        f"{secuencia}|"
        f"{tipo}|"
        f"{nombre}|"
        f"{datos}"
    )

    crc_calculado = crc16_ccitt(cuerpo)

    try:
        crc_recibido_num = int(crc_recibido, 16)
    except ValueError:
        return {
            "valida": False,
            "error": "CRC_INVALIDO"
        }

    if crc_calculado != crc_recibido_num:
        return {
            "valida": False,
            "error": "CRC_NO_COINCIDE",
            "crc_calculado": f"{crc_calculado:04X}",
            "crc_recibido": crc_recibido
        }

    return {
        "valida": True,
        "origen": origen,
        "secuencia": secuencia,
        "tipo": tipo,
        "nombre": nombre,
        "datos": datos,
        "crc": crc_recibido
    }
