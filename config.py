"""Конфигурация Telegram Weather Bot через переменные окружения."""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

BOT_TOKEN = os.getenv("WEATHER_BOT_TOKEN", "")
DB_PATH = os.getenv("WEATHER_DB_PATH", os.path.join(BASE_DIR, "weather.db"))

# 1 = демо-режим (выдуманная погода, сеть не нужна) | 0 = Open-Meteo API
DEMO_MODE = os.getenv("WEATHER_DEMO_MODE", "1") == "1"

# Бесплатный API без ключа: https://open-meteo.com/en/docs
GEOCODING_URL = os.getenv(
    "GEOCODING_URL",
    "https://geocoding-api.open-meteo.com/v1/search",
)
FORECAST_URL = os.getenv(
    "FORECAST_URL",
    "https://api.open-meteo.com/v1/forecast",
)
API_TIMEOUT = float(os.getenv("WEATHER_API_TIMEOUT", "10"))

# Час ежедневной рассылки погоды (локальное время)
DAILY_DIGEST_HOUR = int(os.getenv("DAILY_DIGEST_HOUR", "9"))

# --- Продвинутый уровень ---
# TTL кэша прогноза (секунды): Open-Meteo обновляет прогноз раз в час
CACHE_TTL_SECONDS = float(os.getenv("WEATHER_CACHE_TTL_SECONDS", "1800"))
# Минимальный интервал между сообщениями пользователя (секунды)
THROTTLE_MIN_INTERVAL = float(os.getenv("THROTTLE_MIN_INTERVAL", "0.7"))
# Город по умолчанию для пользователей без сохранённого города
DEFAULT_CITY = os.getenv("WEATHER_DEFAULT_CITY", "Москва")
