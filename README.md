# Telegram Weather Bot 🌤

Погодный бот для Telegram: текущая погода и прогноз на 7 дней, сохранение города по
умолчанию, ежедневная рассылка погоды подписчикам. Источник данных — бесплатный API
**Open-Meteo** (без ключа), геокодинг городов — их же API.

## Возможности

| Команда | Описание |
|---|---|
| `/weather [ГОРОД]` | Текущая погода (температура, ветер, влажность, эмодзи) |
| `/forecast [ГОРОД]` | Прогноз на 7 дней |
| `/city ГОРОД` | Сохранить город по умолчанию |
| `/daily on\|off` | Ежедневная рассылка погоды в 9:00 (подписка) |

## Продвинутый уровень (v2)

- **TTL-кэш прогноза** — Open-Meteo обновляет данные раз в час, кэш 30 мин
  экономит запросы (реализация на stdlib `time.monotonic`, без зависимостей);
- **Чистые функции парсинга** `_parse_current` / `_parse_forecast` в
  `weather_api.py` — покрыты unit-тестами без сети;
- **Демо-режим** — оффлайн-погода со случайным джиттером (±3°): запуск и тесты
  без интернета;
- **Middlewares** — троттлинг (анти-спам с «burst»-защитой) и логирование;
- **APScheduler cron** — ежедневная рассылка, устойчивая к ошибкам по одному
  подписчику.

## Структура

```
telegram-weather-bot/
├── bot.py            # aiogram v3: команды, рассылка, сборка Dispatcher
├── config.py         # переменные окружения (токен, TTL, час рассылки)
├── weather_api.py    # httpx-клиент Open-Meteo + чистые функции парсинга
├── db.py             # aiosqlite: сохранённые города, подписки на рассылку
├── utils.py          # TTL-кэш, retry с джиттером (stdlib)
├── middlewares.py    # троттлинг + логирование
├── tests/            # unit-тесты парсинга, кэша и БД
├── requirements.txt
├── pyproject.toml
├── Dockerfile        # docker run -e WEATHER_BOT_TOKEN=...
├── .github/workflows/ci.yml  # CI: compileall + pytest на каждый push
└── run_bot7.cmd      # запуск в Windows (читает TG_TOKEN из корневого .env)
```

## Запуск

```bash
pip install -r requirements.txt
set WEATHER_BOT_TOKEN=123456:ABC...
set WEATHER_DEMO_MODE=1      # 1 = оффлайн-демо, 0 = реальный Open-Meteo
python bot.py
```

Или в Windows — двойной клик по `run_bot7.cmd` (токен берётся из `..\.env`).

## Тесты

```bash
python -m pytest tests/ -q
```

## Docker

```bash
docker build -t telegram-weather-bot .
docker run -e WEATHER_BOT_TOKEN=... -e WEATHER_DEMO_MODE=1 telegram-weather-bot
```
