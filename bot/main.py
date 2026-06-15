from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from bot.handlers import start, admin
from bot.handlers.notifications import send_notifications
from config import BOT_TOKEN

import asyncio


async def start_bot():
    if not BOT_TOKEN:
        return
    try:
        bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    except Exception:
        return
    dp = Dispatcher()
    dp.include_router(start.router)
    dp.include_router(admin.router)
    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.gather(
        dp.start_polling(bot, allowed_updates=["message", "callback_query"]),
        send_notifications(bot)
    )
