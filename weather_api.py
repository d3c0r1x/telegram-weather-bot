"""Погода через Open-Meteo (бесплатный API без ключа) + демо-режим.

Источники (официальная документация: https://open-meteo.com/en/docs):
  - Геокодинг: /v1/search?name=Москва&count=1&language=ru
  - Прогноз:   /v1/forecast?latitude=..&longitude=..&current=..&daily=..

Парсинг ответов вынесен в чистые функции (_parse_*) — их легко покрыть
unit-тестами без сети. Демо-режим (WEATHER_DEMO_MODE=1) отдаёт выдуманные
данные, чтобы бот работал без интернета.
"""
from __future__ import annotations

import random
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel

import config
from utils import async_retry

# Коды погоды WMO → (описание, эмодзи). Полная таблица: https://open-meteo.com/en/docs
WMO_CODES: dict[int, tuple[str, str]] = {
    0: ("Ясно", "☀️"), 1: ("Преимущественно ясно", "🌤"), 2: ("Переменная облачность", "⛅"),
    3: ("Пасмурно", "☁️"), 45: ("Туман", "🌫"), 48: ("Изморозь", "🌫"),
    51: ("Мелкая морось", "🌦"), 53: ("Морось", "🌦"), 55: ("Сильная морось", "🌧"),
    61: ("Небольшой дождь", "🌦"), 63: ("Дождь", "🌧"), 65: ("Сильный дождь", "🌧"),
    66: ("Ледяной дождь", "🌧"), 67: ("Сильный ледяной дождь", "🌧"),
    71: ("Небольшой снег", "🌨"), 73: ("Снег", "🌨"), 75: ("Сильный снег", "❄️"),
    77: ("Снежная крупа", "🌨"), 80: ("Ливень", "🌧"), 81: ("Ливень", "🌧"),
    82: ("Сильный ливень", "⛈"), 85: ("Снегопад", "🌨"), 86: ("Сильный снегопад", "❄️"),
    95: ("Гроза", "⛈"), 96: ("Гроза с градом", "⛈"), 99: ("Гроза с сильным градом", "⛈"),
}


def wmo(code: int) -> tuple[str, str]:
    """(описание, эмодзи) по коду погоды WMO."""
    return WMO_CODES.get(int(code), ("Неизвестно", "🌡"))


class GeoPoint(BaseModel):
    name: str
    latitude: float
    longitude: float
    country: str = ""


class CurrentWeather(BaseModel):
    time: str = ""
    temperature: float
    wind_speed: float = 0.0
    humidity: float = 0.0
    code: int = 0
    sunrise: str = ""
    sunset: str = ""

    def describe(self) -> str:
        desc, emoji = wmo(self.code)
        sun = ""
        if self.sunrise and self.sunset:
            sun = f"\n🌅 {self.sunrise} · 🌇 {self.sunset}"
        return f"{emoji} {desc}, {self.temperature:.0f}°C{sun}"


class DayForecast(BaseModel):
    date: str
    code: int = 0
    t_max: float
    t_min: float
    precip_prob: float = 0.0

    def describe(self, label: str | None = None) -> str:
        desc, emoji = wmo(self.code)
        prefix = label or self.date
        return (
            f"{prefix}: {emoji} {desc}, "
            f"{self.t_min:.0f}…{self.t_max:.0f}°C, осадки {self.precip_prob:.0f}%"
        )


def _parse_geocode(payload: dict) -> GeoPoint | None:
    """Разбирает ответ геокодинга Open-Meteo → GeoPoint."""
    results = payload.get("results") or []
    if not results:
        return None
    first = results[0]
    return GeoPoint(
        name=str(first.get("name") or "?"),
        latitude=float(first["latitude"]),
        longitude=float(first["longitude"]),
        country=str(first.get("country") or ""),
    )


def _parse_current(payload: dict) -> CurrentWeather:
    """Разбирает секции current и daily (sunrise/sunset) ответа /v1/forecast."""
    cur = payload.get("current") or {}
    daily = payload.get("daily") or {}
    sunrises = daily.get("sunrise") or []
    sunsets = daily.get("sunset") or []
    return CurrentWeather(
        time=str(cur.get("time") or ""),
        temperature=float(cur.get("temperature_2m") or 0),
        wind_speed=float(cur.get("wind_speed_10m") or 0),
        humidity=float(cur.get("relative_humidity_2m") or 0),
        code=int(cur.get("weather_code") or 0),
        sunrise=str(sunrises[0])[-5:] if sunrises else "",
        sunset=str(sunsets[0])[-5:] if sunsets else "",
    )


def _parse_forecast(payload: dict) -> list[DayForecast]:
    """Разбирает секцию daily ответа /v1/forecast → список дней."""
    daily = payload.get("daily") or {}
    times = daily.get("time") or []
    codes = daily.get("weather_code") or []
    t_max = daily.get("temperature_2m_max") or []
    t_min = daily.get("temperature_2m_min") or []
    precip = daily.get("precipitation_probability_max") or []
    days = []
    for i, day in enumerate(times):
        days.append(
            DayForecast(
                date=str(day),
                code=int(codes[i]) if i < len(codes) else 0,
                t_max=float(t_max[i]) if i < len(t_max) else 0.0,
                t_min=float(t_min[i]) if i < len(t_min) else 0.0,
                precip_prob=float(precip[i]) if i < len(precip) else 0.0,
            )
        )
    return days


class Geocoder:
    """Поиск координат города по названию (Open-Meteo geocoding)."""

    def __init__(
        self,
        *,
        demo_mode: bool | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.demo_mode = config.DEMO_MODE if demo_mode is None else demo_mode
        self._transport = transport

    async def geocode(self, city: str) -> GeoPoint | None:
        if self.demo_mode:
            return GeoPoint(name=city.strip().title(), latitude=55.75, longitude=37.62)
        params = {"name": city, "count": 1, "language": "ru", "format": "json"}
        async with httpx.AsyncClient(timeout=config.API_TIMEOUT, transport=self._transport) as client:
            resp = await client.get(config.GEOCODING_URL, params=params)
            resp.raise_for_status()
            payload = resp.json()
        return _parse_geocode(payload)


class WeatherClient:
    """Текущая погода и прогноз (Open-Meteo forecast)."""

    def __init__(
        self,
        *,
        demo_mode: bool | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.demo_mode = config.DEMO_MODE if demo_mode is None else demo_mode
        self._transport = transport

    async def current(self, lat: float, lon: float) -> CurrentWeather:
        if self.demo_mode:
            return CurrentWeather(
                time="now",
                temperature=round(random.uniform(-5, 30), 1),
                wind_speed=round(random.uniform(0, 15), 1),
                humidity=round(random.uniform(30, 95)),
                code=random.choice(list(WMO_CODES)),
            )
        payload = await self._fetch(lat, lon)
        return _parse_current(payload)

    async def forecast(self, lat: float, lon: float, days: int = 7) -> list[DayForecast]:
        if self.demo_mode:
            result = []
            for offset in range(days):
                result.append(
                    DayForecast(
                        date=f"day+{offset}",
                        code=random.choice(list(WMO_CODES)),
                        t_min=round(random.uniform(-5, 15), 1),
                        t_max=round(random.uniform(10, 35), 1),
                        precip_prob=round(random.uniform(0, 90)),
                    )
                )
            return result
        payload = await self._fetch(lat, lon, days=days)
        return _parse_forecast(payload)

    @async_retry(retries=3, retry_on=(httpx.HTTPError,))
    async def _fetch(self, lat: float, lon: float, days: int = 1) -> dict:
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
            "timezone": "auto",
            "forecast_days": days,
        }
        async with httpx.AsyncClient(timeout=config.API_TIMEOUT, transport=self._transport) as client:
            resp = await client.get(config.FORECAST_URL, params=params)
            resp.raise_for_status()
            return resp.json()
