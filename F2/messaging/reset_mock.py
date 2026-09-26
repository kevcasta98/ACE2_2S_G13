"""
Borra la base simulada para que el siguiente arranque regenere:
- códigos de vinculación ABC123 y XYZ789
- contenedores
- franjas
- turno de prueba

Úsalo solo durante desarrollo.
"""

from config import DATA_FILE

if DATA_FILE.exists():
    DATA_FILE.unlink()
    print("Base simulada eliminada.")
else:
    print("No había base simulada.")

print("Ejecuta python bot.py para regenerarla.")
