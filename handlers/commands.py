import logging

import aiohttp
from aiogram import Dispatcher
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.types import Message

from services import (
    add_alert,
    fetch_price,
    format_price,
    list_alerts,
    parse_price,
    remove_alert,
)


def register_commands(dp: Dispatcher, db_path: str) -> None:
    @dp.message(Command("start"))
    async def handle_start(message: Message) -> None:
        await message.answer(
            "Привет!\n"
            "Курс: /now или /now BTCUSDT\n"
            "Добавь алерт: /add BTCUSDT 10000\n"
            "Список: /list\n"
            "Удалить: /remove <id>"
        )

    @dp.message(Command("now"))
    async def handle_now(message: Message, command: CommandObject) -> None:
        symbol = "BTCUSDT"
        if command.args:
            symbol = command.args.split()[0].upper()
        if not symbol.isalnum():
            await message.answer("Некорректный символ. Пример: /now BTCUSDT")
            return
        async with aiohttp.ClientSession() as session:
            try:
                price = await fetch_price(session, symbol)
            except aiohttp.ClientResponseError:
                await message.answer("Не удалось получить цену. Проверьте символ.")
                return
            except Exception:
                logging.exception("Failed to fetch price for %s", symbol)
                await message.answer("Не удалось получить цену. Попробуйте позже.")
                return
        await message.answer(f"{symbol}: {format_price(price)}")

    @dp.message(Command("add"))
    async def handle_add(message: Message, command: CommandObject) -> None:
        if not command.args:
            await message.answer("Формат: /add BTCUSDT 10000")
            return
        parts = command.args.split()
        if len(parts) != 2:
            await message.answer("Формат: /add BTCUSDT 10000")
            return
        symbol = parts[0].upper()
        if not symbol.isalnum():
            await message.answer("Некорректный символ. Пример: BTCUSDT")
            return
        price = parse_price(parts[1])
        if price is None:
            await message.answer("Некорректная цена. Пример: /add BTCUSDT 10000")
            return
        created = await add_alert(db_path, message.from_user.id, symbol, price)
        if created:
            await message.answer(f"Алерт добавлен: {symbol} = {format_price(price)}")
        else:
            await message.answer("Такой алерт уже существует")

    @dp.message(Command("list"))
    async def handle_list(message: Message) -> None:
        rows = await list_alerts(db_path, message.from_user.id)
        if not rows:
            await message.answer("Алерты не найдены")
            return
        lines = ["Ваши алерты:"]
        for row in rows:
            lines.append(f"#{row['id']} {row['symbol']} = {format_price(row['target_price'])}")
        await message.answer("\n".join(lines))

    @dp.message(Command("remove"))
    async def handle_remove(message: Message, command: CommandObject) -> None:
        if not command.args or not command.args.isdigit():
            await message.answer("Формат: /remove <id>")
            return
        alert_id = int(command.args)
        removed = await remove_alert(db_path, message.from_user.id, alert_id)
        if removed:
            await message.answer("Алерт удален")
        else:
            await message.answer("Алерт не найден")
