from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.filters import CommandStart
from database.db import get_or_create_user
from config import WEBAPP_URL

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    user = await get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name
    )

    name = message.from_user.first_name or "пользователь"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🎮 Открыть мини-апп",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )]
    ])

    await message.answer(
        f"👋 Привет, <b>{name}</b>!\n\n"
        f"💰 Твой баланс: <b>{int(user.balance)}</b> кликов\n"
        f"🖱 Кликов за раз: <b>{user.clicks_per_click}</b>\n\n"
        f"Нажми кнопку ниже, чтобы открыть мини-апп и начать кликать!",
        parse_mode="HTML",
        reply_markup=keyboard
    )
