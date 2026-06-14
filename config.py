import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/clickerbot")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
WEBAPP_URL = os.getenv("WEBAPP_URL", "http://localhost:8000")
SECRET_KEY = os.getenv("SECRET_KEY", "changeme_secret_key_123")
PORT = int(os.getenv("PORT", "8000"))
