import asyncio
import logging
import os

from aiogram import Bot, Dispatcher

from handlers.commands import register_commands
from services import check_alerts_loop, get_env_int, init_db


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise RuntimeError("BOT_TOKEN is required")

    db_path = os.getenv("DB_PATH", "alerts.db")
    interval_minutes = get_env_int("CHECK_INTERVAL_MINUTES", 5)
    cooldown_hours = get_env_int("NOTIFY_COOLDOWN_HOURS", 24)

    await init_db(db_path)

    bot = Bot(token=bot_token)
    dp = Dispatcher()

    register_commands(dp, db_path)

    async def on_startup() -> None:
        asyncio.create_task(check_alerts_loop(bot, db_path, interval_minutes, cooldown_hours))

    await on_startup()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
