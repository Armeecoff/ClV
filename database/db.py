from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import select, delete
from datetime import datetime, timedelta
from config import DATABASE_URL, ADMIN_IDS
from database.models import Base, User, ClickUpgrade, UserUpgrade, VPNConfig, VPNPurchase

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Migrations: add new columns if they don't exist yet
        migrations = [
            "ALTER TABLE click_upgrades ADD COLUMN IF NOT EXISTS upgrade_type VARCHAR(10) DEFAULT 'click' NOT NULL",
            "ALTER TABLE click_upgrades ADD COLUMN IF NOT EXISTS auto_click_bonus FLOAT DEFAULT 0.0 NOT NULL",
            "ALTER TABLE click_upgrades ADD COLUMN IF NOT EXISTS is_premium_only BOOLEAN DEFAULT FALSE NOT NULL",
            "ALTER TABLE click_upgrades ADD COLUMN IF NOT EXISTS clicks_bonus INTEGER DEFAULT 0 NOT NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS auto_clicks_per_second FLOAT DEFAULT 0.0 NOT NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_premium BOOLEAN DEFAULT FALSE NOT NULL",
        ]
        for sql in migrations:
            try:
                await conn.execute(__import__('sqlalchemy').text(sql))
            except Exception:
                pass
    await seed_upgrades()


async def seed_upgrades():
    async with async_session() as session:
        result = await session.execute(select(ClickUpgrade).limit(1))
        if result.scalar():
            return
        upgrades = [
            ClickUpgrade(name="Двойной клик", description="+1 к каждому клику", price=50, upgrade_type="click", clicks_bonus=1, icon="✌️"),
            ClickUpgrade(name="Быстрые пальцы", description="+3 к каждому клику", price=150, upgrade_type="click", clicks_bonus=3, icon="👆"),
            ClickUpgrade(name="Кликер Pro", description="+5 к каждому клику", price=400, upgrade_type="click", clicks_bonus=5, icon="🖱️"),
            ClickUpgrade(name="Супер Клик", description="+10 к каждому клику", price=1000, upgrade_type="click", clicks_bonus=10, icon="💥"),
            ClickUpgrade(name="Мега Клик", description="+25 к каждому клику", price=3000, upgrade_type="click", clicks_bonus=25, icon="⚡"),
            ClickUpgrade(name="Ультра Клик", description="+50 к каждому клику", price=8000, upgrade_type="click", clicks_bonus=50, icon="🚀"),
            ClickUpgrade(name="Авто-кликер I", description="+0.5 кликов/сек автоматически", price=500, upgrade_type="autoclk", auto_click_bonus=0.5, icon="🤖"),
            ClickUpgrade(name="Авто-кликер II", description="+1 клик/сек автоматически", price=1500, upgrade_type="autoclk", auto_click_bonus=1.0, icon="⚙️"),
            ClickUpgrade(name="Авто-кликер III", description="+3 кликов/сек автоматически", price=5000, upgrade_type="autoclk", auto_click_bonus=3.0, icon="🏭"),
            ClickUpgrade(name="Авто-кликер IV", description="+10 кликов/сек автоматически", price=15000, upgrade_type="autoclk", auto_click_bonus=10.0, icon="🛸", is_premium_only=True),
        ]
        session.add_all(upgrades)
        await session.commit()


async def get_or_create_user(telegram_id: int, username: str = None, first_name: str = None) -> User:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            is_admin = telegram_id in ADMIN_IDS
            user = User(
                telegram_id=telegram_id, username=username,
                first_name=first_name, is_admin=is_admin,
                balance=0, total_clicks=0, clicks_per_click=1,
                auto_clicks_per_second=0.0
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        else:
            if telegram_id in ADMIN_IDS and not user.is_admin:
                user.is_admin = True
                await session.commit()
                await session.refresh(user)
        return user


async def get_user_by_telegram_id(telegram_id: int) -> User | None:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()


async def add_click(telegram_id: int) -> dict:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            return {"balance": 0, "total_clicks": 0, "clicks_per_click": 1}
        bonus = user.clicks_per_click
        if user.is_premium:
            bonus = int(bonus * 1.1) or bonus
        user.balance += bonus
        user.total_clicks += 1
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
        await session.commit()
        return {"balance": user.balance, "total_clicks": user.total_clicks, "earned": earned}


async def sync_autoclicks(telegram_id: int, amount: float) -> dict:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            return {"balance": 0}
        if user.is_premium:
            amount *= 1.1
        user.balance += amount
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

        if user.balance < upgrade.price:
            return {"ok": False, "error": f"Нужно {int(upgrade.price)} кликов, у вас {int(user.balance)}"}

        user.balance -= upgrade.price
        if upgrade.upgrade_type == "click":
            user.clicks_per_click += upgrade.clicks_bonus
        elif upgrade.upgrade_type == "autoclk":
            user.auto_clicks_per_second += upgrade.auto_click_bonus

        uu = UserUpgrade(user_id=user.id, upgrade_id=upgrade.id)
        session.add(uu)
        await session.commit()
        return {
            "ok": True,
            "new_balance": user.balance,
            "clicks_per_click": user.clicks_per_click,
            "auto_clicks_per_second": user.auto_clicks_per_second
        }


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
        if user.balance < vpn.price_clicks:
            return {"ok": False, "error": f"Нужно {int(vpn.price_clicks)} кликов"}

        user.balance -= vpn.price_clicks
        vpn.quantity_left -= 1
        expires_at = now + timedelta(days=vpn.duration_days)
        purchase = VPNPurchase(user_id=user.id, vpn_config_id=vpn.id, price_paid=vpn.price_clicks, expires_at=expires_at)
        session.add(purchase)
        await session.commit()
        return {"ok": True, "config_data": vpn.config_data, "expires_at": expires_at.isoformat(), "new_balance": user.balance}


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
        await session.commit()
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


async def admin_delete_upgrade(upgrade_id: int) -> dict:
    async with async_session() as session:
        result = await session.execute(select(ClickUpgrade).where(ClickUpgrade.id == upgrade_id))
        upg = result.scalar_one_or_none()
        if not upg:
            return {"ok": False, "error": "Не найдено"}
        await session.delete(upg)
        await session.commit()
        return {"ok": True}
