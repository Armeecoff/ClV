from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import os

from database.db import (
    get_or_create_user, add_click, get_upgrades, get_user_upgrades,
    buy_upgrade, get_vpn_configs, buy_vpn, get_user_vpn_purchases,
    adjust_balance, get_all_vpn_configs, add_vpn_config, toggle_vpn_active,
    get_all_users, set_admin, get_user_by_telegram_id
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
        "id": user.id,
        "telegram_id": user.telegram_id,
        "username": user.username,
        "first_name": user.first_name,
        "balance": user.balance,
        "total_clicks": user.total_clicks,
        "clicks_per_click": user.clicks_per_click,
        "is_admin": check_admin(user.telegram_id, user.is_admin)
    }


@app.post("/api/click/{telegram_id}")
async def do_click(telegram_id: int):
    result = await add_click(telegram_id)
    return result


@app.get("/api/upgrades")
async def list_upgrades():
    upgrades = await get_upgrades()
    return [
        {
            "id": u.id,
            "name": u.name,
            "description": u.description,
            "price": u.price,
            "clicks_bonus": u.clicks_bonus,
            "icon": u.icon
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
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "price_clicks": c.price_clicks,
            "duration_days": c.duration_days,
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


# Admin endpoints
@app.get("/api/admin/check/{telegram_id}")
async def admin_check(telegram_id: int):
    user = await get_user_by_telegram_id(telegram_id)
    is_adm = check_admin(telegram_id, user.is_admin if user else False)
    return {"is_admin": is_adm}


@app.get("/api/admin/users/{telegram_id}")
async def admin_get_users(telegram_id: int):
    user = await get_user_by_telegram_id(telegram_id)
    if not check_admin(telegram_id, user.is_admin if user else False):
        raise HTTPException(status_code=403, detail="Нет доступа")
    users = await get_all_users()
    return [
        {
            "id": u.id,
            "telegram_id": u.telegram_id,
            "username": u.username,
            "first_name": u.first_name,
            "balance": u.balance,
            "total_clicks": u.total_clicks,
            "clicks_per_click": u.clicks_per_click,
            "is_admin": u.is_admin,
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
    user = await get_user_by_telegram_id(data.admin_telegram_id)
    if not check_admin(data.admin_telegram_id, user.is_admin if user else False):
        raise HTTPException(status_code=403, detail="Нет доступа")
    return await adjust_balance(data.target_telegram_id, data.amount)


@app.get("/api/admin/vpn/{telegram_id}")
async def admin_get_vpn(telegram_id: int):
    user = await get_user_by_telegram_id(telegram_id)
    if not check_admin(telegram_id, user.is_admin if user else False):
        raise HTTPException(status_code=403, detail="Нет доступа")
    configs = await get_all_vpn_configs()
    return [
        {
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "config_data": c.config_data,
            "price_clicks": c.price_clicks,
            "duration_days": c.duration_days,
            "quantity": c.quantity,
            "quantity_left": c.quantity_left,
            "available_until": c.available_until.isoformat() if c.available_until else None,
            "is_active": c.is_active,
            "created_at": c.created_at.isoformat()
        }
        for c in configs
    ]


class VPNCreate(BaseModel):
    admin_telegram_id: int
    name: str
    description: str
    config_data: str
    price_clicks: float
    duration_days: int
    quantity: int
    available_until: Optional[str] = None


@app.post("/api/admin/vpn")
async def admin_add_vpn(data: VPNCreate):
    user = await get_user_by_telegram_id(data.admin_telegram_id)
    if not check_admin(data.admin_telegram_id, user.is_admin if user else False):
        raise HTTPException(status_code=403, detail="Нет доступа")
    available_until = None
    if data.available_until:
        try:
            available_until = datetime.fromisoformat(data.available_until)
        except Exception:
            raise HTTPException(status_code=400, detail="Неверный формат даты")
    vpn = await add_vpn_config(
        name=data.name,
        description=data.description,
        config_data=data.config_data,
        price_clicks=data.price_clicks,
        duration_days=data.duration_days,
        quantity=data.quantity,
        available_until=available_until,
        created_by=data.admin_telegram_id
    )
    return {"ok": True, "id": vpn.id}


class VPNToggle(BaseModel):
    admin_telegram_id: int
    vpn_id: int


@app.post("/api/admin/vpn/toggle")
async def admin_toggle_vpn(data: VPNToggle):
    user = await get_user_by_telegram_id(data.admin_telegram_id)
    if not check_admin(data.admin_telegram_id, user.is_admin if user else False):
        raise HTTPException(status_code=403, detail="Нет доступа")
    return await toggle_vpn_active(data.vpn_id)


class AdminSet(BaseModel):
    admin_telegram_id: int
    target_telegram_id: int
    is_admin: bool


@app.post("/api/admin/setadmin")
async def admin_set_admin(data: AdminSet):
    if data.admin_telegram_id not in ADMIN_IDS:
        raise HTTPException(status_code=403, detail="Только супер-администраторы могут выдавать права")
    return await set_admin(data.target_telegram_id, data.is_admin)
