@echo off
rem Launch script for Telegram Weather Bot (Project 7).
rem Reads TG_TOKEN from the root .env, sets WEATHER_BOT_TOKEN, runs the bot.
cd /d "%~dp0"

for /f "usebackq tokens=1,* delims==" %%a in ("..\.env") do (
    if "%%a"=="TG_TOKEN" set "WEATHER_BOT_TOKEN=%%b"
)
if not defined WEATHER_BOT_TOKEN (
    echo [ERROR] TG_TOKEN not found in ..\.env
    pause
    exit /b 1
)

rem 0 = real Open-Meteo API | 1 = demo mode (offline)
set "WEATHER_DEMO_MODE=1"
set "PYTHONIOENCODING=utf-8"

..\.venv\Scripts\python.exe -u bot.py
