from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import select, update
from datetime import datetime, timedelta
from config import DATABASE_URL, ADMIN_IDS
from database.models import Base, User, ClickUpgrade, UserUpgrade, VPNConfig, VPNPurchase

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await seed_upgrades()


async def seed_upgrades():
    async with async_session() as session:
        result = await session.execute(select(ClickUpgrade).limit(1))
        if result.scalar():
            return
        upgrades = [
            ClickUpgrade(name="Двойной клик", description="Каждый клик даёт +1 очко", price=50, clicks_bonus=1, icon="✌️"),
            ClickUpgrade(name="Быстрые пальцы", description="Каждый клик даёт +3 очка", price=150, clicks_bonus=3, icon="👆"),
            ClickUpgrade(name="Кликер Pro", description="Каждый клик даёт +5 очков", price=400, clicks_bonus=5, icon="🖱️"),
            ClickUpgrade(name="Супер Клик", description="Каждый клик даёт +10 очков", price=1000, clicks_bonus=10, icon="💥"),
            ClickUpgrade(name="Мега Клик", description="Каждый клик даёт +25 очков", price=3000, clicks_bonus=25, icon="⚡"),
            ClickUpgrade(name="Ультра Клик", description="Каждый клик даёт +50 очков", price=8000, clicks_bonus=50, icon="🚀"),
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
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                is_admin=is_admin,
                balance=0,
                total_clicks=0,
                clicks_per_click=1
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


async def get_user_by_id(user_id: int) -> User | None:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()


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
        user.balance += user.clicks_per_click
        user.total_clicks += 1
        await session.commit()
        return {
            "balance": user.balance,
            "total_clicks": user.total_clicks,
            "clicks_per_click": user.clicks_per_click
        }


async def get_upgrades() -> list[ClickUpgrade]:
    async with async_session() as session:
        result = await session.execute(select(ClickUpgrade).where(ClickUpgrade.is_active == True))
        return result.scalars().all()


async def get_user_upgrades(telegram_id: int) -> list[UserUpgrade]:
    async with async_session() as session:
        result = await session.execute(
            select(UserUpgrade)
            .join(User)
            .where(User.telegram_id == telegram_id)
        )
        upgrades = result.scalars().all()
        for u in upgrades:
            await session.refresh(u, ["upgrade"])
        return upgrades


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

        if user.balance < upgrade.price:
            return {"ok": False, "error": f"Недостаточно кликов. Нужно: {upgrade.price}, у вас: {user.balance}"}

        user.balance -= upgrade.price
        user.clicks_per_click += upgrade.clicks_bonus
        uu = UserUpgrade(user_id=user.id, upgrade_id=upgrade.id)
        session.add(uu)
        await session.commit()
        return {"ok": True, "new_balance": user.balance, "clicks_per_click": user.clicks_per_click}


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


async def add_vpn_config(name: str, description: str, config_data: str, price_clicks: float,
                          duration_days: int, quantity: int, available_until: datetime | None,
                          created_by: int) -> VPNConfig:
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


async def buy_vpn(telegram_id: int, vpn_id: int) -> dict:
    async with async_session() as session:
        user_res = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_res.scalar_one_or_none()
        if not user:
            return {"ok": False, "error": "Пользователь не найден"}

        now = datetime.utcnow()
        vpn_res = await session.execute(
            select(VPNConfig).where(
                VPNConfig.id == vpn_id,
                VPNConfig.is_active == True,
                VPNConfig.quantity_left > 0,
                (VPNConfig.available_until == None) | (VPNConfig.available_until > now)
            )
        )
        vpn = vpn_res.scalar_one_or_none()
        if not vpn:
            return {"ok": False, "error": "VPN конфиг не найден или недоступен"}

        if user.balance < vpn.price_clicks:
            return {"ok": False, "error": f"Недостаточно кликов. Нужно: {vpn.price_clicks}"}

        user.balance -= vpn.price_clicks
        vpn.quantity_left -= 1
        expires_at = now + timedelta(days=vpn.duration_days)
        purchase = VPNPurchase(
            user_id=user.id, vpn_config_id=vpn.id,
            price_paid=vpn.price_clicks, expires_at=expires_at
        )
        session.add(purchase)
        await session.commit()
        await session.refresh(purchase)
        return {
            "ok": True,
            "config_data": vpn.config_data,
            "expires_at": expires_at.isoformat(),
            "new_balance": user.balance
        }


async def get_user_vpn_purchases(telegram_id: int) -> list:
    async with async_session() as session:
        user_res = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_res.scalar_one_or_none()
        if not user:
            return []
        result = await session.execute(
            select(VPNPurchase).where(VPNPurchase.user_id == user.id)
        )
        purchases = result.scalars().all()
        out = []
        for p in purchases:
            vpn_res = await session.execute(select(VPNConfig).where(VPNConfig.id == p.vpn_config_id))
            vpn = vpn_res.scalar_one_or_none()
            out.append({
                "id": p.id,
                "vpn_name": vpn.name if vpn else "Удалён",
                "price_paid": p.price_paid,
                "purchased_at": p.purchased_at.isoformat(),
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
