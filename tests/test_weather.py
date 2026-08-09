"""Unit-тесты Weather Bot: парсинг Open-Meteo, WMO, демо-режим, БД."""
import asyncio

import httpx

from db import Database
from weather_api import (
    Geocoder,
    WeatherClient,
    _parse_current,
    _parse_forecast,
    _parse_geocode,
    wmo,
)

GEO_PAYLOAD = {
    "results": [
        {"name": "Москва", "latitude": 55.75, "longitude": 37.62, "country": "Россия"}
    ]
}

FORECAST_PAYLOAD = {
    "current": {
        "time": "2026-08-07T12:00",
        "temperature_2m": 21.3,
        "relative_humidity_2m": 64.0,
        "wind_speed_10m": 7.5,
        "weather_code": 3,
    },
    "daily": {
        "time": ["2026-08-07", "2026-08-08"],
        "weather_code": [3, 61],
        "temperature_2m_max": [24.1, 19.4],
        "temperature_2m_min": [15.2, 12.0],
        "precipitation_probability_max": [10, 80],
    },
}


class FakeTransport(httpx.AsyncBaseTransport):
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    async def handle_async_request(self, request):
        return httpx.Response(200, json=self.payload, request=request)


def test_day_label() -> None:
    from datetime import date

    from bot import _day_label

    assert _day_label(date.today().isoformat()) == "Сегодня"
    assert _day_label("2026-08-07") == "Пт, 07.08"   # 7 августа 2026 — пятница
    assert _day_label("2026-08-08") == "Сб, 08.08"
    assert _day_label("day+0") == "day+0"           # демо-режим — как есть
    assert _day_label("мусор") == "мусор"


def test_wmo_map() -> None:
    assert wmo(0) == ("Ясно", "☀️")
    assert wmo(95) == ("Гроза", "⛈")
    assert wmo(999)[0] == "Неизвестно"  # неизвестный код не падает


def test_parse_geocode() -> None:
    point = _parse_geocode(GEO_PAYLOAD)
    assert point is not None
    assert point.name == "Москва"
    assert point.latitude == 55.75
    assert point.longitude == 37.62
    assert _parse_geocode({"results": []}) is None
    assert _parse_geocode({}) is None


def test_parse_current() -> None:
    cur = _parse_current(FORECAST_PAYLOAD)
    assert cur.temperature == 21.3
    assert cur.humidity == 64.0
    assert cur.wind_speed == 7.5
    assert cur.code == 3
    assert "Пасмурно" in cur.describe()


def test_parse_forecast() -> None:
    days = _parse_forecast(FORECAST_PAYLOAD)
    assert len(days) == 2
    assert days[0].date == "2026-08-07"
    assert days[0].t_max == 24.1
    assert days[1].precip_prob == 80.0
    assert "2026-08-08" in days[1].describe()


def test_demo_mode_geocoder_and_weather() -> None:
    async def run() -> None:
        point = await Geocoder(demo_mode=True).geocode("казань")
        assert point is not None and point.name == "Казань"
        client = WeatherClient(demo_mode=True)
        cur = await client.current(55.0, 49.0)
        assert -40 <= cur.temperature <= 40
        days = await client.forecast(55.0, 49.0, days=7)
        assert len(days) == 7

    asyncio.run(run())


def test_real_client_with_fake_transport() -> None:
    """Реальный клиент с подменой транспорта (без сети) парсит ответ Open-Meteo."""
    async def run() -> None:
        client = WeatherClient(demo_mode=False, transport=FakeTransport(FORECAST_PAYLOAD))
        cur = await client.current(55.75, 37.62)
        assert cur.temperature == 21.3
        days = await client.forecast(55.75, 37.62, days=2)
        assert len(days) == 2

    asyncio.run(run())


def test_db_city_and_digest(tmp_path) -> None:
    async def run() -> None:
        db = Database(str(tmp_path / "weather.db"))
        await db.init()
        await db.set_city(1, "alice", "Москва", 55.75, 37.62)
        user = await db.get_user(1)
        assert user["city"] == "Москва" and user["daily_digest"] == 0
        assert await db.get_user(999) is None

        await db.set_digest(1, "alice", True)
        await db.set_digest(2, "bob", True)  # без города — не попадёт в рассылку
        digest = await db.digest_users()
        assert [u["user_id"] for u in digest] == [1]

    asyncio.run(run())
