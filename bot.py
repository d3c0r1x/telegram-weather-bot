"""Telegram Weather Bot (aiogram v3 + Open-Meteo + apscheduler).

Стек: aiogram v3 (Telegram Bot API) + httpx (Open-Meteo, бесплатно без ключа)
+ pydantic (модели погоды) + aiosqlite (города, подписки) + APScheduler
(ежедневная рассылка).

Команды:
  /weather [ГОРОД] — текущая погода
  /forecast [ГОРОД] — прогноз на 7 дней
  /city ГОРОД — сохранить город по умолчанию
  /daily on|off — ежедневная рассылка погоды (в 9:00)

Продвинутый уровень:
  - TTL-кэш прогноза + retry с джиттером (stdlib);
  - чистые функции парсинга Open-Meteo (_parse_*) — покрыты unit-тестами;
  - middlewares: троттлинг и логирование.

Запуск:  python bot.py   (задайте WEATHER_BOT_TOKEN, или start.bat).
"""
from __future__ import annotations

import asyncio
import html as _html
import logging
import os
from datetime import date

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from db import Database
from middlewares import LoggingMiddleware, ThrottlingMiddleware
from utils import TTLCache
from weather_api import Geocoder, WeatherClient, _parse_current, _parse_forecast

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(config.BASE_DIR, "bot.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

router = Router()
db = Database(config.DB_PATH)
geocoder = Geocoder()
weather = WeatherClient()
forecast_cache = TTLCache(ttl_seconds=config.CACHE_TTL_SECONDS)

# Бот создаётся в main() — нужен планировщику для рассылки
_bot: Bot | None = None
scheduler = AsyncIOScheduler()


async def _resolve_city(city_arg: str | None, user_id: int) -> tuple[str, float, float] | None:
    """Определяет город для запроса: аргумент → сохранённый → по умолчанию."""
    city = (city_arg or "").strip()
    if not city:
        user = await db.get_user(user_id)
        if user and user.get("city"):
            return user["city"], user["latitude"], user["longitude"]
        city = config.DEFAULT_CITY
    point = await geocoder.geocode(city)
    if point is None:
        return None
    return point.name, point.latitude, point.longitude


def _format_current(name: str, weather) -> str:
    desc = weather.describe()
    return (
        f"🌤 <b>Погода в {_html.escape(name)}</b>\n\n"
        f"{desc}\n"
        f"💨 Ветер: {weather.wind_speed:.0f} км/ч | 💧 Влажность: {weather.humidity:.0f}%"
    )


_WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def _day_label(date_str: str) -> str:
    """'2026-08-07' → 'Сегодня' для сегодняшнего дня, иначе 'Пт, 07.08'.

    Если дата не разбирается (демо-режим: 'day+0') — возвращаем как есть.
    """
    if date_str == date.today().isoformat():
        return "Сегодня"
    try:
        day = date.fromisoformat(date_str)
    except ValueError:
        return date_str
    return f"{_WEEKDAYS[day.weekday()]}, {day.strftime('%d.%m')}"


def _format_forecast(name: str, days) -> str:
    lines = [f"📅 <b>Прогноз для {_html.escape(name)} на {len(days)} дней</b>\n"]
    lines += [f"• {d.describe(_day_label(d.date))}" for d in days]
    return "\n".join(lines)


# ---------------------------------------------------------------- команды

@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "🌤 <b>Telegram Weather Bot</b>\n\n"
        "/weather Москва — текущая погода\n"
        "/forecast Москва — прогноз на 7 дней\n"
        "/city Москва — сохранить город по умолчанию\n"
        "/daily on — ежедневная рассылка погоды (в 9:00)\n\n"
        f"Источник: <b>{'демо-данные' if weather.demo_mode else 'Open-Meteo (бесплатный API)'}</b>"
    )


@router.message(Command("weather"))
async def cmd_weather(message: Message) -> None:
    args = message.text.split(maxsplit=1)
    city_arg = args[1] if len(args) > 1 else None
    resolved = await _resolve_city(city_arg, message.from_user.id)
    if resolved is None:
        await message.answer("Город не найден. Попробуйте иначе: /weather Москва")
        return
    name, lat, lon = resolved
    status = await message.answer(f"Загружаю погоду для <b>{_html.escape(name)}</b>…")
    try:
        cur = await forecast_cache.get_or_set(
            f"cur:{lat},{lon}", lambda: weather.current(lat, lon)
        )
    except Exception as exc:
        logger.exception("Ошибка погоды")
        await status.edit_text(f"⚠️ Не удалось получить погоду: {exc}")
        return
    await status.edit_text(_format_current(name, cur))


@router.message(Command("forecast"))
async def cmd_forecast(message: Message) -> None:
    args = message.text.split(maxsplit=1)
    city_arg = args[1] if len(args) > 1 else None
    resolved = await _resolve_city(city_arg, message.from_user.id)
    if resolved is None:
        await message.answer("Город не найден. Попробуйте иначе: /forecast Москва")
        return
    name, lat, lon = resolved
    status = await message.answer(f"Загружаю прогноз для <b>{_html.escape(name)}</b>…")
    try:
        days = await forecast_cache.get_or_set(
            f"fc:{lat},{lon}", lambda: weather.forecast(lat, lon, days=7)
        )
    except Exception as exc:
        logger.exception("Ошибка прогноза")
        await status.edit_text(f"⚠️ Не удалось получить прогноз: {exc}")
        return
    await status.edit_text(_format_forecast(name, days))


@router.message(Command("city"))
async def cmd_city(message: Message) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /city Москва")
        return
    point = await geocoder.geocode(args[1])
    if point is None:
        await message.answer(f"Город <b>{_html.escape(args[1])}</b> не найден.")
        return
    await db.set_city(
        message.from_user.id, message.from_user.username, point.name,
        point.latitude, point.longitude,
    )
    await message.answer(
        f"🏙 Город по умолчанию сохранён: <b>{_html.escape(point.name)}</b>\n"
        f"Теперь просто: /weather"
    )


@router.message(Command("daily"))
async def cmd_daily(message: Message) -> None:
    args = message.text.split()
    if len(args) < 2 or args[1].lower() not in ("on", "off"):
        await message.answer("Использование: /daily on  или  /daily off")
        return
    on = args[1].lower() == "on"
    if on:
        user = await db.get_user(message.from_user.id)
        if not (user and user.get("city")):
            await message.answer(
                "Сначала сохраните город: /city Москва — иначе нечего присылать."
            )
            return
    await db.set_digest(message.from_user.id, message.from_user.username, on)
    await message.answer(
        f"📬 Ежедневная погода <b>{'включена' if on else 'выключена'}</b> "
        f"(каждый день в {config.DAILY_DIGEST_HOUR}:00)."
    )


# ------------------------------------------------------------- ежедневная рассылка

async def _daily_job() -> None:
    """Рассылка текущей погоды подписчикам (apscheduler cron)."""
    if _bot is None:
        return
    for user in await db.digest_users():
        try:
            cur = await weather.current(user["latitude"], user["longitude"])
            await _bot.send_message(
                user["user_id"], _format_current(user["city"], cur)
            )
        except Exception:
            logger.exception("Рассылка: не удалось отправить погоду user_id=%s", user["user_id"])
            continue
        await asyncio.sleep(0.3)


async def main() -> None:
    global _bot
    if not config.BOT_TOKEN:
        raise SystemExit("Не задан WEATHER_BOT_TOKEN. Скопируйте .env.example и задайте токен.")
    _bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    dp.message.middleware(ThrottlingMiddleware(min_interval=config.THROTTLE_MIN_INTERVAL))
    dp.update.middleware(LoggingMiddleware())
    await db.init()
    scheduler.add_job(_daily_job, "cron", hour=config.DAILY_DIGEST_HOUR, minute=0)
    scheduler.start()
    logger.info(
        "Погодный бот запущен. Источник: %s",
        "демо-данные" if weather.demo_mode else "Open-Meteo",
    )
    try:
        await dp.start_polling(_bot)
    finally:
        await _bot.session.close()
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())
