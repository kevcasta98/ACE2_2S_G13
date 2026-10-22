#!/usr/bin/env python3
# Simulador local del canal de mensajería PORTUS.
# Sirve para probar la lógica de comandos antes de conectar Telegram.

import sys

from db_portus import inicializar_bd
from mensajeria_portus import procesar_texto


def main():
    inicializar_bd()
    cuenta = sys.argv[1] if len(sys.argv) > 1 else "SIMULADOR-01"
    print("PORTUS - Simulador del transportista")
    print(f"Cuenta simulada: {cuenta}")
    print("Escribe comandos como /vincular CODIGO, /cita, /miscitas.")
    print("Escribe salir para terminar.\n")

    while True:
        try:
            texto = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if texto.lower() in ("salir", "exit", "quit"):
            break
        if not texto:
            continue
        try:
            print(procesar_texto(cuenta, texto))
        except Exception as exc:
            print(f"ERROR: {exc}")
        print()


if __name__ == "__main__":
    main()
