"""SQLite-БД (aiosqlite): сохранённые города пользователей и подписки
на ежедневную рассылку погоды."""
from __future__ import annotations

import aiosqlite


class Database:
    def __init__(self, path: str) -> None:
        self.path = path

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id      INTEGER PRIMARY KEY,
                    username     TEXT,
                    city         TEXT,
                    latitude     REAL,
                    longitude    REAL,
                    daily_digest INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            await db.commit()

    async def set_city(
        self, user_id: int, username: str | None, city: str, lat: float, lon: float
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO users (user_id, username, city, latitude, longitude, daily_digest)
                VALUES (?, ?, ?, ?, ?, 0)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    city = excluded.city,
                    latitude = excluded.latitude,
                    longitude = excluded.longitude
                """,
                (user_id, username or "", city, lat, lon),
            )
            await db.commit()

    async def get_user(self, user_id: int) -> dict | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            )
            row = await cur.fetchone()
        return dict(row) if row else None

    async def set_digest(self, user_id: int, username: str | None, on: bool) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO users (user_id, username, daily_digest)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    daily_digest = excluded.daily_digest
                """,
                (user_id, username or "", 1 if on else 0),
            )
            await db.commit()

    async def digest_users(self) -> list[dict]:
        """Пользователи с включённой рассылкой и сохранённым городом."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM users WHERE daily_digest = 1 AND city IS NOT NULL"
            )
            rows = await cur.fetchall()
        return [dict(r) for r in rows]
