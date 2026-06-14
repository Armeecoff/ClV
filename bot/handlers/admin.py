from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from database.db import (
    get_all_users, get_all_vpn_configs, adjust_balance,
    add_vpn_config, toggle_vpn_active, set_admin, get_user_by_telegram_id
)
from database.models import VPNConfig
from config import ADMIN_IDS
from datetime import datetime

router = Router()


def is_admin(telegram_id: int) -> bool:
    return telegram_id in ADMIN_IDS


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        user = await get_user_by_telegram_id(message.from_user.id)
        if not user or not user.is_admin:
            await message.answer("❌ У вас нет доступа к админ-панели.")
            return

    text = (
        "🛠 <b>Админ-панель</b>\n\n"
        "Доступные команды:\n\n"
        "/users — список всех пользователей\n"
        "/addbalance [tg_id] [сумма] — пополнить баланс\n"
        "/removebalance [tg_id] [сумма] — снять баланс\n"
        "/addvpn — добавить VPN конфиг (пошагово)\n"
        "/vpnlist — список всех VPN конфигов\n"
        "/togglevpn [id] — включить/выключить VPN конфиг\n"
        "/setadmin [tg_id] — выдать права админа\n"
        "/removeadmin [tg_id] — снять права админа\n"
    )
    await message.answer(text, parse_mode="HTML")


@router.message(Command("users"))
async def cmd_users(message: Message):
    if not is_admin(message.from_user.id):
        user = await get_user_by_telegram_id(message.from_user.id)
        if not user or not user.is_admin:
            return

    users = await get_all_users()
    if not users:
        await message.answer("Нет пользователей.")
        return

    lines = ["👥 <b>Все пользователи:</b>\n"]
    for u in users[:30]:
        name = u.first_name or u.username or "Без имени"
        admin_mark = " 👑" if u.is_admin else ""
        lines.append(
            f"• <b>{name}</b>{admin_mark}\n"
            f"  ID: <code>{u.telegram_id}</code>\n"
            f"  Баланс: {int(u.balance)} | Кликов: {u.total_clicks}"
        )

    if len(users) > 30:
        lines.append(f"\n... и ещё {len(users) - 30} пользователей")

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("addbalance"))
async def cmd_add_balance(message: Message):
    if not is_admin(message.from_user.id):
        user = await get_user_by_telegram_id(message.from_user.id)
        if not user or not user.is_admin:
            return

    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("Использование: /addbalance [tg_id] [сумма]")
        return
    try:
        tg_id = int(parts[1])
        amount = float(parts[2])
    except ValueError:
        await message.answer("❌ Неверный формат. Пример: /addbalance 123456789 500")
        return

    result = await adjust_balance(tg_id, amount)
    if result["ok"]:
        await message.answer(f"✅ Баланс пополнен. Новый баланс: <b>{int(result['new_balance'])}</b> кликов", parse_mode="HTML")
    else:
        await message.answer(f"❌ Ошибка: {result['error']}")


@router.message(Command("removebalance"))
async def cmd_remove_balance(message: Message):
    if not is_admin(message.from_user.id):
        user = await get_user_by_telegram_id(message.from_user.id)
        if not user or not user.is_admin:
            return

    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("Использование: /removebalance [tg_id] [сумма]")
        return
    try:
        tg_id = int(parts[1])
        amount = float(parts[2])
    except ValueError:
        await message.answer("❌ Неверный формат. Пример: /removebalance 123456789 500")
        return

    result = await adjust_balance(tg_id, -amount)
    if result["ok"]:
        await message.answer(f"✅ Баланс изменён. Новый баланс: <b>{int(result['new_balance'])}</b> кликов", parse_mode="HTML")
    else:
        await message.answer(f"❌ Ошибка: {result['error']}")


@router.message(Command("vpnlist"))
async def cmd_vpn_list(message: Message):
    if not is_admin(message.from_user.id):
        user = await get_user_by_telegram_id(message.from_user.id)
        if not user or not user.is_admin:
            return

    configs = await get_all_vpn_configs()
    if not configs:
        await message.answer("VPN конфигов нет. Добавьте через /addvpn")
        return

    lines = ["📋 <b>Все VPN конфиги:</b>\n"]
    for c in configs:
        status = "✅" if c.is_active else "❌"
        until = c.available_until.strftime("%d.%m.%Y") if c.available_until else "Бессрочно"
        lines.append(
            f"{status} <b>[{c.id}] {c.name}</b>\n"
            f"  💰 Цена: {int(c.price_clicks)} кликов | ⏳ {c.duration_days} дн.\n"
            f"  📦 В наличии: {c.quantity_left}/{c.quantity} | До: {until}"
        )

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("togglevpn"))
async def cmd_toggle_vpn(message: Message):
    if not is_admin(message.from_user.id):
        user = await get_user_by_telegram_id(message.from_user.id)
        if not user or not user.is_admin:
            return

    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Использование: /togglevpn [id]")
        return
    try:
        vpn_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Неверный ID")
        return

    result = await toggle_vpn_active(vpn_id)
    if result["ok"]:
        status = "включён ✅" if result["is_active"] else "отключён ❌"
        await message.answer(f"VPN конфиг [{vpn_id}] {status}")
    else:
        await message.answer(f"❌ {result['error']}")


@router.message(Command("setadmin"))
async def cmd_set_admin(message: Message):
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Использование: /setadmin [tg_id]")
        return
    try:
        tg_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Неверный ID")
        return

    result = await set_admin(tg_id, True)
    if result["ok"]:
        await message.answer(f"✅ Пользователю {tg_id} выданы права администратора")
    else:
        await message.answer(f"❌ {result['error']}")


@router.message(Command("removeadmin"))
async def cmd_remove_admin(message: Message):
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Использование: /removeadmin [tg_id]")
        return
    try:
        tg_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Неверный ID")
        return

    result = await set_admin(tg_id, False)
    if result["ok"]:
        await message.answer(f"✅ Права администратора сняты с пользователя {tg_id}")
    else:
        await message.answer(f"❌ {result['error']}")


# Пошаговое добавление VPN конфига
add_vpn_states = {}


@router.message(Command("addvpn"))
async def cmd_add_vpn_start(message: Message):
    if not is_admin(message.from_user.id):
        user = await get_user_by_telegram_id(message.from_user.id)
        if not user or not user.is_admin:
            return

    add_vpn_states[message.from_user.id] = {"step": "name"}
    await message.answer(
        "➕ <b>Добавление VPN конфига</b>\n\n"
        "Шаг 1/6: Введите <b>название</b> конфига:",
        parse_mode="HTML"
    )


@router.message(F.text)
async def handle_add_vpn_steps(message: Message):
    uid = message.from_user.id
    if uid not in add_vpn_states:
        return

    state = add_vpn_states[uid]
    step = state.get("step")

    if step == "name":
        state["name"] = message.text
        state["step"] = "description"
        await message.answer("Шаг 2/6: Введите <b>описание</b>:", parse_mode="HTML")

    elif step == "description":
        state["description"] = message.text
        state["step"] = "config_data"
        await message.answer("Шаг 3/6: Вставьте <b>конфиг VPN</b> (текст/ключ):", parse_mode="HTML")

    elif step == "config_data":
        state["config_data"] = message.text
        state["step"] = "price"
        await message.answer("Шаг 4/6: Укажите <b>цену в кликах</b> (число):", parse_mode="HTML")

    elif step == "price":
        try:
            state["price_clicks"] = float(message.text)
        except ValueError:
            await message.answer("❌ Введите число!")
            return
        state["step"] = "duration"
        await message.answer("Шаг 5/6: Укажите <b>срок действия в днях</b> (число):", parse_mode="HTML")

    elif step == "duration":
        try:
            state["duration_days"] = int(message.text)
        except ValueError:
            await message.answer("❌ Введите целое число!")
            return
        state["step"] = "quantity"
        await message.answer("Шаг 6/6: Укажите <b>количество в наличии</b> (число):", parse_mode="HTML")

    elif step == "quantity":
        try:
            state["quantity"] = int(message.text)
        except ValueError:
            await message.answer("❌ Введите целое число!")
            return
        state["step"] = "available_until"
        await message.answer(
            "Последний шаг: Укажите <b>дату окончания продажи</b> в формате ДД.ММ.ГГГГ\n"
            "или напишите <code>нет</code> для бессрочной продажи:",
            parse_mode="HTML"
        )

    elif step == "available_until":
        available_until = None
        if message.text.lower() not in ("нет", "no", "-"):
            try:
                available_until = datetime.strptime(message.text.strip(), "%d.%m.%Y")
            except ValueError:
                await message.answer("❌ Формат даты: ДД.ММ.ГГГГ или 'нет'")
                return

        vpn = await add_vpn_config(
            name=state["name"],
            description=state["description"],
            config_data=state["config_data"],
            price_clicks=state["price_clicks"],
            duration_days=state["duration_days"],
            quantity=state["quantity"],
            available_until=available_until,
            created_by=uid
        )
        del add_vpn_states[uid]
        until_str = available_until.strftime("%d.%m.%Y") if available_until else "Бессрочно"
        await message.answer(
            f"✅ <b>VPN конфиг добавлен!</b>\n\n"
            f"ID: {vpn.id}\n"
            f"Название: {vpn.name}\n"
            f"Цена: {int(vpn.price_clicks)} кликов\n"
            f"Срок: {vpn.duration_days} дней\n"
            f"Кол-во: {vpn.quantity}\n"
            f"До: {until_str}",
            parse_mode="HTML"
        )
