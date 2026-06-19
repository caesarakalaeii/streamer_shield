"""One-shot migration of the legacy JSON state into Postgres.

Run once after deploying the DB-backed bot, so the existing whitelist / blacklist /
joinable channels aren't lost. Idempotent (uses upserts). Needs the DB_* env vars.

    python scripts/migrate_json_to_pg.py
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import DbConfig  # noqa: E402
from db import Database  # noqa: E402
from logger import Logger  # noqa: E402

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name: str) -> list:
    path = os.path.join(_BASE, name)
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


async def main():
    log = Logger(console_log=True)
    db = Database(log)
    await db.connect(DbConfig.from_env())
    await db.init_schema()

    for name in _load("whitelist.json"):
        if isinstance(name, str):
            await db.add_to_list("whitelist", name)
    for name in _load("blacklist.json"):
        if isinstance(name, str):
            await db.add_to_list("blacklist", name)
    for channel in _load("joinable_channels.json"):
        if isinstance(channel, str):
            await db.add_channel(channel)

    log.passing(f"whitelist -> {await db.list_all('whitelist')}")
    log.passing(f"blacklist -> {await db.list_all('blacklist')}")
    log.passing(f"channels  -> {await db.all_channels()}")
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
