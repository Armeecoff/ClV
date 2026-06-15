from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import select, delete, func
from datetime import datetime, timedelta
from config import DATABASE_URL, ADMIN_IDS
from database.models import (
    Base, User, ClickUpgrade, UserUpgrade, VPNConfig, VPNPurchase,
    Promotion, UserActivityLog, Achievement, UserAchievement
)

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        migrations = [
            "ALTER TABLE click_upgrades ADD COLUMN IF NOT EXISTS upgrade_type VARCHAR(10) DEFAULT 'click' NOT NULL",
            "ALTER TABLE click_upgrades ADD COLUMN IF NOT EXISTS auto_click_bonus FLOAT DEFAULT 0.0 NOT NULL",
            "ALTER TABLE click_upgrades ADD COLUMN IF NOT EXISTS is_premium_only BOOLEAN DEFAULT FALSE NOT NULL",
            "ALTER TABLE click_upgrades ADD COLUMN IF NOT EXISTS clicks_bonus INTEGER DEFAULT 0 NOT NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS auto_clicks_per_second FLOAT DEFAULT 0.0 NOT NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_premium BOOLEAN DEFAULT FALSE NOT NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS premium_until TIMESTAMP DEFAULT NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS max_balance FLOAT DEFAULT 0.0 NOT NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS autobuy_enabled BOOLEAN DEFAULT FALSE NOT NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS autobuy_keywords TEXT DEFAULT NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS autobuy_min_price FLOAT DEFAULT NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS autobuy_max_price FLOAT DEFAULT NULL",
        ]
        for sql in migrations:
            try:
                await conn.execute(__import__('sqlalchemy').text(sql))
            except Exception:
                pass
    await seed_upgrades()
    await seed_achievements()
    async with engine.begin() as conn:
        await conn.execute(
            __import__('sqlalchemy').text(
                "UPDATE click_upgrades SET auto_click_bonus=7.0, description='+7 кликов/сек автоматически' WHERE name='Авто-кликер IV'"
            )
        )


async def add_user_log(user_id: int, telegram_id: int, action_type: str, description: str):
    async with async_session() as session:
        log = UserActivityLog(
            user_id=user_id, telegram_id=telegram_id,
            action_type=action_type, description=description
        )
        session.add(log)
        await session.commit()


async def get_or_create_user(telegram_id: int, username: str = None, first_name: str = None) -> User:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                is_admin=(telegram_id in ADMIN_IDS)
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            await add_user_log(user.id, telegram_id, "register", "Первый вход в приложение")
        else:
            if username and user.username != username:
                user.username = username
            if first_name and user.first_name != first_name:
                user.first_name = first_name
            await session.commit()
    return user


async def get_user_by_telegram_id(telegram_id: int) -> User | None:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()


async def do_click(telegram_id: int) -> dict:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            return {"balance": 0, "total_clicks": 0}
        bonus = user.clicks_per_click
        if user.is_premium:
            bonus = max(int(bonus * 1.1), bonus + 1)
        user.balance += bonus
        user.total_clicks += 1
        if user.balance > user.max_balance:
            user.max_balance = user.balance
        await session.commit()
        return {
            "balance": user.balance,
            "total_clicks": user.total_clicks,
            "clicks_per_click": user.clicks_per_click,
            "effective_cpc": bonus
        }


async def sync_clicks(telegram_id: int, count: int) -> dict:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            return {"balance": 0, "total_clicks": 0}
        bonus = user.clicks_per_click
        if user.is_premium:
            bonus = max(int(bonus * 1.1), bonus + 1)
        earned = bonus * count
        user.balance += earned
        user.total_clicks += count
        if user.balance > user.max_balance:
            user.max_balance = user.balance
        await session.commit()
        return {"balance": user.balance, "total_clicks": user.total_clicks, "earned": earned}


async def sync_autoclicks(telegram_id: int, amount: float) -> dict:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            return {"balance": 0}
        if user.is_premium:
            amount *= 1.5
        user.balance += amount
        if user.balance > user.max_balance:
            user.max_balance = user.balance
        await session.commit()
        return {"balance": user.balance}


async def get_upgrades() -> list[ClickUpgrade]:
    async with async_session() as session:
        result = await session.execute(select(ClickUpgrade).where(ClickUpgrade.is_active == True))
        return result.scalars().all()


async def get_user_upgrade_ids(telegram_id: int) -> set[int]:
    async with async_session() as session:
        user_res = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_res.scalar_one_or_none()
        if not user:
            return set()
        result = await session.execute(
            select(UserUpgrade.upgrade_id).where(UserUpgrade.user_id == user.id)
        )
        return set(result.scalars().all())


async def buy_upgrade(telegram_id: int, upgrade_id: int) -> dict:
    async with async_session() as session:
        user_res = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_res.scalar_one_or_none()
        if not user:
            return {"ok": False, "error": "Пользователь не найден"}

        upg_res = await session.execute(select(ClickUpgrade).where(ClickUpgrade.id == upgrade_id, ClickUpgrade.is_active == True))
        upgrade = upg_res.scalar_one_or_none()
        if not upgrade:
            return {"ok": False, "error": "Улучшение не найдено"}

        if upgrade.is_premium_only and not user.is_premium:
            return {"ok": False, "error": "Только для Premium пользователей"}

        existing = await session.execute(
            select(UserUpgrade).where(UserUpgrade.user_id == user.id, UserUpgrade.upgrade_id == upgrade.id)
        )
        if existing.scalar_one_or_none():
            return {"ok": False, "error": "Уже куплено"}

        if int(user.balance) < int(upgrade.price):
            return {"ok": False, "error": f"Нужно {int(upgrade.price)} кликов, у вас {int(user.balance)}"}

        user.balance -= upgrade.price
        if upgrade.upgrade_type == "click":
            user.clicks_per_click += upgrade.clicks_bonus
        elif upgrade.upgrade_type == "autoclk":
            user.auto_clicks_per_second += upgrade.auto_click_bonus

        uu = UserUpgrade(user_id=user.id, upgrade_id=upgrade.id)
        session.add(uu)
        await session.commit()
        result2 = {
            "ok": True,
            "new_balance": user.balance,
            "clicks_per_click": user.clicks_per_click,
            "auto_clicks_per_second": user.auto_clicks_per_second
        }
    await add_user_log(
        user.id, user.telegram_id, "upgrade_buy",
        f"Куплено улучшение «{upgrade.name}» за {int(upgrade.price)} кликов"
    )
    return result2


async def buy_premium_subscription(telegram_id: int, period: str) -> dict:
    prices = {
        'month': 150000,
        '3months': 350000,
        '6months': 550000,
        'year': 1000000
    }
    durations = {'month': 30, '3months': 90, '6months': 180, 'year': 365}
    price = prices.get(period)
    days = durations.get(period)
    if not price:
        return {"ok": False, "error": "Неверный период"}

    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            return {"ok": False, "error": "Пользователь не найден"}
        if int(user.balance) < price:
            return {"ok": False, "error": f"Нужно {price} кликов"}

        user.balance -= price
        now = datetime.utcnow()
        if user.is_premium and user.premium_until and user.premium_until > now:
            user.premium_until = user.premium_until + timedelta(days=days)
        else:
            user.premium_until = now + timedelta(days=days)
        user.is_premium = True

        labels = {'month': '1 месяц', '3months': '3 месяца', '6months': '6 месяцев', 'year': '1 год'}
        await session.commit()
        res = {"ok": True, "new_balance": user.balance, "premium_until": user.premium_until.isoformat()}
    await add_user_log(
        user.id, user.telegram_id, "premium_buy",
        f"Куплен Premium на {labels.get(period, period)} за {price} кликов"
    )
    return res


async def seed_upgrades():
    async with async_session() as session:
        result = await session.execute(select(func.count(ClickUpgrade.id)))
        if result.scalar() > 0:
            return
        upgrades = [
            ClickUpgrade(name="Двойной Клик", description="+1 клик за тап", price=100, upgrade_type="click", clicks_bonus=1, icon="👆"),
            ClickUpgrade(name="Тройной Клик", description="+2 клика за тап", price=500, upgrade_type="click", clicks_bonus=2, icon="✌️"),
            ClickUpgrade(name="Мега Клик", description="+5 кликов за тап", price=2000, upgrade_type="click", clicks_bonus=5, icon="💪"),
            ClickUpgrade(name="Гига Клик", description="+10 кликов за тап", price=8000, upgrade_type="click", clicks_bonus=10, icon="🦾"),
            ClickUpgrade(name="Авто-кликер I", description="+0.5 кликов/сек автоматически", price=300, upgrade_type="autoclk", auto_click_bonus=0.5, icon="🤖"),
            ClickUpgrade(name="Авто-кликер II", description="+1 кликов/сек автоматически", price=1200, upgrade_type="autoclk", auto_click_bonus=1.0, icon="⚙️"),
            ClickUpgrade(name="Авто-кликер III", description="+3 кликов/сек автоматически", price=5000, upgrade_type="autoclk", auto_click_bonus=3.0, icon="🔧"),
            ClickUpgrade(name="Авто-кликер IV", description="+7 кликов/сек автоматически", price=15000, upgrade_type="autoclk", auto_click_bonus=7.0, icon="🚀"),
            ClickUpgrade(name="Квантовый Клик", description="+25 кликов за тап", price=50000, upgrade_type="click", clicks_bonus=25, icon="⚡", is_premium_only=True),
            ClickUpgrade(name="Нейро Авто", description="+15 кликов/сек автоматически", price=100000, upgrade_type="autoclk", auto_click_bonus=15.0, icon="🧠", is_premium_only=True),
        ]
        session.add_all(upgrades)
        await session.commit()


async def get_vpn_configs() -> list[VPNConfig]:
    async with async_session() as session:
        now = datetime.utcnow()
        result = await session.execute(
            select(VPNConfig).where(
                VPNConfig.is_active == True,
                VPNConfig.quantity_left > 0,
                (VPNConfig.available_until == None) | (VPNConfig.available_until > now)
            )
        )
        return result.scalars().all()


async def get_all_vpn_configs() -> list[VPNConfig]:
    async with async_session() as session:
        result = await session.execute(select(VPNConfig))
        return result.scalars().all()


async def add_vpn_config(name, description, config_data, price_clicks, duration_days, quantity, available_until, created_by) -> VPNConfig:
    async with async_session() as session:
        vpn = VPNConfig(
            name=name, description=description, config_data=config_data,
            price_clicks=price_clicks, duration_days=duration_days,
            quantity=quantity, quantity_left=quantity,
            available_until=available_until, created_by=created_by
        )
        session.add(vpn)
        await session.commit()
        await session.refresh(vpn)
    await process_autobuy_for_vpn(vpn.id)
    return vpn


async def edit_vpn_config(vpn_id: int, **kwargs) -> dict:
    async with async_session() as session:
        result = await session.execute(select(VPNConfig).where(VPNConfig.id == vpn_id))
        vpn = result.scalar_one_or_none()
        if not vpn:
            return {"ok": False, "error": "Не найден"}
        for k, v in kwargs.items():
            if hasattr(vpn, k) and v is not None:
                setattr(vpn, k, v)
        await session.commit()
        return {"ok": True}


async def delete_vpn_config(vpn_id: int) -> dict:
    async with async_session() as session:
        result = await session.execute(select(VPNConfig).where(VPNConfig.id == vpn_id))
        vpn = result.scalar_one_or_none()
        if not vpn:
            return {"ok": False, "error": "Не найден"}
        await session.delete(vpn)
        await session.commit()
        return {"ok": True}


async def buy_vpn(telegram_id: int, vpn_id: int) -> dict:
    async with async_session() as session:
        user_res = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_res.scalar_one_or_none()
        if not user:
            return {"ok": False, "error": "Пользователь не найден"}

        now = datetime.utcnow()
        vpn_res = await session.execute(
            select(VPNConfig).where(
                VPNConfig.id == vpn_id, VPNConfig.is_active == True,
                VPNConfig.quantity_left > 0,
                (VPNConfig.available_until == None) | (VPNConfig.available_until > now)
            )
        )
        vpn = vpn_res.scalar_one_or_none()
        if not vpn:
            return {"ok": False, "error": "VPN конфиг не найден или недоступен"}
        effective_price = vpn.price_clicks * (0.9 if user.is_premium else 1.0)
        if user.balance < effective_price:
            return {"ok": False, "error": f"Нужно {int(effective_price)} кликов"}

        user.balance -= effective_price
        vpn.quantity_left -= 1
        expires_at = now + timedelta(days=vpn.duration_days)
        purchase = VPNPurchase(user_id=user.id, vpn_config_id=vpn.id, price_paid=vpn.price_clicks, expires_at=expires_at)
        session.add(purchase)
        await session.commit()
        res = {"ok": True, "config_data": vpn.config_data, "expires_at": expires_at.isoformat(), "new_balance": user.balance}
    await add_user_log(
        user.id, user.telegram_id, "vpn_buy",
        f"Куплен VPN «{vpn.name}» за {int(effective_price)} кликов, истекает {expires_at.strftime('%d.%m.%Y')}"
    )
    return res


async def get_user_vpn_purchases(telegram_id: int) -> list:
    async with async_session() as session:
        user_res = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_res.scalar_one_or_none()
        if not user:
            return []
        result = await session.execute(select(VPNPurchase).where(VPNPurchase.user_id == user.id))
        purchases = result.scalars().all()
        out = []
        for p in purchases:
            vpn_res = await session.execute(select(VPNConfig).where(VPNConfig.id == p.vpn_config_id))
            vpn = vpn_res.scalar_one_or_none()
            out.append({
                "id": p.id, "vpn_name": vpn.name if vpn else "Удалён",
                "price_paid": p.price_paid, "purchased_at": p.purchased_at.isoformat(),
                "expires_at": p.expires_at.isoformat() if p.expires_at else None,
                "config_data": vpn.config_data if vpn else ""
            })
        return out


async def adjust_balance(telegram_id: int, amount: float) -> dict:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            return {"ok": False, "error": "Пользователь не найден"}
        user.balance = max(0, user.balance + amount)
        if user.balance > user.max_balance:
            user.max_balance = user.balance
        await session.commit()
        uid, unm = user.id, user.telegram_id
    action = "balance_add" if amount >= 0 else "balance_remove"
    desc = f"{'Начислено' if amount >= 0 else 'Снято'} {abs(int(amount))} кликов администратором"
    await add_user_log(uid, unm, action, desc)
    return {"ok": True, "new_balance": user.balance}


async def toggle_vpn_active(vpn_id: int) -> dict:
    async with async_session() as session:
        result = await session.execute(select(VPNConfig).where(VPNConfig.id == vpn_id))
        vpn = result.scalar_one_or_none()
        if not vpn:
            return {"ok": False, "error": "Не найден"}
        vpn.is_active = not vpn.is_active
        await session.commit()
        return {"ok": True, "is_active": vpn.is_active}


async def get_all_users() -> list[User]:
    async with async_session() as session:
        result = await session.execute(select(User))
        return result.scalars().all()


async def set_admin(telegram_id: int, is_admin: bool) -> dict:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            return {"ok": False, "error": "Пользователь не найден"}
        user.is_admin = is_admin
        await session.commit()
        return {"ok": True}


async def set_premium(telegram_id: int, is_premium: bool) -> dict:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            return {"ok": False, "error": "Пользователь не найден"}
        user.is_premium = is_premium
        if not is_premium:
            user.premium_until = None
        await session.commit()
        return {"ok": True}


async def admin_add_upgrade(name, description, price, upgrade_type, clicks_bonus, auto_click_bonus, icon, is_premium_only) -> ClickUpgrade:
    async with async_session() as session:
        upg = ClickUpgrade(
            name=name, description=description, price=price,
            upgrade_type=upgrade_type, clicks_bonus=clicks_bonus,
            auto_click_bonus=auto_click_bonus, icon=icon,
            is_premium_only=is_premium_only
        )
        session.add(upg)
        await session.commit()
        await session.refresh(upg)
        return upg


async def admin_edit_upgrade(upgrade_id: int, **kwargs) -> dict:
    async with async_session() as session:
        result = await session.execute(select(ClickUpgrade).where(ClickUpgrade.id == upgrade_id))
        upg = result.scalar_one_or_none()
        if not upg:
            return {"ok": False, "error": "Не найдено"}
        for k, v in kwargs.items():
            if hasattr(upg, k) and v is not None:
                setattr(upg, k, v)
        await session.commit()
        return {"ok": True}


async def delete_user(telegram_id: int) -> dict:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            return {"ok": False, "error": "Пользователь не найден"}
        await session.delete(user)
        await session.commit()
        return {"ok": True}


async def get_all_click_upgrades() -> list[ClickUpgrade]:
    async with async_session() as session:
        result = await session.execute(select(ClickUpgrade))
        return result.scalars().all()


async def get_all_user_upgrades() -> list[UserUpgrade]:
    async with async_session() as session:
        result = await session.execute(select(UserUpgrade))
        return result.scalars().all()


async def get_all_vpn_purchases() -> list[VPNPurchase]:
    async with async_session() as session:
        result = await session.execute(select(VPNPurchase))
        return result.scalars().all()


async def admin_delete_upgrade(upgrade_id: int) -> dict:
    async with async_session() as session:
        result = await session.execute(select(ClickUpgrade).where(ClickUpgrade.id == upgrade_id))
        upg = result.scalar_one_or_none()
        if not upg:
            return {"ok": False, "error": "Не найдено"}
        await session.delete(upg)
        await session.commit()
        return {"ok": True}


async def get_active_promotions() -> list:
    async with async_session() as session:
        now = datetime.utcnow()
        result = await session.execute(
            select(Promotion).where(
                Promotion.is_active == True,
                Promotion.end_at > now
            ).order_by(Promotion.created_at.desc())
        )
        return result.scalars().all()


async def get_all_promotions() -> list:
    async with async_session() as session:
        result = await session.execute(select(Promotion).order_by(Promotion.created_at.desc()))
        return result.scalars().all()


async def add_promotion(title: str, description: str, icon: str, promo_type: str, value: float, end_at: datetime) -> Promotion:
    async with async_session() as session:
        promo = Promotion(title=title, description=description, icon=icon, promo_type=promo_type, value=value, end_at=end_at)
        session.add(promo)
        await session.commit()
        await session.refresh(promo)
        return promo


async def delete_promotion(promo_id: int) -> dict:
    async with async_session() as session:
        result = await session.execute(select(Promotion).where(Promotion.id == promo_id))
        promo = result.scalar_one_or_none()
        if not promo:
            return {"ok": False, "error": "Не найдена"}
        await session.delete(promo)
        await session.commit()
        return {"ok": True}


async def toggle_promotion(promo_id: int) -> dict:
    async with async_session() as session:
        result = await session.execute(select(Promotion).where(Promotion.id == promo_id))
        promo = result.scalar_one_or_none()
        if not promo:
            return {"ok": False}
        promo.is_active = not promo.is_active
        await session.commit()
        return {"ok": True, "is_active": promo.is_active}


async def get_click_multiplier() -> float:
    promos = await get_active_promotions()
    mults = [p.value for p in promos if p.promo_type == "click_mult"]
    return max(mults) if mults else 1.0


async def get_vpn_promo_discount() -> float:
    promos = await get_active_promotions()
    discs = [p.value for p in promos if p.promo_type == "vpn_disc"]
    return max(discs) if discs else 0.0


async def get_all_logs(limit: int = 200) -> list:
    async with async_session() as session:
        result = await session.execute(
            select(UserActivityLog).order_by(UserActivityLog.created_at.desc()).limit(limit)
        )
        return result.scalars().all()


async def get_user_logs(telegram_id: int, limit: int = 50) -> list:
    async with async_session() as session:
        result = await session.execute(
            select(UserActivityLog)
            .where(UserActivityLog.telegram_id == telegram_id)
            .order_by(UserActivityLog.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()


# ── Achievements ──────────────────────────────────────────────

async def seed_achievements():
    async with async_session() as session:
        result = await session.execute(select(func.count(Achievement.id)))
        if result.scalar() > 0:
            return
        items = [
            Achievement(name="Первый Клик", description="Заработайте 1 000 кликов", icon="🖱", condition_type="total_clicks_gte", condition_value="1000"),
            Achievement(name="Анонимус", description="Купите первый VPN-конфиг", icon="🔐", condition_type="vpn_buy_count_gte", condition_value="1"),
            Achievement(name="Хамелеон", description="Купите радужный скин кликера", icon="🌈", condition_type="own_skin", condition_value="rainbow"),
            Achievement(name="Аристократ", description="Купите Premium подписку", icon="👑", condition_type="is_premium", condition_value="0"),
            Achievement(name="Инженер Мощи", description="Купите все обычные улучшения", icon="⚡", condition_type="all_non_premium_upgrades", condition_value="0"),
            Achievement(name="Биткоин-Миллионер", description="Соберите 1 000 000 кликов на балансе", icon="💰", condition_type="balance_max_gte", condition_value="1000000"),
            Achievement(name="Маг Эффектов", description="Купите все 8 эффектов интерфейса", icon="✨", condition_type="all_effects_owned", condition_value="8"),
            Achievement(name="Охотник за Акциями", description="Откройте магазин во время активной акции", icon="🎉", condition_type="promo_exists", condition_value="0"),
            Achievement(name="Путешественник Вселенных", description="Попробуйте все 15 тем оформления", icon="🎨", condition_type="all_themes_tried", condition_value="15"),
            Achievement(name="Накопитель", description="Соберите 100 000 кликов на балансе", icon="💎", condition_type="balance_max_gte", condition_value="100000"),
        ]
        session.add_all(items)
        await session.commit()


async def get_achievements(telegram_id: int) -> list:
    async with async_session() as session:
        user_res = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_res.scalar_one_or_none()
        if not user:
            return []

        ach_res = await session.execute(
            select(Achievement).where(Achievement.is_active == True).order_by(Achievement.id)
        )
        achievements = ach_res.scalars().all()

        ua_res = await session.execute(
            select(UserAchievement).where(UserAchievement.user_id == user.id)
        )
        user_ach = {ua.achievement_id: ua for ua in ua_res.scalars().all()}

        return [
            {
                "id": a.id, "name": a.name, "description": a.description, "icon": a.icon,
                "condition_type": a.condition_type, "condition_value": a.condition_value,
                "unlocked": a.id in user_ach,
                "unlocked_at": user_ach[a.id].unlocked_at.isoformat() if a.id in user_ach else None
            }
            for a in achievements
        ]


async def check_and_unlock_achievements(telegram_id: int, client_state: dict) -> list:
    async with async_session() as session:
        user_res = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_res.scalar_one_or_none()
        if not user:
            return []

        ach_res = await session.execute(
            select(Achievement).where(Achievement.is_active == True)
        )
        achievements = ach_res.scalars().all()

        ua_res = await session.execute(
            select(UserAchievement.achievement_id).where(UserAchievement.user_id == user.id)
        )
        already_unlocked = set(ua_res.scalars().all())

        vpn_count_res = await session.execute(
            select(func.count(VPNPurchase.id)).where(VPNPurchase.user_id == user.id)
        )
        vpn_count = vpn_count_res.scalar() or 0

        total_np_res = await session.execute(
            select(func.count(ClickUpgrade.id)).where(
                ClickUpgrade.is_active == True, ClickUpgrade.is_premium_only == False
            )
        )
        total_non_prem = total_np_res.scalar() or 0

        owned_np_res = await session.execute(
            select(func.count(UserUpgrade.id))
            .join(ClickUpgrade, UserUpgrade.upgrade_id == ClickUpgrade.id)
            .where(UserUpgrade.user_id == user.id, ClickUpgrade.is_premium_only == False)
        )
        owned_non_prem = owned_np_res.scalar() or 0

        now = datetime.utcnow()
        promo_res = await session.execute(
            select(func.count(Promotion.id)).where(
                Promotion.is_active == True, Promotion.end_at > now
            )
        )
        promo_active = (promo_res.scalar() or 0) > 0

        newly_unlocked = []
        for ach in achievements:
            if ach.id in already_unlocked:
                continue
            ct = ach.condition_type
            try:
                cv = float(ach.condition_value)
            except (ValueError, TypeError):
                cv = 0
            unlocked = False

            if ct == "total_clicks_gte":
                unlocked = user.total_clicks >= cv
            elif ct == "vpn_buy_count_gte":
                unlocked = vpn_count >= cv
            elif ct == "is_premium":
                unlocked = user.is_premium
            elif ct == "all_non_premium_upgrades":
                unlocked = total_non_prem > 0 and owned_non_prem >= total_non_prem
            elif ct == "balance_max_gte":
                unlocked = user.max_balance >= cv
            elif ct == "own_skin":
                unlocked = ach.condition_value in client_state.get("owned_skins", [])
            elif ct == "all_effects_owned":
                unlocked = client_state.get("owned_items_count", 0) >= int(cv)
            elif ct == "promo_exists":
                unlocked = promo_active
            elif ct == "all_themes_tried":
                unlocked = client_state.get("themes_tried_count", 0) >= int(cv)

            if unlocked:
                ua = UserAchievement(user_id=user.id, achievement_id=ach.id)
                session.add(ua)
                newly_unlocked.append({"id": ach.id, "name": ach.name, "icon": ach.icon})

        if newly_unlocked:
            await session.commit()

        return newly_unlocked


async def admin_get_achievements() -> list:
    async with async_session() as session:
        result = await session.execute(select(Achievement).order_by(Achievement.id))
        return [
            {
                "id": a.id, "name": a.name, "description": a.description, "icon": a.icon,
                "condition_type": a.condition_type, "condition_value": a.condition_value,
                "is_active": a.is_active, "created_at": a.created_at.isoformat()
            }
            for a in result.scalars().all()
        ]


async def admin_add_achievement(name: str, description: str, icon: str, condition_type: str, condition_value: str) -> dict:
    async with async_session() as session:
        ach = Achievement(
            name=name, description=description, icon=icon,
            condition_type=condition_type, condition_value=condition_value
        )
        session.add(ach)
        await session.commit()
        await session.refresh(ach)
        return {"ok": True, "id": ach.id}


async def admin_edit_achievement(ach_id: int, **kwargs) -> dict:
    async with async_session() as session:
        result = await session.execute(select(Achievement).where(Achievement.id == ach_id))
        ach = result.scalar_one_or_none()
        if not ach:
            return {"ok": False, "error": "Не найдено"}
        for k, v in kwargs.items():
            if hasattr(ach, k) and v is not None:
                setattr(ach, k, v)
        await session.commit()
        return {"ok": True}


async def admin_delete_achievement(ach_id: int) -> dict:
    async with async_session() as session:
        result = await session.execute(select(Achievement).where(Achievement.id == ach_id))
        ach = result.scalar_one_or_none()
        if not ach:
            return {"ok": False, "error": "Не найдено"}
        await session.delete(ach)
        await session.commit()
        return {"ok": True}


# ── Premium Auto-Buy VPN ──────────────────────────────────────

async def get_autobuy_settings(telegram_id: int) -> dict:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            return {}
        return {
            "enabled": user.autobuy_enabled,
            "keywords": user.autobuy_keywords or "",
            "min_price": user.autobuy_min_price,
            "max_price": user.autobuy_max_price
        }


async def save_autobuy_settings(telegram_id: int, enabled: bool, keywords: str, min_price, max_price) -> dict:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            return {"ok": False, "error": "Пользователь не найден"}
        if not user.is_premium:
            return {"ok": False, "error": "Требуется Premium подписка"}
        user.autobuy_enabled = enabled
        user.autobuy_keywords = keywords or None
        user.autobuy_min_price = float(min_price) if min_price is not None else None
        user.autobuy_max_price = float(max_price) if max_price is not None else None
        await session.commit()
        return {"ok": True}


async def process_autobuy_for_vpn(vpn_id: int):
    async with async_session() as session:
        vpn_res = await session.execute(select(VPNConfig).where(VPNConfig.id == vpn_id))
        vpn = vpn_res.scalar_one_or_none()
        if not vpn or not vpn.is_active or vpn.quantity_left <= 0:
            return

        users_res = await session.execute(
            select(User).where(User.is_premium == True, User.autobuy_enabled == True)
        )
        users = users_res.scalars().all()

    for user in users:
        if user.autobuy_min_price is not None and vpn.price_clicks < user.autobuy_min_price:
            continue
        if user.autobuy_max_price is not None and vpn.price_clicks > user.autobuy_max_price:
            continue
        if user.autobuy_keywords:
            keywords = [k.strip().lower() for k in user.autobuy_keywords.split(',') if k.strip()]
            if keywords and not any(k in vpn.name.lower() for k in keywords):
                continue
        await buy_vpn(user.telegram_id, vpn_id)


# ── Extended History ──────────────────────────────────────────

async def get_user_extended_history(telegram_id: int, limit: int = 100) -> list:
    async with async_session() as session:
        result = await session.execute(
            select(UserActivityLog)
            .where(UserActivityLog.telegram_id == telegram_id)
            .order_by(UserActivityLog.created_at.desc())
            .limit(limit)
        )
        return [
            {
                "id": log.id,
                "action_type": log.action_type,
                "description": log.description,
                "created_at": log.created_at.isoformat()
            }
            for log in result.scalars().all()
        ]


# ── Notification helpers ──────────────────────────────────────

async def get_users_vpn_expiring(days_ahead: int = 3) -> list:
    now = datetime.utcnow()
    window_start = now + timedelta(days=days_ahead - 0.5)
    window_end = now + timedelta(days=days_ahead + 0.5)
    async with async_session() as session:
        result = await session.execute(
            select(VPNPurchase, User, VPNConfig)
            .join(User, VPNPurchase.user_id == User.id)
            .join(VPNConfig, VPNPurchase.vpn_config_id == VPNConfig.id)
            .where(
                VPNPurchase.expires_at >= window_start,
                VPNPurchase.expires_at <= window_end
            )
        )
        rows = result.all()
        return [
            {
                "telegram_id": user.telegram_id,
                "first_name": user.first_name or user.username or "пользователь",
                "vpn_name": vpn.name,
                "expires_at": purchase.expires_at
            }
            for purchase, user, vpn in rows
        ]


async def get_users_premium_expiring(hours_ahead: int = 24) -> list:
    now = datetime.utcnow()
    window_end = now + timedelta(hours=hours_ahead)
    async with async_session() as session:
        result = await session.execute(
            select(User).where(
                User.is_premium == True,
                User.premium_until >= now,
                User.premium_until <= window_end
            )
        )
        users = result.scalars().all()
        return [
            {
                "telegram_id": u.telegram_id,
                "first_name": u.first_name or u.username or "пользователь",
                "premium_until": u.premium_until
            }
            for u in users
        ]
