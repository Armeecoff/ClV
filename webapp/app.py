from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import os

from database.db import (
    get_or_create_user, sync_clicks, sync_autoclicks,
    get_upgrades, get_user_upgrade_ids, buy_upgrade,
    get_vpn_configs, buy_vpn, get_user_vpn_purchases,
    adjust_balance, get_all_vpn_configs, add_vpn_config,
    edit_vpn_config, delete_vpn_config, toggle_vpn_active,
    get_all_users, set_admin, set_premium, get_user_by_telegram_id,
    admin_add_upgrade, admin_edit_upgrade, admin_delete_upgrade,
    delete_user
)
from config import ADMIN_IDS

app = FastAPI()
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def check_admin(telegram_id: int, user_is_admin: bool) -> bool:
    return telegram_id in ADMIN_IDS or user_is_admin


@app.get("/")
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/user/{telegram_id}")
async def get_user(telegram_id: int, username: str = None, first_name: str = None):
    user = await get_or_create_user(telegram_id, username, first_name)
    return {
        "id": user.id, "telegram_id": user.telegram_id,
        "username": user.username, "first_name": user.first_name,
        "balance": user.balance, "total_clicks": user.total_clicks,
        "clicks_per_click": user.clicks_per_click,
        "auto_clicks_per_second": user.auto_clicks_per_second,
        "is_admin": check_admin(user.telegram_id, user.is_admin),
        "is_premium": user.is_premium
    }


class ClickSync(BaseModel):
    count: int = 1


@app.post("/api/click/{telegram_id}")
async def do_click(telegram_id: int, body: ClickSync = None):
    count = (body.count if body else 1) or 1
    count = min(count, 500)
    return await sync_clicks(telegram_id, count)


class AutoClickSync(BaseModel):
    amount: float


@app.post("/api/autoclk/{telegram_id}")
async def do_autoclk(telegram_id: int, body: AutoClickSync):
    amount = min(abs(body.amount), 10000)
    return await sync_autoclicks(telegram_id, amount)


@app.get("/api/upgrades/{telegram_id}")
async def list_upgrades(telegram_id: int):
    upgrades = await get_upgrades()
    owned = await get_user_upgrade_ids(telegram_id)
    user = await get_user_by_telegram_id(telegram_id)
    is_premium = user.is_premium if user else False
    return [
        {
            "id": u.id, "name": u.name, "description": u.description,
            "price": u.price, "upgrade_type": u.upgrade_type,
            "clicks_bonus": u.clicks_bonus, "auto_click_bonus": u.auto_click_bonus,
            "icon": u.icon, "is_premium_only": u.is_premium_only,
            "owned": u.id in owned,
            "locked": u.is_premium_only and not is_premium
        }
        for u in upgrades
    ]


@app.post("/api/upgrades/buy/{telegram_id}/{upgrade_id}")
async def purchase_upgrade(telegram_id: int, upgrade_id: int):
    return await buy_upgrade(telegram_id, upgrade_id)


@app.get("/api/vpn")
async def list_vpn():
    configs = await get_vpn_configs()
    return [
        {
            "id": c.id, "name": c.name, "description": c.description,
            "price_clicks": c.price_clicks, "duration_days": c.duration_days,
            "quantity_left": c.quantity_left,
            "available_until": c.available_until.isoformat() if c.available_until else None
        }
        for c in configs
    ]


@app.post("/api/vpn/buy/{telegram_id}/{vpn_id}")
async def purchase_vpn(telegram_id: int, vpn_id: int):
    return await buy_vpn(telegram_id, vpn_id)


@app.get("/api/vpn/purchases/{telegram_id}")
async def user_vpn_purchases(telegram_id: int):
    return await get_user_vpn_purchases(telegram_id)


# ── Admin ──────────────────────────────────────────────

async def require_admin(telegram_id: int):
    user = await get_user_by_telegram_id(telegram_id)
    if not check_admin(telegram_id, user.is_admin if user else False):
        raise HTTPException(status_code=403, detail="Нет доступа")


@app.get("/api/admin/check/{telegram_id}")
async def admin_check(telegram_id: int):
    user = await get_user_by_telegram_id(telegram_id)
    return {"is_admin": check_admin(telegram_id, user.is_admin if user else False)}


@app.get("/api/admin/users/{telegram_id}")
async def admin_get_users(telegram_id: int):
    await require_admin(telegram_id)
    users = await get_all_users()
    return [
        {
            "id": u.id, "telegram_id": u.telegram_id,
            "username": u.username, "first_name": u.first_name,
            "balance": u.balance, "total_clicks": u.total_clicks,
            "clicks_per_click": u.clicks_per_click,
            "auto_clicks_per_second": u.auto_clicks_per_second,
            "is_admin": u.is_admin, "is_premium": u.is_premium,
            "created_at": u.created_at.isoformat()
        }
        for u in users
    ]


class BalanceAdjust(BaseModel):
    admin_telegram_id: int
    target_telegram_id: int
    amount: float


@app.post("/api/admin/balance")
async def admin_adjust_balance(data: BalanceAdjust):
    await require_admin(data.admin_telegram_id)
    return await adjust_balance(data.target_telegram_id, data.amount)


@app.get("/api/admin/vpn/{telegram_id}")
async def admin_get_vpn(telegram_id: int):
    await require_admin(telegram_id)
    configs = await get_all_vpn_configs()
    return [
        {
            "id": c.id, "name": c.name, "description": c.description,
            "config_data": c.config_data, "price_clicks": c.price_clicks,
            "duration_days": c.duration_days, "quantity": c.quantity,
            "quantity_left": c.quantity_left,
            "available_until": c.available_until.isoformat() if c.available_until else None,
            "is_active": c.is_active, "created_at": c.created_at.isoformat()
        }
        for c in configs
    ]


class VPNCreate(BaseModel):
    admin_telegram_id: int
    name: str
    description: str = ""
    config_data: str
    price_clicks: float
    duration_days: int
    quantity: int
    available_until: Optional[str] = None


@app.post("/api/admin/vpn")
async def admin_add_vpn(data: VPNCreate):
    await require_admin(data.admin_telegram_id)
    available_until = None
    if data.available_until:
        try:
            available_until = datetime.fromisoformat(data.available_until)
        except Exception:
            raise HTTPException(status_code=400, detail="Неверный формат даты")
    vpn = await add_vpn_config(
        name=data.name, description=data.description, config_data=data.config_data,
        price_clicks=data.price_clicks, duration_days=data.duration_days,
        quantity=data.quantity, available_until=available_until, created_by=data.admin_telegram_id
    )
    return {"ok": True, "id": vpn.id}


class VPNEdit(BaseModel):
    admin_telegram_id: int
    vpn_id: int
    name: Optional[str] = None
    description: Optional[str] = None
    config_data: Optional[str] = None
    price_clicks: Optional[float] = None
    duration_days: Optional[int] = None
    quantity: Optional[int] = None
    available_until: Optional[str] = None
    is_active: Optional[bool] = None


@app.post("/api/admin/vpn/edit")
async def admin_edit_vpn(data: VPNEdit):
    await require_admin(data.admin_telegram_id)
    kwargs = {k: v for k, v in data.dict().items() if k not in ("admin_telegram_id", "vpn_id") and v is not None}
    if "available_until" in kwargs:
        try:
            kwargs["available_until"] = datetime.fromisoformat(kwargs["available_until"])
        except Exception:
            kwargs.pop("available_until")
    return await edit_vpn_config(data.vpn_id, **kwargs)


class VPNDelete(BaseModel):
    admin_telegram_id: int
    vpn_id: int


@app.post("/api/admin/vpn/delete")
async def admin_delete_vpn(data: VPNDelete):
    await require_admin(data.admin_telegram_id)
    return await delete_vpn_config(data.vpn_id)


class VPNToggle(BaseModel):
    admin_telegram_id: int
    vpn_id: int


@app.post("/api/admin/vpn/toggle")
async def admin_toggle_vpn(data: VPNToggle):
    await require_admin(data.admin_telegram_id)
    return await toggle_vpn_active(data.vpn_id)


class AdminSet(BaseModel):
    admin_telegram_id: int
    target_telegram_id: int
    is_admin: bool


@app.post("/api/admin/setadmin")
async def admin_set_admin(data: AdminSet):
    if data.admin_telegram_id not in ADMIN_IDS:
        raise HTTPException(status_code=403, detail="Только супер-администраторы")
    return await set_admin(data.target_telegram_id, data.is_admin)


class PremiumSet(BaseModel):
    admin_telegram_id: int
    target_telegram_id: int
    is_premium: bool


@app.post("/api/admin/setpremium")
async def admin_set_premium(data: PremiumSet):
    await require_admin(data.admin_telegram_id)
    return await set_premium(data.target_telegram_id, data.is_premium)


class UpgradeCreate(BaseModel):
    admin_telegram_id: int
    name: str
    description: str = ""
    price: float
    upgrade_type: str = "click"
    clicks_bonus: int = 0
    auto_click_bonus: float = 0.0
    icon: str = "⚡"
    is_premium_only: bool = False


@app.post("/api/admin/upgrades")
async def admin_create_upgrade(data: UpgradeCreate):
    await require_admin(data.admin_telegram_id)
    upg = await admin_add_upgrade(
        name=data.name, description=data.description, price=data.price,
        upgrade_type=data.upgrade_type, clicks_bonus=data.clicks_bonus,
        auto_click_bonus=data.auto_click_bonus, icon=data.icon,
        is_premium_only=data.is_premium_only
    )
    return {"ok": True, "id": upg.id}


class UpgradeEdit(BaseModel):
    admin_telegram_id: int
    upgrade_id: int
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    upgrade_type: Optional[str] = None
    clicks_bonus: Optional[int] = None
    auto_click_bonus: Optional[float] = None
    icon: Optional[str] = None
    is_premium_only: Optional[bool] = None
    is_active: Optional[bool] = None


@app.post("/api/admin/upgrades/edit")
async def admin_edit_upg(data: UpgradeEdit):
    await require_admin(data.admin_telegram_id)
    kwargs = {k: v for k, v in data.dict().items() if k not in ("admin_telegram_id", "upgrade_id") and v is not None}
    return await admin_edit_upgrade(data.upgrade_id, **kwargs)


class UpgradeDelete(BaseModel):
    admin_telegram_id: int
    upgrade_id: int


@app.post("/api/admin/upgrades/delete")
async def admin_delete_upg(data: UpgradeDelete):
    await require_admin(data.admin_telegram_id)
    return await admin_delete_upgrade(data.upgrade_id)


@app.get("/api/admin/upgrades/{telegram_id}")
async def admin_get_upgrades(telegram_id: int):
    await require_admin(telegram_id)
    upgrades = await get_upgrades()
    return [
        {
            "id": u.id, "name": u.name, "description": u.description,
            "price": u.price, "upgrade_type": u.upgrade_type,
            "clicks_bonus": u.clicks_bonus, "auto_click_bonus": u.auto_click_bonus,
            "icon": u.icon, "is_premium_only": u.is_premium_only, "is_active": u.is_active
        }
        for u in upgrades
    ]


class UserDelete(BaseModel):
    admin_telegram_id: int
    target_telegram_id: int


@app.post("/api/admin/users/delete")
async def admin_delete_user(data: UserDelete):
    await require_admin(data.admin_telegram_id)
    return await delete_user(data.target_telegram_id)
