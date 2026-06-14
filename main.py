import asyncio
import uvicorn
import logging
from database.db import init_db
from bot.main import start_bot
from webapp.app import app
from config import PORT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    logger.info("Initializing database...")
    await init_db()
    logger.info("Database ready.")

    config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=PORT,
        log_level="info",
        loop="asyncio"
    )
    server = uvicorn.Server(config)

    logger.info(f"Starting web server on port {PORT}...")
    logger.info("Starting Telegram bot...")

    await asyncio.gather(
        server.serve(),
        start_bot()
    )


if __name__ == "__main__":
    asyncio.run(main())
