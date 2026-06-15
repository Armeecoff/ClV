import asyncio
import logging
from aiogram import Bot
from database.db import (
    get_users_vpn_expiring, get_users_premium_expiring,
    get_unsent_vpn_configs, get_users_with_vpn_notify, mark_vpn_notified
)

logger = logging.getLogger(__name__)


async def send_new_vpn_notifications(bot: Bot):
    try:
        new_configs = await get_unsent_vpn_configs()
        if not new_configs:
            return
        notify_users = await get_users_with_vpn_notify()
        if not notify_users:
            for cfg in new_configs:
                await mark_vpn_notified(cfg.id)
            return
        for cfg in new_configs:
            prem_badge = " ⭐ только Premium" if cfg.is_premium_only else ""
            msg = (
                f"🔐 <b>Новый VPN конфиг!</b>{prem_badge}\n\n"
                f"📛 <b>{cfg.name}</b>\n"
                f"💰 Цена: <b>{int(cfg.price_clicks)}</b> кликов\n"
                f"📅 Срок: <b>{cfg.duration_days}</b> дней\n"
                f"📦 Осталось: <b>{cfg.quantity_left}</b> шт.\n\n"
                f"Откройте приложение и купите!"
            )
            for user in notify_users:
                try:
                    await bot.send_message(user.telegram_id, msg, parse_mode="HTML")
                    await asyncio.sleep(0.05)
                except Exception:
                    pass
            await mark_vpn_notified(cfg.id)
    except Exception as e:
        logger.error(f"New VPN notify error: {e}")


async def send_notifications(bot: Bot):
    await asyncio.sleep(60)
    tick = 0
    while True:
        try:
            await send_new_vpn_notifications(bot)

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
