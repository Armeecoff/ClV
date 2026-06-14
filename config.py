import os
import re
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

_raw_db_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/clickerbot")
_db_url = _raw_db_url.replace("postgresql://", "postgresql+asyncpg://", 1).replace("postgres://", "postgresql+asyncpg://", 1)
_db_url = re.sub(r'\?.*', '', _db_url)
_db_url = re.sub(r'&?sslmode=[^&?]*', '', _db_url)
DATABASE_URL = _db_url

ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
WEBAPP_URL = os.getenv("WEBAPP_URL", "http://localhost:8000")
SECRET_KEY = os.getenv("SECRET_KEY", "changeme_secret_key_123")
PORT = int(os.getenv("PORT", "8000"))
