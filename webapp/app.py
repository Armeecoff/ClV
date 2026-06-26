from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import os

from database.db import (
    get_or_create_user, sync_clicks, sync_autoclicks,
    get_upgrades, get_user_upgrade_ids, buy_upgrade,
    get_vpn_configs, buy_vpn, get_user_vpn_purchases, delete_vpn_purchase,
    adjust_balance, get_all_vpn_configs, add_vpn_config,
    edit_vpn_config, delete_vpn_config, toggle_vpn_active,
    get_all_users, set_admin, set_premium, get_user_by_telegram_id,
    admin_add_upgrade, admin_edit_upgrade, admin_delete_upgrade,
    delete_user, buy_premium_subscription,
    get_active_promotions, get_all_promotions, add_promotion,
    delete_promotion, toggle_promotion,
    get_all_logs, get_user_logs,
    get_achievements, check_and_unlock_achievements,
    admin_get_achievements, admin_add_achievement,
    admin_edit_achievement, admin_delete_achievement,
    get_autobuy_settings, save_autobuy_settings,
    get_user_extended_history,
    get_premium_prices, set_premium_price,
    get_user_upgrades_admin, remove_user_upgrade,
    get_avatars_with_ownership, buy_avatar, equip_avatar, equip_frame,
    spin_roulette,
    admin_create_promo_code, admin_edit_promo_code,
    get_news, get_news_by_id, get_all_news_admin, add_news, edit_news, delete_news, toggle_news,
    admin_delete_promo_code, admin_get_promo_codes, activate_promo_code, toggle_promo_code,
    save_user_settings, update_user_profile, claim_offline_income,
    get_or_create_api_key, regenerate_api_key, get_user_by_api_key,
    get_global_vpn_notify, set_global_vpn_notify
)
from config import ADMIN_IDS

app = FastAPI()
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def check_admin(telegram_id: int, user_is_admin: bool) -> bool:
    return telegram_id in ADMIN_IDS or user_is_admin


@app.get("/")
async def root():
    file_path = os.path.join(STATIC_DIR, "index.html")
    with open(file_path, "rb") as f:
        content = f.read()
    return Response(
        content=content,
        media_type="text/html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        }
    )


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
        "is_premium": user.is_premium,
        "premium_until": user.premium_until.isoformat() if user.premium_until else None,
        "profile_bio": user.profile_bio,
        "profile_badge": user.profile_badge,
        "vpn_notify_enabled": user.vpn_notify_enabled,
        "offline_income_enabled": user.offline_income_enabled,
        "news_show": user.news_show,
        "news_notify_enabled": user.news_notify_enabled,
        "equipped_avatar": user.equipped_avatar or "👤",
        "equipped_frame": user.equipped_frame or ""
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


class PremiumBuy(BaseModel):
    period: str


@app.post("/api/premium/buy/{telegram_id}")
async def purchase_premium(telegram_id: int, body: PremiumBuy):
    return await buy_premium_subscription(telegram_id, body.period)


@app.get("/api/vpn")
async def list_vpn():
    configs = await get_vpn_configs()
    return [
        {
            "id": c.id, "name": c.name, "description": c.description,
            "price_clicks": c.price_clicks, "duration_days": c.duration_days,
            "quantity_left": c.quantity_left,
            "is_premium_only": c.is_premium_only,
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


@app.delete("/api/vpn/purchase/{telegram_id}/{purchase_id}")
async def remove_vpn_purchase(telegram_id: int, purchase_id: int):
    return await delete_vpn_purchase(telegram_id, purchase_id)


# ── Achievements ──────────────────────────────────────────────

@app.get("/api/achievements/{telegram_id}")
async def list_achievements(telegram_id: int):
    return await get_achievements(telegram_id)


class AchievementCheck(BaseModel):
    owned_skins: list = []
    owned_items_count: int = 0
    themes_tried_count: int = 0


@app.post("/api/achievements/check/{telegram_id}")
async def check_achievements(telegram_id: int, body: AchievementCheck):
    return await check_and_unlock_achievements(telegram_id, body.dict())


# ── Extended History ──────────────────────────────────────────

@app.get("/api/user/history/{telegram_id}")
async def extended_history(telegram_id: int):
    user = await get_user_by_telegram_id(telegram_id)
    if not user or not user.is_premium:
        raise HTTPException(status_code=403, detail="Требуется Premium")
    return await get_user_extended_history(telegram_id, 100)


# ── Autobuy Settings ─────────────────────────────────────────

@app.get("/api/user/autobuy/{telegram_id}")
async def get_autobuy(telegram_id: int):
    user = await get_user_by_telegram_id(telegram_id)
    if not user or not user.is_premium:
        raise HTTPException(status_code=403, detail="Требуется Premium")
    return await get_autobuy_settings(telegram_id)


class AutobuySettings(BaseModel):
    enabled: bool = False
    keywords: str = ""
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    max_count: Optional[int] = None


@app.post("/api/user/autobuy/{telegram_id}")
async def set_autobuy(telegram_id: int, body: AutobuySettings):
    return await save_autobuy_settings(
        telegram_id, body.enabled, body.keywords, body.min_price, body.max_price, body.max_count
    )


# ── User Settings & Profile ───────────────────────────────────

class UserSettingsBody(BaseModel):
    vpn_notify_enabled: Optional[bool] = None
    offline_income_enabled: Optional[bool] = None
    news_show: Optional[bool] = None
    news_notify_enabled: Optional[bool] = None


@app.post("/api/user/settings/{telegram_id}")
async def update_settings(telegram_id: int, body: UserSettingsBody):
    return await save_user_settings(
        telegram_id, body.vpn_notify_enabled, body.offline_income_enabled,
        body.news_show, body.news_notify_enabled
    )


class ProfileUpdateBody(BaseModel):
    bio: Optional[str] = None
    badge: Optional[str] = None


@app.post("/api/user/profile/{telegram_id}")
async def update_profile(telegram_id: int, body: ProfileUpdateBody):
    return await update_user_profile(telegram_id, body.bio, body.badge)


@app.post("/api/user/offline-income/{telegram_id}")
async def get_offline_income(telegram_id: int):
    return await claim_offline_income(telegram_id)


# ── Roulette ──────────────────────────────────────────────────

class RouletteSpin(BaseModel):
    bet: int


@app.post("/api/roulette/spin/{telegram_id}")
async def roulette_spin(telegram_id: int, body: RouletteSpin):
    return await spin_roulette(telegram_id, body.bet)


# ── Avatars ───────────────────────────────────────────────────

@app.get("/api/avatars/{telegram_id}")
async def get_avatars(telegram_id: int):
    return await get_avatars_with_ownership(telegram_id)


class AvatarAction(BaseModel):
    avatar_id: int


@app.post("/api/avatars/buy/{telegram_id}")
async def purchase_avatar(telegram_id: int, body: AvatarAction):
    return await buy_avatar(telegram_id, body.avatar_id)


@app.post("/api/avatars/equip/{telegram_id}")
async def set_avatar(telegram_id: int, body: AvatarAction):
    return await equip_avatar(telegram_id, body.avatar_id)


@app.post("/api/avatars/equip-frame/{telegram_id}")
async def set_frame(telegram_id: int, body: AvatarAction):
    return await equip_frame(telegram_id, body.avatar_id)


@app.get("/api/admin/vpn-notify-global/{telegram_id}")
async def get_vpn_notify_global(telegram_id: int):
    await require_admin(telegram_id)
    enabled = await get_global_vpn_notify()
    return {"ok": True, "enabled": enabled}


class GlobalNotifyToggle(BaseModel):
    admin_telegram_id: int
    enabled: bool


@app.post("/api/admin/vpn-notify-global")
async def toggle_vpn_notify_global(data: GlobalNotifyToggle):
    await require_admin(data.admin_telegram_id)
    return await set_global_vpn_notify(data.enabled)


# ── Promo Codes (user) ────────────────────────────────────────

class PromoCodeActivate(BaseModel):
    code: str


@app.post("/api/promo-code/activate/{telegram_id}")
async def user_activate_promo(telegram_id: int, body: PromoCodeActivate):
    return await activate_promo_code(telegram_id, body.code)


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
            "premium_until": u.premium_until.isoformat() if u.premium_until else None,
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
            "is_premium_only": c.is_premium_only,
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
    is_premium_only: bool = False


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
        quantity=data.quantity, available_until=available_until,
        created_by=data.admin_telegram_id, is_premium_only=data.is_premium_only
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
    quantity_left: Optional[int] = None
    available_until: Optional[str] = None
    is_active: Optional[bool] = None
    is_premium_only: Optional[bool] = None


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


@app.get("/api/promotions")
async def list_promotions():
    promos = await get_active_promotions()
    return [
        {
            "id": p.id, "title": p.title, "description": p.description,
            "icon": p.icon, "promo_type": p.promo_type, "value": p.value,
            "end_at": p.end_at.isoformat(), "is_active": p.is_active
        }
        for p in promos
    ]


class PromoCreate(BaseModel):
    admin_telegram_id: int
    title: str
    description: str = ""
    icon: str = "🎉"
    promo_type: str = "click_mult"
    value: float = 2.0
    end_at: str


@app.post("/api/admin/promotions")
async def admin_add_promo(data: PromoCreate):
    await require_admin(data.admin_telegram_id)
    try:
        end_at = datetime.fromisoformat(data.end_at)
    except Exception:
        raise HTTPException(status_code=400, detail="Неверный формат даты")
    promo = await add_promotion(
        title=data.title, description=data.description, icon=data.icon,
        promo_type=data.promo_type, value=data.value, end_at=end_at
    )
    return {"ok": True, "id": promo.id}


@app.get("/api/admin/promotions/{telegram_id}")
async def admin_list_promos(telegram_id: int):
    await require_admin(telegram_id)
    promos = await get_all_promotions()
    return [
        {
            "id": p.id, "title": p.title, "description": p.description,
            "icon": p.icon, "promo_type": p.promo_type, "value": p.value,
            "end_at": p.end_at.isoformat(), "is_active": p.is_active,
            "created_at": p.created_at.isoformat()
        }
        for p in promos
    ]


class PromoAction(BaseModel):
    admin_telegram_id: int
    promo_id: int


@app.post("/api/admin/promotions/delete")
async def admin_delete_promo(data: PromoAction):
    await require_admin(data.admin_telegram_id)
    return await delete_promotion(data.promo_id)


@app.post("/api/admin/promotions/toggle")
async def admin_toggle_promo(data: PromoAction):
    await require_admin(data.admin_telegram_id)
    return await toggle_promotion(data.promo_id)


@app.get("/api/admin/logs/{telegram_id}")
async def admin_get_logs(telegram_id: int):
    await require_admin(telegram_id)
    return await get_all_logs(300)


@app.get("/api/admin/logs/user/{target_id}/{telegram_id}")
async def admin_get_user_logs(target_id: int, telegram_id: int):
    await require_admin(telegram_id)
    return await get_user_logs(target_id)


# ── Admin Achievements ────────────────────────────────────────

@app.get("/api/admin/achievements/{telegram_id}")
async def admin_list_achievements(telegram_id: int):
    await require_admin(telegram_id)
    return await admin_get_achievements()


class AchievementCreate(BaseModel):
    admin_telegram_id: int
    name: str
    description: str = ""
    icon: str = "🏆"
    condition_type: str
    condition_value: str = "0"


@app.post("/api/admin/achievements")
async def admin_create_achievement(data: AchievementCreate):
    await require_admin(data.admin_telegram_id)
    return await admin_add_achievement(
        name=data.name, description=data.description, icon=data.icon,
        condition_type=data.condition_type, condition_value=data.condition_value
    )


class AchievementEdit(BaseModel):
    admin_telegram_id: int
    achievement_id: int
    name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    condition_type: Optional[str] = None
    condition_value: Optional[str] = None
    is_active: Optional[bool] = None


@app.post("/api/admin/achievements/edit")
async def admin_edit_ach(data: AchievementEdit):
    await require_admin(data.admin_telegram_id)
    kwargs = {k: v for k, v in data.dict().items() if k not in ("admin_telegram_id", "achievement_id") and v is not None}
    return await admin_edit_achievement(data.achievement_id, **kwargs)


class AchievementDelete(BaseModel):
    admin_telegram_id: int
    achievement_id: int


@app.post("/api/admin/achievements/delete")
async def admin_delete_ach(data: AchievementDelete):
    await require_admin(data.admin_telegram_id)
    return await admin_delete_achievement(data.achievement_id)


# ── Premium Prices ────────────────────────────────────────────

@app.get("/api/settings/premium-prices")
async def get_prices():
    return await get_premium_prices()


class PremiumPriceSet(BaseModel):
    admin_telegram_id: int
    period: str
    price: int


@app.post("/api/admin/settings/premium-prices")
async def admin_set_price(data: PremiumPriceSet):
    await require_admin(data.admin_telegram_id)
    return await set_premium_price(data.admin_telegram_id, data.period, data.price)


# ── Admin: User Upgrades ──────────────────────────────────────

@app.get("/api/admin/user-upgrades/{target_telegram_id}/{admin_telegram_id}")
async def admin_list_user_upgrades(target_telegram_id: int, admin_telegram_id: int):
    await require_admin(admin_telegram_id)
    return await get_user_upgrades_admin(target_telegram_id)


class RemoveUserUpgrade(BaseModel):
    admin_telegram_id: int
    target_telegram_id: int
    user_upgrade_id: int


@app.post("/api/admin/user-upgrades/remove")
async def admin_remove_user_upgrade(data: RemoveUserUpgrade):
    await require_admin(data.admin_telegram_id)
    return await remove_user_upgrade(data.admin_telegram_id, data.target_telegram_id, data.user_upgrade_id)


# ── Admin: Promo Codes ────────────────────────────────────────

@app.get("/api/admin/promo-codes/{telegram_id}")
async def admin_list_promo_codes(telegram_id: int):
    await require_admin(telegram_id)
    return await admin_get_promo_codes(telegram_id)


class PromoCodeCreate(BaseModel):
    admin_telegram_id: int
    code: str
    name: str
    amount: float
    max_activations: int
    expires_at: Optional[str] = None


@app.post("/api/admin/promo-codes/create")
async def admin_create_promo(data: PromoCodeCreate):
    await require_admin(data.admin_telegram_id)
    expires = None
    if data.expires_at:
        try:
            expires = datetime.fromisoformat(data.expires_at)
        except Exception:
            raise HTTPException(status_code=400, detail="Неверный формат даты")
    return await admin_create_promo_code(
        data.admin_telegram_id, data.code, data.name,
        data.amount, data.max_activations, expires
    )


class PromoCodeEdit(BaseModel):
    admin_telegram_id: int
    code_id: int
    code: Optional[str] = None
    name: Optional[str] = None
    amount: Optional[float] = None
    max_activations: Optional[int] = None
    expires_at: Optional[str] = None
    is_active: Optional[bool] = None


@app.post("/api/admin/promo-codes/edit")
async def admin_edit_promo(data: PromoCodeEdit):
    await require_admin(data.admin_telegram_id)
    kwargs = {k: v for k, v in data.dict().items() if k not in ("admin_telegram_id", "code_id") and v is not None}
    if "expires_at" in kwargs:
        try:
            kwargs["expires_at"] = datetime.fromisoformat(kwargs["expires_at"])
        except Exception:
            kwargs.pop("expires_at")
    return await admin_edit_promo_code(data.admin_telegram_id, data.code_id, **kwargs)


class PromoCodeDelete(BaseModel):
    admin_telegram_id: int
    code_id: int


@app.post("/api/admin/promo-codes/delete")
async def admin_del_promo(data: PromoCodeDelete):
    await require_admin(data.admin_telegram_id)
    return await admin_delete_promo_code(data.admin_telegram_id, data.code_id)


class PromoCodeToggle(BaseModel):
    admin_telegram_id: int
    code_id: int


@app.post("/api/admin/promo-codes/toggle")
async def admin_toggle_promo_code(data: PromoCodeToggle):
    await require_admin(data.admin_telegram_id)
    return await toggle_promo_code(data.admin_telegram_id, data.code_id)


# ── API Keys ──────────────────────────────────────────

@app.get("/api/user/api-key/{telegram_id}")
async def user_get_api_key(telegram_id: int):
    return await get_or_create_api_key(telegram_id)


@app.post("/api/user/api-key/{telegram_id}/regenerate")
async def user_regenerate_api_key(telegram_id: int):
    return await regenerate_api_key(telegram_id)


# ── Public API v1 (key-authenticated) ────────────────

def _key_error():
    raise HTTPException(status_code=401, detail={"ok": False, "error": "Неверный API-ключ"})


@app.get("/api/v1/me")
async def v1_me(key: str):
    user = await get_user_by_api_key(key)
    if not user:
        _key_error()
    return {"ok": True, "user": user}


@app.get("/api/v1/balance")
async def v1_balance(key: str):
    user = await get_user_by_api_key(key)
    if not user:
        _key_error()
    return {"ok": True, "balance": user["balance"], "clicks_per_click": user["clicks_per_click"], "auto_clicks_per_second": user["auto_clicks_per_second"]}


@app.get("/api/v1/upgrades")
async def v1_upgrades(key: str):
    user = await get_user_by_api_key(key)
    if not user:
        _key_error()
    ids = await get_user_upgrade_ids(user["telegram_id"])
    all_upgrades = await get_upgrades()
    owned = [u for u in all_upgrades if u["id"] in ids]
    return {"ok": True, "upgrades": owned}


# ── News ──────────────────────────────────────────────────────

@app.get("/api/news")
async def api_get_news(limit: int = 50):
    return await get_news(limit=limit)


@app.get("/api/news/{news_id}")
async def api_get_news_item(news_id: int):
    item = await get_news_by_id(news_id)
    if not item:
        raise HTTPException(status_code=404, detail={"ok": False, "error": "Не найдено"})
    return item


@app.get("/api/admin/news/{telegram_id}")
async def api_admin_get_news(telegram_id: int):
    user = await get_user_by_telegram_id(telegram_id)
    if not user or not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Нет доступа")
    return await get_all_news_admin()


class NewsBody(BaseModel):
    admin_telegram_id: int
    title: str
    icon: Optional[str] = "📰"
    content: str


@app.post("/api/admin/news/add")
async def api_admin_add_news(data: NewsBody):
    user = await get_user_by_telegram_id(data.admin_telegram_id)
    if not user or not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Нет доступа")
    return await add_news(data.title, data.icon, data.content)


class NewsEditBody(BaseModel):
    admin_telegram_id: int
    title: Optional[str] = None
    icon: Optional[str] = None
    content: Optional[str] = None


@app.post("/api/admin/news/edit/{news_id}")
async def api_admin_edit_news(news_id: int, data: NewsEditBody):
    user = await get_user_by_telegram_id(data.admin_telegram_id)
    if not user or not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Нет доступа")
    return await edit_news(news_id, title=data.title, icon=data.icon, content=data.content)


class NewsDeleteBody(BaseModel):
    admin_telegram_id: int


@app.post("/api/admin/news/delete/{news_id}")
async def api_admin_delete_news(news_id: int, data: NewsDeleteBody):
    user = await get_user_by_telegram_id(data.admin_telegram_id)
    if not user or not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Нет доступа")
    return await delete_news(news_id)


@app.post("/api/admin/news/toggle/{news_id}")
async def api_admin_toggle_news(news_id: int, data: NewsDeleteBody):
    user = await get_user_by_telegram_id(data.admin_telegram_id)
    if not user or not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Нет доступа")
    return await toggle_news(news_id)
