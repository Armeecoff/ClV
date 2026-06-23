import asyncio
import logging
from aiogram import Bot
from database.db import (
    get_users_vpn_expiring, get_users_premium_expiring, auto_disable_expired_vpns,
)

logger = logging.getLogger(__name__)


async def send_notifications(bot: Bot):
    await asyncio.sleep(60)
    tick = 0
    while True:
        try:
            await auto_disable_expired_vpns()
            if tick % 6 == 0:
                vpn_users = await get_users_vpn_expiring(days_ahead=3)
                for item in vpn_users:
                    try:
                        expires = item['expires_at'].strftime('%d.%m.%Y')
                        await bot.send_message(
                            item['telegram_id'],
                            f"⚠️ <b>Ваш VPN скоро истекает!</b>\n\n"
                            f"🔐 <b>{item['vpn_name']}</b>\n"
                            f"📅 Истекает: <b>{expires}</b> (осталось ~3 дня)\n\n"
                            f"Зайдите в магазин, чтобы купить новый конфиг.",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass

                premium_users = await get_users_premium_expiring(hours_ahead=24)
                for item in premium_users:
                    try:
                        expires = item['premium_until'].strftime('%d.%m.%Y %H:%M')
                        await bot.send_message(
                            item['telegram_id'],
                            f"👑 <b>Premium заканчивается!</b>\n\n"
                            f"📅 Истекает: <b>{expires}</b>\n\n"
                            f"Продлите подписку в магазине, чтобы сохранить привилегии.",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f"Notification error: {e}")

        tick += 1
        await asyncio.sleep(10 * 60)
