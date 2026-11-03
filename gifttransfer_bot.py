"""
GiftTransfer — безопасный прототип Telegram-бота.

Возможности:
- /start в личном чате;
- выдача закрытого доступа по секретному коду;
- создание офферов через inline mode только для пользователей с доступом;
- кнопки «Принять» / «Отклонить»;
- предупреждение при принятии;
- просмотр инструкции и кнопка «Назад».

ВАЖНО:
Этот прототип НЕ хранит и не переводит деньги/NFT, не является эскроу
и не умеет достоверно подтверждать передачу NFT. Кнопка проверки всегда
сообщает, что автоматическая проверка не подключена. Не обещайте выплату,
заморозку средств или успешную сделку без реальной проверенной интеграции.
"""

import asyncio
import html
import os
import re
import sqlite3
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.types import (
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    Message,
)
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ACCESS_CODE = os.getenv("ACCESS_CODE", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "").lstrip("@")
DB_PATH = os.getenv("DB_PATH", "gifttransfer.sqlite3")

if not BOT_TOKEN or not ACCESS_CODE:
    raise RuntimeError("Укажите переменные окружения BOT_TOKEN и ACCESS_CODE")

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

db = sqlite3.connect(DB_PATH)
db.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    has_access INTEGER NOT NULL DEFAULT 0
)
""")
db.commit()


def has_access(user_id: int) -> bool:
    row = db.execute(
        "SELECT has_access FROM users WHERE user_id = ?", (user_id,)
    ).fetchone()
    return bool(row and row[0])


def grant_access(user_id: int) -> None:
    db.execute(
        """INSERT INTO users(user_id, has_access) VALUES(?, 1)
           ON CONFLICT(user_id) DO UPDATE SET has_access = 1""",
        (user_id,),
    )
    db.commit()


def valid_gift_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return (
            parsed.scheme == "https"
            and parsed.netloc.lower() in {"t.me", "telegram.me"}
            and bool(parsed.path)
        )
    except Exception:
        return False


def main_menu_text() -> str:
    return (
        "📦 <b>GiftTransfer — предложения по подаркам и ⭐</b>\n\n"
        "Создавайте предложения и согласовывайте условия сделки "
        "непосредственно в Telegram.\n\n"
        "🛡 <b>Важно:</b> бот не принимает и не хранит NFT или деньги. "
        "Перед любой передачей самостоятельно проверяйте получателя "
        "и условия сделки в официальном интерфейсе Telegram.\n\n"
        "🎁 <b>Как это работает:</b>\n"
        "1. Пользователь с доступом создаёт предложение через inline-режим.\n"
        "2. Получатель выбирает «Принять» или «Отклонить».\n"
        "3. Стороны самостоятельно проверяют детали и выполняют передачу "
        "только если доверяют друг другу.\n\n"
        "Автоматическая проверка передачи и расчёты в этом прототипе "
        "не подключены."
    )


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(main_menu_text())


@dp.message(F.text)
async def receive_access_code(message: Message):
    if message.chat.type != "private":
        return
    if message.text.strip() == ACCESS_CODE:
        grant_access(message.from_user.id)
        await message.answer(
            "✅ <b>Доступ к созданию предложений выдан.</b>\n\n"
            "Используйте inline-режим:\n"
            f"<code>@{html.escape(BOT_USERNAME or 'имя_бота')} "
            "[ссылка] [сумма] [валюта] [язык]</code>\n\n"
            "Языки: ru, en, zh\n"
            "Валюты: stars, gram, rub"
        )


def parse_inline_query(query: str):
    parts = query.strip().split()
    if len(parts) != 4:
        return None
    gift_url, amount, currency, language = parts

    if not valid_gift_url(gift_url):
        return None
    if not re.fullmatch(r"\d+(?:[.,]\d{1,2})?", amount):
        return None
    if currency not in {"stars", "gram", "rub"}:
        return None
    if language not in {"ru", "en", "zh"}:
        return None

    return gift_url, amount.replace(",", "."), currency, language


def offer_text(gift_url: str, amount: str, currency: str) -> str:
    currency_names = {
        "stars": "Telegram Stars",
        "gram": "TON",
        "rub": "RUB",
    }
    return (
        "🎁 <b>Предложение по подарку</b>\n\n"
        f"Подарок: <a href=\"{html.escape(gift_url, quote=True)}\">открыть ссылку</a>\n"
        f"Сумма предложения: <b>{html.escape(amount)} "
        f"{currency_names[currency]}</b>\n\n"
        "Пожалуйста, самостоятельно проверьте ссылку, сумму и условия "
        "до любых действий."
    )


@dp.inline_query()
async def inline_offer(inline_query: InlineQuery):
    # Для пользователей без доступа возвращаем пустой список:
    # функция создания оффера для них не отображается.
    if not has_access(inline_query.from_user.id):
        await inline_query.answer([], cache_time=0, is_personal=True)
        return

    parsed = parse_inline_query(inline_query.query)
    if not parsed:
        await inline_query.answer([], cache_time=0, is_personal=True)
        return

    gift_url, amount, currency, language = parsed
    text = offer_text(gift_url, amount, currency)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ Отклонить", callback_data="offer:decline"),
        InlineKeyboardButton(text="✅ Принять", callback_data="offer:accept"),
    ]])

    result = InlineQueryResultArticle(
        id="gift-offer",
        title="🎁 Создать предложение",
        description=f"{amount} {currency} — отправить предложение в чат",
        input_message_content=InputTextMessageContent(
            message_text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        ),
        reply_markup=keyboard,
    )
    await inline_query.answer([result], cache_time=0, is_personal=True)


def accepted_text() -> str:
    return (
        "🎁 <b>Предложение принято.</b>\n\n"
        "Стороны согласовали предложение. Перед выполнением передачи "
        "обязательно сверьте подарок, сумму и получателя.\n\n"
        "<i>Это сообщение не подтверждает оплату или резервирование NFT.</i>"
    )


def accepted_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Как проверить сделку?", callback_data="offer:how")],
        [InlineKeyboardButton(text="Проверить передачу", callback_data="offer:verify")],
    ])


def instructions_text() -> str:
    return (
        "🎁 <b>Проверка сделки</b>\n\n"
        "1. Откройте подарок в официальном интерфейсе Telegram.\n"
        "2. Внимательно проверьте аккаунт получателя и условия передачи.\n"
        "3. Не передавайте подарок, если данные не совпадают или вы "
        "не уверены в контрагенте.\n"
        "4. Не сообщайте никому коды входа, пароли или данные аккаунта.\n\n"
        "<b>Автоматическое завершение сделки</b>\n"
        "Автоматическая проверка передачи и зачисление средств здесь "
        "не реализованы. Подтверждайте расчёт отдельно и только после "
        "проверки фактического получения подарка."
    )


@dp.callback_query(F.data == "offer:decline")
async def decline_offer(callback: CallbackQuery):
    if callback.inline_message_id:
        await bot.edit_message_text(
            inline_message_id=callback.inline_message_id,
            text="❌ <b>Предложение отклонено.</b>",
            reply_markup=None,
        )
    await callback.answer("Предложение отклонено.")


@dp.callback_query(F.data == "offer:accept")
async def accept_offer(callback: CallbackQuery):
    # Всплывающее окно Telegram с кнопкой OK.
    await callback.answer(
        "⚠️ ВНИМАНИЕ\n"
        "Ни в коем случае не передавайте NFT напрямую незнакомым лицам!\n"
        "Проверяйте получателя и условия сделки в Telegram.",
        show_alert=True,
    )
    if callback.inline_message_id:
        await bot.edit_message_text(
            inline_message_id=callback.inline_message_id,
            text=accepted_text(),
            reply_markup=accepted_keyboard(),
        )


@dp.callback_query(F.data == "offer:how")
async def show_instructions(callback: CallbackQuery):
    if callback.inline_message_id:
        await bot.edit_message_text(
            inline_message_id=callback.inline_message_id,
            text=instructions_text(),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="← Назад", callback_data="offer:back")
            ]]),
        )
    await callback.answer()


@dp.callback_query(F.data == "offer:back")
async def back_to_accepted(callback: CallbackQuery):
    if callback.inline_message_id:
        await bot.edit_message_text(
            inline_message_id=callback.inline_message_id,
            text=accepted_text(),
            reply_markup=accepted_keyboard(),
        )
    await callback.answer()


@dp.callback_query(F.data == "offer:verify")
async def verify_transfer(callback: CallbackQuery):
    await callback.answer(
        "Автоматическая проверка передачи не подключена. "
        "Бот не может подтвердить получение NFT.",
        show_alert=True,
    )


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
