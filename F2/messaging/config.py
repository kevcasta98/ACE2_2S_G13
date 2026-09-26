import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
PORTUS_TIMEZONE = os.getenv("PORTUS_TIMEZONE", "America/Guatemala").strip()

data_file = os.getenv("PORTUS_DATA_FILE", "data/mock_db.json")
DATA_FILE = (BASE_DIR / data_file).resolve()

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError(
        "Falta TELEGRAM_BOT_TOKEN. Copia .env.example a .env y agrega el token."
    )
