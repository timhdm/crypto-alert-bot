import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Dict, Optional

import aiohttp
import aiosqlite
from aiogram import Bot

BINANCE_PRICE_URL = "https://api.binance.com/api/v3/ticker/price"


@dataclass
class AlertRow:
    alert_id: int
    user_id: int
    symbol: str
    target_price: float
    last_price: Optional[float]
    last_notified_at: Optional[datetime]


def get_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def init_db(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                target_price REAL NOT NULL,
                last_price REAL,
                last_notified_at TEXT
            )
            """
        )
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_alert_unique ON alerts (user_id, symbol, target_price)"
        )
        await db.commit()


async def fetch_prices(session: aiohttp.ClientSession, symbols: Dict[str, None]) -> Dict[str, float]:
    prices: Dict[str, float] = {}
    for symbol in symbols:
        params = {"symbol": symbol}
        async with session.get(BINANCE_PRICE_URL, params=params, timeout=10) as response:
            response.raise_for_status()
            payload = await response.json()
            prices[symbol] = float(payload["price"])
    return prices


async def fetch_price(session: aiohttp.ClientSession, symbol: str) -> float:
    params = {"symbol": symbol}
    async with session.get(BINANCE_PRICE_URL, params=params, timeout=10) as response:
        response.raise_for_status()
        payload = await response.json()
        return float(payload["price"])


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def format_price(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".")


async def load_alerts(db_path: str) -> list[AlertRow]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, user_id, symbol, target_price, last_price, last_notified_at FROM alerts"
        )
        rows = await cursor.fetchall()
    alerts: list[AlertRow] = []
    for row in rows:
        alerts.append(
            AlertRow(
                alert_id=row["id"],
                user_id=row["user_id"],
                symbol=row["symbol"],
                target_price=row["target_price"],
                last_price=row["last_price"],
                last_notified_at=parse_iso(row["last_notified_at"]),
            )
        )
    return alerts


async def update_alert_state(
    db_path: str, alert_id: int, last_price: float, last_notified_at: Optional[datetime]
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE alerts SET last_price = ?, last_notified_at = ? WHERE id = ?",
            (last_price, last_notified_at.isoformat() if last_notified_at else None, alert_id),
        )
        await db.commit()


async def check_alerts_loop(bot: Bot, db_path: str, interval_minutes: int, cooldown_hours: int) -> None:
    cooldown = timedelta(hours=cooldown_hours)
    while True:
        try:
            alerts = await load_alerts(db_path)
            if alerts:
                symbols = {alert.symbol: None for alert in alerts}
                async with aiohttp.ClientSession() as session:
                    prices = await fetch_prices(session, symbols)
                now = utcnow()
                for alert in alerts:
                    current_price = prices.get(alert.symbol)
                    if current_price is None:
                        continue
                    crossed = False
                    if alert.last_price is not None:
                        crossed = (alert.last_price < alert.target_price <= current_price) or (
                            alert.last_price > alert.target_price >= current_price
                        )
                    should_notify = crossed
                    if should_notify and alert.last_notified_at:
                        if now - alert.last_notified_at < cooldown:
                            should_notify = False
                    if should_notify:
                        direction = "выше" if current_price >= alert.target_price else "ниже"
                        text = (
                            f"⚠️ {alert.symbol}: цена {format_price(current_price)} {direction} цели"
                            f" {format_price(alert.target_price)}"
                        )
                        await bot.send_message(alert.user_id, text)
                        await update_alert_state(db_path, alert.alert_id, current_price, now)
                    else:
                        await update_alert_state(db_path, alert.alert_id, current_price, alert.last_notified_at)
        except Exception:
            logging.exception("Failed to check alerts")
        await asyncio.sleep(interval_minutes * 60)


async def add_alert(db_path: str, user_id: int, symbol: str, target_price: float) -> bool:
    async with aiosqlite.connect(db_path) as db:
        try:
            await db.execute(
                "INSERT INTO alerts (user_id, symbol, target_price) VALUES (?, ?, ?)",
                (user_id, symbol, target_price),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def list_alerts(db_path: str, user_id: int) -> list[aiosqlite.Row]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, symbol, target_price FROM alerts WHERE user_id = ? ORDER BY id",
            (user_id,),
        )
        return await cursor.fetchall()


async def remove_alert(db_path: str, user_id: int, alert_id: int) -> bool:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "DELETE FROM alerts WHERE id = ? AND user_id = ?",
            (alert_id, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0


def parse_price(value: str) -> Optional[float]:
    try:
        price = Decimal(value)
    except InvalidOperation:
        return None
    if price <= 0:
        return None
    return float(price)
