from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import select, delete, func
from datetime import datetime, timedelta, timezone
import random
from config import DATABASE_URL, ADMIN_IDS

MSK = timezone(timedelta(hours=3))

def now_msk() -> datetime:
    return datetime.now(MSK).replace(tzinfo=None)

from database.models import (
    Base, User, ClickUpgrade, UserUpgrade, VPNConfig, VPNPurchase,
    Promotion, UserActivityLog, Achievement, UserAchievement, AppSettings,
    Avatar, UserAvatar, PromoCode, PromoCodeActivation, ApiKey
)
import secrets

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
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS autobuy_max_count INTEGER DEFAULT NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS login_days_count INTEGER DEFAULT 0 NOT NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS login_streak INTEGER DEFAULT 0 NOT NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_date TIMESTAMP DEFAULT NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_bio VARCHAR(200) DEFAULT NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_badge VARCHAR(20) DEFAULT NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS vpn_notify_enabled BOOLEAN DEFAULT FALSE NOT NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS offline_income_enabled BOOLEAN DEFAULT FALSE NOT NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_offline_check TIMESTAMP DEFAULT NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS equipped_avatar VARCHAR(20) DEFAULT '👤' NOT NULL",
            "ALTER TABLE vpn_configs ADD COLUMN IF NOT EXISTS is_premium_only BOOLEAN DEFAULT FALSE NOT NULL",
            "ALTER TABLE vpn_configs ADD COLUMN IF NOT EXISTS notify_sent BOOLEAN DEFAULT FALSE NOT NULL",
            "ALTER TABLE avatars ADD COLUMN IF NOT EXISTS item_type VARCHAR(10) DEFAULT 'avatar' NOT NULL",
            "ALTER TABLE avatars ADD COLUMN IF NOT EXISTS border_css VARCHAR(200) DEFAULT NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS equipped_frame VARCHAR(200) DEFAULT '' NOT NULL",
        ]
        for sql in migrations:
            try:
                await conn.execute(__import__('sqlalchemy').text(sql))
            except Exception:
                pass
    await seed_upgrades()
    await seed_achievements()
    await seed_new_achievements()
    await seed_avatars()
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
        now = now_msk()
        today = now.date()
        if not user:
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                is_admin=(telegram_id in ADMIN_IDS),
                login_days_count=1,
                login_streak=1,
                last_login_date=now
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
            last = user.last_login_date.date() if user.last_login_date else None
            if last != today:
                user.login_days_count = (user.login_days_count or 0) + 1
                if last and (today - last).days == 1:
                    user.login_streak = (user.login_streak or 0) + 1
                else:
                    user.login_streak = 1
                user.last_login_date = now
            await session.commit()
    return user


async def get_user_by_telegram_id(telegram_id: int) -> User | None:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()


async def do_click(telegram_id: int) -> dict:
    click_mult = await get_click_multiplier()
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            return {"balance": 0, "total_clicks": 0}
        bonus = user.clicks_per_click
        if user.is_premium:
            bonus = max(round(bonus * 1.1), bonus + 1)
        bonus = round(bonus * click_mult)
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
    click_mult = await get_click_multiplier()
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            return {"balance": 0, "total_clicks": 0}
        bonus = user.clicks_per_click
        if user.is_premium:
            bonus = max(round(bonus * 1.1), bonus + 1)
        bonus = round(bonus * click_mult)
        earned = bonus * count
        user.balance += earned
        user.total_clicks += count
        if user.balance > user.max_balance:
            user.max_balance = user.balance
        await session.commit()
        return {"balance": user.balance, "total_clicks": user.total_clicks, "earned": earned, "clicks_per_click": user.clicks_per_click}


async def get_auto_multiplier() -> float:
    promos = await get_active_promotions()
    mults = [p.value for p in promos if p.promo_type == "auto_mult"]
    return max(mults) if mults else 1.0


async def sync_autoclicks(telegram_id: int, amount: float) -> dict:
    auto_mult = await get_auto_multiplier()
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            return {"balance": 0}
        if user.is_premium:
            amount *= 1.5
        amount *= auto_mult
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


async def get_premium_prices() -> dict:
    defaults = {'month': 150000, '3months': 350000, '6months': 550000, 'year': 1000000}
    async with async_session() as session:
        for key, default in defaults.items():
            skey = f"premium_price_{key}"
            res = await session.execute(select(AppSettings).where(AppSettings.key == skey))
            if not res.scalar_one_or_none():
                session.add(AppSettings(key=skey, value=str(default), updated_at=now_msk()))
        await session.commit()
        result = await session.execute(
            select(AppSettings).where(AppSettings.key.like("premium_price_%"))
        )
        rows = result.scalars().all()
        prices = dict(defaults)
        for row in rows:
            period = row.key.replace("premium_price_", "")
            try:
                prices[period] = int(float(row.value))
            except Exception:
                pass
    return prices


async def set_premium_price(admin_telegram_id: int, period: str, price: int) -> dict:
    valid = {'month', '3months', '6months', 'year'}
    if period not in valid:
        return {"ok": False, "error": "Неверный период"}
    user = await get_user_by_telegram_id(admin_telegram_id)
    if not user or not (admin_telegram_id in ADMIN_IDS or user.is_admin):
        return {"ok": False, "error": "Нет доступа"}
    skey = f"premium_price_{period}"
    async with async_session() as session:
        res = await session.execute(select(AppSettings).where(AppSettings.key == skey))
        row = res.scalar_one_or_none()
        if row:
            row.value = str(int(price))
            row.updated_at = now_msk()
        else:
            session.add(AppSettings(key=skey, value=str(int(price)), updated_at=now_msk()))
        await session.commit()
    return {"ok": True}


async def buy_premium_subscription(telegram_id: int, period: str) -> dict:
    prices = await get_premium_prices()
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

        user.balance = int(user.balance) - price
        now = now_msk()
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
        now = now_msk()
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


async def auto_disable_expired_vpns():
    now = now_msk()
    async with async_session() as session:
        result = await session.execute(
            select(VPNConfig).where(
                VPNConfig.is_active == True,
                VPNConfig.available_until != None,
                VPNConfig.available_until < now
            )
        )
        vpns = result.scalars().all()
        for vpn in vpns:
            vpn.is_active = False
        if vpns:
            await session.commit()


async def add_vpn_config(name, description, config_data, price_clicks, duration_days, quantity, available_until, created_by, is_premium_only=False) -> VPNConfig:
    async with async_session() as session:
        if available_until is None:
            available_until = now_msk() + timedelta(days=duration_days)
        vpn = VPNConfig(
            name=name, description=description, config_data=config_data,
            price_clicks=price_clicks, duration_days=duration_days,
            quantity=quantity, quantity_left=quantity,
            available_until=available_until, created_by=created_by,
            is_premium_only=is_premium_only
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
        await session.execute(delete(VPNPurchase).where(VPNPurchase.vpn_config_id == vpn_id))
        await session.delete(vpn)
        await session.commit()
        return {"ok": True}


async def buy_vpn(telegram_id: int, vpn_id: int) -> dict:
    async with async_session() as session:
        user_res = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_res.scalar_one_or_none()
        if not user:
            return {"ok": False, "error": "Пользователь не найден"}

        now = now_msk()
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
        if vpn.is_premium_only and not user.is_premium:
            return {"ok": False, "error": "Этот VPN только для Premium пользователей"}
        vpn_disc = await get_vpn_promo_discount()
        if vpn.is_premium_only:
            discount = 0.1 if user.is_premium else 0.0
        else:
            discount = max(vpn_disc / 100.0, 0.1 if user.is_premium else 0.0)
        discount = min(discount, 0.9)
        effective_price = round(vpn.price_clicks * (1.0 - discount))
        if user.balance < effective_price:
            return {"ok": False, "error": f"Нужно {int(effective_price)} кликов"}

        user.balance -= effective_price
        vpn.quantity_left -= 1
        expires_at = vpn.available_until if vpn.available_until else now + timedelta(days=vpn.duration_days)
        purchase = VPNPurchase(user_id=user.id, vpn_config_id=vpn.id, price_paid=effective_price, expires_at=expires_at)
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


async def delete_vpn_purchase(telegram_id: int, purchase_id: int) -> dict:
    async with async_session() as session:
        user_res = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_res.scalar_one_or_none()
        if not user:
            return {"ok": False, "error": "Пользователь не найден"}
        p_res = await session.execute(
            select(VPNPurchase).where(VPNPurchase.id == purchase_id, VPNPurchase.user_id == user.id)
        )
        purchase = p_res.scalar_one_or_none()
        if not purchase:
            return {"ok": False, "error": "Запись не найдена"}
        await session.delete(purchase)
        await session.commit()
        return {"ok": True}


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


async def get_user_upgrades_admin(telegram_id: int) -> list:
    async with async_session() as session:
        user_res = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_res.scalar_one_or_none()
        if not user:
            return []
        result = await session.execute(
            select(UserUpgrade, ClickUpgrade)
            .join(ClickUpgrade, UserUpgrade.upgrade_id == ClickUpgrade.id)
            .where(UserUpgrade.user_id == user.id)
            .order_by(UserUpgrade.purchased_at.asc())
        )
        rows = result.all()
        return [
            {
                "user_upgrade_id": uu.id,
                "upgrade_id": cu.id,
                "name": cu.name,
                "icon": cu.icon,
                "upgrade_type": cu.upgrade_type,
                "clicks_bonus": cu.clicks_bonus,
                "auto_click_bonus": cu.auto_click_bonus,
                "price": cu.price,
                "purchased_at": uu.purchased_at.isoformat()
            }
            for uu, cu in rows
        ]


async def remove_user_upgrade(admin_telegram_id: int, target_telegram_id: int, user_upgrade_id: int) -> dict:
    admin = await get_user_by_telegram_id(admin_telegram_id)
    if not admin or not (admin_telegram_id in ADMIN_IDS or admin.is_admin):
        return {"ok": False, "error": "Нет доступа"}
    async with async_session() as session:
        target_res = await session.execute(select(User).where(User.telegram_id == target_telegram_id))
        target = target_res.scalar_one_or_none()
        if not target:
            return {"ok": False, "error": "Пользователь не найден"}
        uu_res = await session.execute(
            select(UserUpgrade).where(UserUpgrade.id == user_upgrade_id, UserUpgrade.user_id == target.id)
        )
        uu = uu_res.scalar_one_or_none()
        if not uu:
            return {"ok": False, "error": "Улучшение не найдено"}
        cu_res = await session.execute(select(ClickUpgrade).where(ClickUpgrade.id == uu.upgrade_id))
        cu = cu_res.scalar_one_or_none()
        if cu:
            if cu.upgrade_type == "click":
                target.clicks_per_click = max(1, target.clicks_per_click - cu.clicks_bonus)
            elif cu.upgrade_type == "autoclk":
                target.auto_clicks_per_second = max(0, target.auto_clicks_per_second - cu.auto_click_bonus)
        await session.delete(uu)
        await session.commit()
        name = cu.name if cu else f"ID {user_upgrade_id}"
    await add_user_log(target.id, target.telegram_id, "upgrade_remove", f"Улучшение «{name}» удалено администратором")
    return {"ok": True}


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
        now = now_msk()
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
            Achievement(name="Постоянный гость", description="Заходите в приложение 7 дней подряд", icon="🔥", condition_type="login_streak_gte", condition_value="7"),
            Achievement(name="Верный пользователь", description="Зайдите в приложение 30 дней", icon="📅", condition_type="login_days_gte", condition_value="30"),
            Achievement(name="Легенда", description="Зайдите в приложение 100 дней", icon="🏅", condition_type="login_days_gte", condition_value="100"),
            Achievement(name="Машина кликов", description="Получите 5 авто-кликов в секунду", icon="🤖", condition_type="autoclk_gte", condition_value="5"),
            Achievement(name="Кибер-завод", description="Получите 10 авто-кликов в секунду", icon="🏭", condition_type="autoclk_gte", condition_value="10"),
        ]
        session.add_all(items)
        await session.commit()


async def seed_new_achievements():
    new_items = [
        {"name": "Постоянный гость", "description": "Заходите в приложение 7 дней подряд", "icon": "🔥", "condition_type": "login_streak_gte", "condition_value": "7"},
        {"name": "Верный пользователь", "description": "Зайдите в приложение 30 дней", "icon": "📅", "condition_type": "login_days_gte", "condition_value": "30"},
        {"name": "Легенда", "description": "Зайдите в приложение 100 дней", "icon": "🏅", "condition_type": "login_days_gte", "condition_value": "100"},
        {"name": "Машина кликов", "description": "Получите 5 авто-кликов в секунду", "icon": "🤖", "condition_type": "autoclk_gte", "condition_value": "5"},
        {"name": "Кибер-завод", "description": "Получите 10 авто-кликов в секунду", "icon": "🏭", "condition_type": "autoclk_gte", "condition_value": "10"},
    ]
    async with async_session() as session:
        for item in new_items:
            res = await session.execute(select(Achievement).where(Achievement.name == item["name"]))
            if not res.scalar_one_or_none():
                session.add(Achievement(**item))
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

        now = now_msk()
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
            elif ct == "login_days_gte":
                unlocked = (user.login_days_count or 0) >= int(cv)
            elif ct == "login_streak_gte":
                unlocked = (user.login_streak or 0) >= int(cv)
            elif ct == "autoclk_gte":
                unlocked = user.auto_clicks_per_second >= cv

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
            "max_price": user.autobuy_max_price,
            "max_count": user.autobuy_max_count,
        }


async def save_autobuy_settings(telegram_id: int, enabled: bool, keywords: str, min_price, max_price, max_count=None) -> dict:
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
        user.autobuy_max_count = int(max_count) if max_count is not None else None
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
        if user.autobuy_max_count is not None:
            async with async_session() as session:
                count_res = await session.execute(
                    select(func.count(VPNPurchase.id)).where(VPNPurchase.user_id == user.id)
                )
                total_bought = count_res.scalar() or 0
            if total_bought >= user.autobuy_max_count:
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
    now = now_msk()
    window_start = now + timedelta(days=days_ahead - 0.5)
    window_end = now + timedelta(days=days_ahead + 0.5)
    min_purchase_age = now - timedelta(days=1)
    async with async_session() as session:
        result = await session.execute(
            select(VPNPurchase, User, VPNConfig)
            .join(User, VPNPurchase.user_id == User.id)
            .join(VPNConfig, VPNPurchase.vpn_config_id == VPNConfig.id)
            .where(
                VPNPurchase.expires_at >= window_start,
                VPNPurchase.expires_at <= window_end,
                VPNPurchase.purchased_at <= min_purchase_age,
                User.vpn_notify_enabled == True
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
    now = now_msk()
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


async def get_unsent_vpn_configs() -> list:
    async with async_session() as session:
        result = await session.execute(
            select(VPNConfig).where(
                VPNConfig.notify_sent == False,
                VPNConfig.is_active == True
            )
        )
        return result.scalars().all()


async def mark_vpn_notified(vpn_id: int):
    async with async_session() as session:
        result = await session.execute(select(VPNConfig).where(VPNConfig.id == vpn_id))
        vpn = result.scalar_one_or_none()
        if vpn:
            vpn.notify_sent = True
            await session.commit()


async def get_users_with_vpn_notify() -> list:
    async with async_session() as session:
        result = await session.execute(
            select(User).where(
                User.vpn_notify_enabled == True,
                User.is_premium == True
            )
        )
        return result.scalars().all()


# ── User settings & profile ───────────────────────────────────

async def save_user_settings(telegram_id: int, vpn_notify: bool = None, offline_income: bool = None) -> dict:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            return {"ok": False, "error": "Пользователь не найден"}
        if vpn_notify is not None:
            user.vpn_notify_enabled = vpn_notify
        if offline_income is not None:
            if offline_income and not user.is_premium:
                await session.commit()
                return {"ok": False, "error": "Требуется Premium"}
            user.offline_income_enabled = offline_income
        await session.commit()
        return {"ok": True}


async def update_user_profile(telegram_id: int, bio: str = None, badge: str = None) -> dict:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            return {"ok": False, "error": "Пользователь не найден"}
        if not user.is_premium:
            return {"ok": False, "error": "Кастомный профиль только для Premium"}
        if bio is not None:
            user.profile_bio = bio[:200] if bio else None
        if badge is not None:
            user.profile_badge = badge[:20] if badge else None
        await session.commit()
        return {"ok": True}


async def claim_offline_income(telegram_id: int) -> dict:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            return {"ok": False, "earned": 0}
        if not user.is_premium or not user.offline_income_enabled:
            return {"ok": True, "earned": 0}
        if user.auto_clicks_per_second <= 0:
            return {"ok": True, "earned": 0}
        now = now_msk()
        last = user.last_offline_check or user.created_at or now
        offline_secs = min((now - last).total_seconds(), 12 * 3600)
        if offline_secs < 60:
            return {"ok": True, "earned": 0}
        earned = offline_secs * user.auto_clicks_per_second * 1.5
        earned = int(earned)
        user.balance += earned
        if user.balance > user.max_balance:
            user.max_balance = user.balance
        user.last_offline_check = now
        await session.commit()
    if earned > 0:
        await add_user_log(user.id, telegram_id, "offline_income", f"Оффлайн-доход: +{earned} кликов за {int(offline_secs//60)} мин")
    return {"ok": True, "earned": earned, "seconds": int(offline_secs), "new_balance": user.balance}


# ── Roulette ──────────────────────────────────────────────────

ROULETTE_SEGMENTS = [
    {"label": "💀 Потеря",   "mult": 0.0,  "color": "#e53e3e", "weight": 20},
    {"label": "😢 ×0.5",    "mult": 0.5,  "color": "#ed8936", "weight": 24},
    {"label": "🤏 ×0.75",   "mult": 0.75, "color": "#c05621", "weight": 25},
    {"label": "😐 Возврат", "mult": 1.0,  "color": "#718096", "weight": 15},
    {"label": "😊 ×1.5",   "mult": 1.5,  "color": "#38a169", "weight": 10},
    {"label": "🎉 ×2",     "mult": 2.0,  "color": "#3182ce", "weight": 5},
    {"label": "🌟 ×5",     "mult": 5.0,  "color": "#d69e2e", "weight": 1},
]


async def spin_roulette(telegram_id: int, bet: int) -> dict:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            return {"ok": False, "error": "Пользователь не найден"}
        if bet < 100:
            return {"ok": False, "error": "Минимальная ставка: 100 кликов"}
        if bet > user.balance:
            return {"ok": False, "error": "Недостаточно кликов"}

        weights = [s["weight"] for s in ROULETTE_SEGMENTS]
        segment = random.choices(ROULETTE_SEGMENTS, weights=weights, k=1)[0]
        payout = int(bet * segment["mult"])
        user.balance = user.balance - bet + payout
        if user.balance > user.max_balance:
            user.max_balance = user.balance
        await session.commit()
        uid = user.id
    delta = payout - bet
    sign = "+" if delta >= 0 else ""
    await add_user_log(uid, telegram_id, "roulette", f"Рулетка: ставка {bet}, {segment['label']}, {sign}{delta}")
    return {
        "ok": True,
        "segment": segment,
        "bet": bet,
        "payout": payout,
        "delta": delta,
        "new_balance": user.balance
    }


# ── Avatars ───────────────────────────────────────────────────

AVATAR_SEED = [
    {"name": "Робот",       "emoji": "🤖", "price": 500,   "description": "Стальной помощник",    "item_type": "avatar"},
    {"name": "Кот",         "emoji": "🐱", "price": 500,   "description": "Мурчащий аватар",      "item_type": "avatar"},
    {"name": "Дракон",      "emoji": "🐲", "price": 1000,  "description": "Огнедышащий",           "item_type": "avatar"},
    {"name": "Пришелец",    "emoji": "👽", "price": 1500,  "description": "Не с этой планеты",     "item_type": "avatar"},
    {"name": "Ниндзя",      "emoji": "🥷", "price": 2000,  "description": "Невидимый воин",        "item_type": "avatar"},
    {"name": "Маг",         "emoji": "🧙", "price": 2000,  "description": "Властелин заклинаний",  "item_type": "avatar"},
    {"name": "Дьявол",      "emoji": "😈", "price": 3000,  "description": "Тёмная сила",           "item_type": "avatar"},
    {"name": "Ангел",       "emoji": "😇", "price": 3000,  "description": "Небесный защитник",     "item_type": "avatar"},
    {"name": "Лис",         "emoji": "🦊", "price": 3000,  "description": "Хитрый и ловкий",       "item_type": "avatar"},
    {"name": "Лев",         "emoji": "🦁", "price": 5000,  "description": "Царь зверей",           "item_type": "avatar"},
    {"name": "Дракон II",   "emoji": "🐉", "price": 8000,  "description": "Легендарный дракон",    "item_type": "avatar"},
    {"name": "Корона",      "emoji": "👑", "price": 10000, "description": "Для настоящих королей", "item_type": "avatar"},
    {"name": "Волк",        "emoji": "🐺", "price": 3500,  "description": "Вожак стаи",            "item_type": "avatar"},
    {"name": "Тигр",        "emoji": "🐯", "price": 4000,  "description": "Полосатый хищник",      "item_type": "avatar"},
    {"name": "Акула",       "emoji": "🦈", "price": 4500,  "description": "Король океана",         "item_type": "avatar"},
    {"name": "Феникс",      "emoji": "🦅", "price": 6000,  "description": "Возрождается из пепла", "item_type": "avatar"},
    {"name": "Единорог",    "emoji": "🦄", "price": 7000,  "description": "Магическое существо",   "item_type": "avatar"},
    {"name": "Скелет",      "emoji": "💀", "price": 5500,  "description": "Берегись темноты",      "item_type": "avatar"},
    {"name": "Клоун",       "emoji": "🤡", "price": 2500,  "description": "Смех сквозь слёзы",    "item_type": "avatar"},
    {"name": "Астронавт",   "emoji": "👨‍🚀", "price": 8500,  "description": "Из далёкого космоса",  "item_type": "avatar"},
    {"name": "Бронзовая",   "emoji": "🔵", "price": 1000,  "description": "Бронзовая рамка",       "item_type": "frame", "border_css": "outline: 3px solid #cd7f32; outline-offset: 2px; box-shadow: 0 0 8px #cd7f32"},
    {"name": "Серебряная",  "emoji": "⚪", "price": 3000,  "description": "Серебряная рамка",      "item_type": "frame", "border_css": "outline: 3px solid #c0c0c0; outline-offset: 2px; box-shadow: 0 0 10px #c0c0c0"},
    {"name": "Золотая",     "emoji": "🟡", "price": 6000,  "description": "Золотая рамка",         "item_type": "frame", "border_css": "outline: 3px solid #ffd700; outline-offset: 2px; box-shadow: 0 0 12px #ffd700"},
    {"name": "Фиолетовая",  "emoji": "🟣", "price": 5000,  "description": "Фиолетовая рамка",      "item_type": "frame", "border_css": "outline: 3px solid #7c6cf7; outline-offset: 2px; box-shadow: 0 0 12px #7c6cf7"},
    {"name": "Неоновая",    "emoji": "🟢", "price": 8000,  "description": "Неоновая зелёная",      "item_type": "frame", "border_css": "outline: 3px solid #00ff88; outline-offset: 2px; box-shadow: 0 0 14px #00ff88"},
    {"name": "Огненная",    "emoji": "🔴", "price": 9000,  "description": "Огненная рамка",        "item_type": "frame", "border_css": "outline: 3px solid #ff4500; outline-offset: 2px; box-shadow: 0 0 14px #ff4500"},
    {"name": "Алмазная",    "emoji": "💎", "price": 15000, "description": "Алмазная рамка",        "item_type": "frame", "border_css": "outline: 3px solid #b9f2ff; outline-offset: 2px; box-shadow: 0 0 16px #b9f2ff, 0 0 30px #7dd8ff"},
]


async def seed_avatars():
    async with async_session() as session:
        for av in AVATAR_SEED:
            existing = await session.execute(select(Avatar).where(Avatar.name == av["name"]))
            if not existing.scalar_one_or_none():
                session.add(Avatar(**av))
        await session.commit()


async def get_avatars_with_ownership(telegram_id: int) -> list:
    async with async_session() as session:
        user_res = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_res.scalar_one_or_none()
        if not user:
            return []
        av_res = await session.execute(select(Avatar).where(Avatar.is_active == True).order_by(Avatar.price))
        avatars = av_res.scalars().all()
        owned_res = await session.execute(select(UserAvatar.avatar_id).where(UserAvatar.user_id == user.id))
        owned_ids = set(owned_res.scalars().all())
        return [
            {
                "id": a.id, "name": a.name, "emoji": a.emoji, "price": a.price,
                "description": a.description, "item_type": a.item_type or "avatar",
                "border_css": a.border_css or "",
                "owned": a.id in owned_ids,
                "equipped": (a.item_type or "avatar") == "avatar" and a.emoji == user.equipped_avatar,
                "equipped_frame": (a.item_type or "avatar") == "frame" and a.border_css == user.equipped_frame
            }
            for a in avatars
        ]


async def buy_avatar(telegram_id: int, avatar_id: int) -> dict:
    async with async_session() as session:
        user_res = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_res.scalar_one_or_none()
        if not user:
            return {"ok": False, "error": "Пользователь не найден"}
        av_res = await session.execute(select(Avatar).where(Avatar.id == avatar_id, Avatar.is_active == True))
        av = av_res.scalar_one_or_none()
        if not av:
            return {"ok": False, "error": "Аватар не найден"}
        owned = await session.execute(
            select(UserAvatar).where(UserAvatar.user_id == user.id, UserAvatar.avatar_id == avatar_id)
        )
        if owned.scalar_one_or_none():
            return {"ok": False, "error": "Уже куплено"}
        if user.balance < av.price:
            return {"ok": False, "error": f"Нужно {int(av.price)} кликов"}
        user.balance -= av.price
        session.add(UserAvatar(user_id=user.id, avatar_id=avatar_id))
        await session.commit()
    await add_user_log(user.id, telegram_id, "avatar_buy", f"Куплен аватар «{av.name}» за {int(av.price)} кликов")
    return {"ok": True, "new_balance": user.balance}


async def equip_avatar(telegram_id: int, avatar_id: int) -> dict:
    async with async_session() as session:
        user_res = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_res.scalar_one_or_none()
        if not user:
            return {"ok": False, "error": "Пользователь не найден"}
        if avatar_id == 0:
            user.equipped_avatar = "👤"
            await session.commit()
            return {"ok": True, "emoji": "👤"}
        owned = await session.execute(
            select(UserAvatar).where(UserAvatar.user_id == user.id, UserAvatar.avatar_id == avatar_id)
        )
        if not owned.scalar_one_or_none():
            return {"ok": False, "error": "Сначала купите аватар"}
        av_res = await session.execute(select(Avatar).where(Avatar.id == avatar_id))
        av = av_res.scalar_one_or_none()
        if not av:
            return {"ok": False, "error": "Аватар не найден"}
        user.equipped_avatar = av.emoji
        await session.commit()
        return {"ok": True, "emoji": av.emoji}


async def equip_frame(telegram_id: int, avatar_id: int) -> dict:
    async with async_session() as session:
        user_res = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_res.scalar_one_or_none()
        if not user:
            return {"ok": False, "error": "Пользователь не найден"}
        if avatar_id == 0:
            user.equipped_frame = ""
            await session.commit()
            return {"ok": True, "border_css": ""}
        owned = await session.execute(
            select(UserAvatar).where(UserAvatar.user_id == user.id, UserAvatar.avatar_id == avatar_id)
        )
        if not owned.scalar_one_or_none():
            return {"ok": False, "error": "Сначала купите рамку"}
        av_res = await session.execute(select(Avatar).where(Avatar.id == avatar_id, Avatar.item_type == "frame"))
        av = av_res.scalar_one_or_none()
        if not av:
            return {"ok": False, "error": "Рамка не найдена"}
        user.equipped_frame = av.border_css or ""
        await session.commit()
        return {"ok": True, "border_css": av.border_css or ""}


async def get_global_vpn_notify() -> bool:
    async with async_session() as session:
        res = await session.execute(select(AppSettings).where(AppSettings.key == "vpn_notify_global"))
        setting = res.scalar_one_or_none()
        return setting.value == "1" if setting else True


async def set_global_vpn_notify(enabled: bool) -> dict:
    async with async_session() as session:
        res = await session.execute(select(AppSettings).where(AppSettings.key == "vpn_notify_global"))
        setting = res.scalar_one_or_none()
        if setting:
            setting.value = "1" if enabled else "0"
        else:
            session.add(AppSettings(key="vpn_notify_global", value="1" if enabled else "0"))
        await session.commit()
    return {"ok": True, "enabled": enabled}


# ── Promo Codes ───────────────────────────────────────────────

async def admin_create_promo_code(admin_telegram_id: int, code: str, name: str, amount: float, max_activations: int, expires_at=None) -> dict:
    admin = await get_user_by_telegram_id(admin_telegram_id)
    if not admin or not (admin_telegram_id in ADMIN_IDS or admin.is_admin):
        return {"ok": False, "error": "Нет доступа"}
    async with async_session() as session:
        existing = await session.execute(select(PromoCode).where(PromoCode.code == code.upper()))
        if existing.scalar_one_or_none():
            return {"ok": False, "error": "Такой код уже существует"}
        pc = PromoCode(
            code=code.upper().strip(),
            name=name,
            amount=amount,
            max_activations=max_activations,
            expires_at=expires_at,
            created_by=admin_telegram_id
        )
        session.add(pc)
        await session.commit()
        await session.refresh(pc)
        return {"ok": True, "id": pc.id}


async def toggle_promo_code(admin_telegram_id: int, code_id: int) -> dict:
    admin = await get_user_by_telegram_id(admin_telegram_id)
    if not admin or not (admin_telegram_id in ADMIN_IDS or admin.is_admin):
        return {"ok": False, "error": "Нет доступа"}
    async with async_session() as session:
        res = await session.execute(select(PromoCode).where(PromoCode.id == code_id))
        pc = res.scalar_one_or_none()
        if not pc:
            return {"ok": False, "error": "Не найден"}
        pc.is_active = not pc.is_active
        await session.commit()
        return {"ok": True, "is_active": pc.is_active}


async def admin_edit_promo_code(admin_telegram_id: int, code_id: int, **kwargs) -> dict:
    admin = await get_user_by_telegram_id(admin_telegram_id)
    if not admin or not (admin_telegram_id in ADMIN_IDS or admin.is_admin):
        return {"ok": False, "error": "Нет доступа"}
    async with async_session() as session:
        res = await session.execute(select(PromoCode).where(PromoCode.id == code_id))
        pc = res.scalar_one_or_none()
        if not pc:
            return {"ok": False, "error": "Не найден"}
        for k, v in kwargs.items():
            if hasattr(pc, k) and v is not None:
                if k == "code":
                    v = v.upper().strip()
                setattr(pc, k, v)
        await session.commit()
        return {"ok": True}


async def admin_delete_promo_code(admin_telegram_id: int, code_id: int) -> dict:
    admin = await get_user_by_telegram_id(admin_telegram_id)
    if not admin or not (admin_telegram_id in ADMIN_IDS or admin.is_admin):
        return {"ok": False, "error": "Нет доступа"}
    async with async_session() as session:
        res = await session.execute(select(PromoCode).where(PromoCode.id == code_id))
        pc = res.scalar_one_or_none()
        if not pc:
            return {"ok": False, "error": "Не найден"}
        await session.delete(pc)
        await session.commit()
        return {"ok": True}


async def admin_get_promo_codes(admin_telegram_id: int) -> list:
    admin = await get_user_by_telegram_id(admin_telegram_id)
    if not admin or not (admin_telegram_id in ADMIN_IDS or admin.is_admin):
        return []
    async with async_session() as session:
        res = await session.execute(select(PromoCode).order_by(PromoCode.created_at.desc()))
        codes = res.scalars().all()
        return [
            {
                "id": pc.id, "code": pc.code, "name": pc.name, "amount": pc.amount,
                "max_activations": pc.max_activations, "activations_used": pc.activations_used,
                "expires_at": pc.expires_at.isoformat() if pc.expires_at else None,
                "is_active": pc.is_active, "created_at": pc.created_at.isoformat()
            }
            for pc in codes
        ]


async def activate_promo_code(telegram_id: int, code: str) -> dict:
    async with async_session() as session:
        user_res = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_res.scalar_one_or_none()
        if not user:
            return {"ok": False, "error": "Пользователь не найден"}

        pc_res = await session.execute(select(PromoCode).where(PromoCode.code == code.upper().strip()))
        pc = pc_res.scalar_one_or_none()
        if not pc:
            return {"ok": False, "error": "Промокод не найден"}
        if not pc.is_active:
            return {"ok": False, "error": "Промокод деактивирован"}
        if pc.expires_at and pc.expires_at < now_msk():
            return {"ok": False, "error": "Промокод истёк"}
        if pc.activations_used >= pc.max_activations:
            return {"ok": False, "error": "Промокод исчерпан"}

        already = await session.execute(
            select(PromoCodeActivation).where(
                PromoCodeActivation.promo_code_id == pc.id,
                PromoCodeActivation.user_id == user.id
            )
        )
        if already.scalar_one_or_none():
            return {"ok": False, "error": "Вы уже активировали этот промокод"}

        pc.activations_used += 1
        user.balance += pc.amount
        if user.balance > user.max_balance:
            user.max_balance = user.balance
        session.add(PromoCodeActivation(promo_code_id=pc.id, user_id=user.id))
        await session.commit()
    await add_user_log(user.id, telegram_id, "promo_activate", f"Активирован промокод «{pc.name}» (+{int(pc.amount)} кликов)")
    return {"ok": True, "amount": pc.amount, "name": pc.name, "new_balance": user.balance}


async def get_or_create_api_key(telegram_id: int) -> dict:
    async with async_session() as session:
        user_res = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_res.scalar_one_or_none()
        if not user:
            return {"ok": False, "error": "Пользователь не найден"}
        ak_res = await session.execute(select(ApiKey).where(ApiKey.user_id == user.id))
        ak = ak_res.scalar_one_or_none()
        if not ak:
            ak = ApiKey(user_id=user.id, key=secrets.token_hex(32))
            session.add(ak)
            await session.commit()
        return {"ok": True, "key": ak.key, "created_at": ak.created_at.isoformat(), "last_used_at": ak.last_used_at.isoformat() if ak.last_used_at else None}


async def regenerate_api_key(telegram_id: int) -> dict:
    async with async_session() as session:
        user_res = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_res.scalar_one_or_none()
        if not user:
            return {"ok": False, "error": "Пользователь не найден"}
        await session.execute(delete(ApiKey).where(ApiKey.user_id == user.id))
        new_key = secrets.token_hex(32)
        session.add(ApiKey(user_id=user.id, key=new_key))
        await session.commit()
        return {"ok": True, "key": new_key}


async def get_user_by_api_key(key: str) -> dict | None:
    async with async_session() as session:
        ak_res = await session.execute(select(ApiKey).where(ApiKey.key == key))
        ak = ak_res.scalar_one_or_none()
        if not ak:
            return None
        ak.last_used_at = now_msk()
        user_res = await session.execute(select(User).where(User.id == ak.user_id))
        user = user_res.scalar_one_or_none()
        await session.commit()
        if not user:
            return None
        return {
            "telegram_id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
            "balance": user.balance,
            "total_clicks": user.total_clicks,
            "clicks_per_click": user.clicks_per_click,
            "auto_clicks_per_second": user.auto_clicks_per_second,
            "is_premium": user.is_premium,
            "is_admin": user.is_admin,
            "login_streak": user.login_streak,
            "created_at": user.created_at.isoformat(),
        }
