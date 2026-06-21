"""Postgres persistence for StreamerShield (asyncpg).

Replaces the old JSON-file storage (whitelist.json / blacklist.json /
joinable_channels.json / known_users.json). Owns a connection pool, creates the
schema idempotently on startup, and exposes small async CRUD helpers.

Only the bot uses this; the model API has no database dependency.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import asyncpg

from config import DbConfig
from logger import Logger

SCHEMA = """
CREATE TABLE IF NOT EXISTS list_entries (
    kind     TEXT NOT NULL CHECK (kind IN ('whitelist', 'blacklist')),
    login    TEXT NOT NULL,
    added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (kind, login)
);

CREATE TABLE IF NOT EXISTS channels (
    login           TEXT PRIMARY KEY,
    broadcaster_id  TEXT,
    is_armed        BOOLEAN NOT NULL DEFAULT FALSE,
    collect_data    BOOLEAN NOT NULL DEFAULT TRUE,
    age_threshold   INTEGER NOT NULL DEFAULT 6,
    conf_restrict   REAL NOT NULL DEFAULT 0.9,
    conf_monitor    REAL NOT NULL DEFAULT 0.5,
    joined_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Upgrade-safe: add per-channel settings columns if an older channels table exists.
ALTER TABLE channels ADD COLUMN IF NOT EXISTS broadcaster_id TEXT;
ALTER TABLE channels ADD COLUMN IF NOT EXISTS is_armed BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE channels ADD COLUMN IF NOT EXISTS collect_data BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE channels ADD COLUMN IF NOT EXISTS age_threshold INTEGER NOT NULL DEFAULT 6;
ALTER TABLE channels ADD COLUMN IF NOT EXISTS conf_restrict REAL NOT NULL DEFAULT 0.9;
ALTER TABLE channels ADD COLUMN IF NOT EXISTS conf_monitor REAL NOT NULL DEFAULT 0.5;
CREATE INDEX IF NOT EXISTS idx_channels_broadcaster ON channels (broadcaster_id);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_tokens (
    id            INTEGER PRIMARY KEY DEFAULT 1,
    access_token  TEXT,
    refresh_token TEXT,
    scopes        TEXT,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS observations (
    id                 BIGSERIAL PRIMARY KEY,
    twitch_user_id     TEXT,
    login              TEXT NOT NULL,
    display_name       TEXT,
    description        TEXT,
    account_created_at TIMESTAMPTZ,
    follower_count     INTEGER,
    follows_channel    BOOLEAN,
    follow_age_days    INTEGER,
    broadcaster_type   TEXT,
    profile_image_url  TEXT,
    has_default_avatar BOOLEAN,
    model_confidence   REAL,
    action_taken       TEXT,
    is_armed           BOOLEAN,
    channel_id         TEXT,
    label              SMALLINT,
    observed_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_obs_login ON observations (login);
CREATE INDEX IF NOT EXISTS idx_obs_observed_at ON observations (observed_at);
"""

# Columns accepted by record_observation (login is required).
_OBS_COLUMNS = (
    "twitch_user_id",
    "login",
    "display_name",
    "description",
    "account_created_at",
    "follower_count",
    "follows_channel",
    "follow_age_days",
    "broadcaster_type",
    "profile_image_url",
    "has_default_avatar",
    "model_confidence",
    "action_taken",
    "is_armed",
    "channel_id",
    "label",
)


class Database:
    def __init__(self, logger: Optional[Logger] = None) -> None:
        self._pool: Optional[asyncpg.Pool] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._log = logger

    async def connect(self, cfg: DbConfig) -> None:
        self._loop = asyncio.get_running_loop()
        self._pool = await asyncpg.create_pool(
            host=cfg.host,
            port=cfg.port,
            user=cfg.user,
            password=cfg.password,
            database=cfg.name,
            ssl=cfg.ssl(),
            min_size=1,
            max_size=5,
            command_timeout=10,
        )
        if self._log:
            self._log.passingblue(f"Connected to Postgres {cfg.host}:{cfg.port}/{cfg.name}")

    # --- loop bridging --------------------------------------------------------
    # The asyncpg pool is bound to the loop it was created on (the main loop).
    # twitchAPI runs Chat and EventSub callbacks on their own threads/loops, so a
    # DB call from on_ready/on_message/on_join/on_follow would otherwise raise
    # "got Future attached to a different loop". Every pool primitive is funnelled
    # through _run, which hops back onto the owning loop when called elsewhere.
    async def _run(self, coro):
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if self._loop is None or running is self._loop:
            return await coro
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return await asyncio.wrap_future(fut)

    async def _execute(self, *args, **kwargs):
        return await self._run(self._pool.execute(*args, **kwargs))

    async def _fetch(self, *args, **kwargs):
        return await self._run(self._pool.fetch(*args, **kwargs))

    async def _fetchrow(self, *args, **kwargs):
        return await self._run(self._pool.fetchrow(*args, **kwargs))

    async def _fetchval(self, *args, **kwargs):
        return await self._run(self._pool.fetchval(*args, **kwargs))

    async def init_schema(self) -> None:
        assert self._pool is not None, "connect() must be called before init_schema()"
        async with self._pool.acquire() as conn:
            await conn.execute(SCHEMA)
        if self._log:
            self._log.passingblue("Database schema ready")

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def ping(self) -> bool:
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                return (await conn.fetchval("SELECT 1")) == 1
        except Exception:  # noqa: BLE001 - health check must never raise
            return False

    # --- whitelist / blacklist ------------------------------------------------
    async def is_listed(self, kind: str, login: str) -> bool:
        row = await self._fetchval(
            "SELECT 1 FROM list_entries WHERE kind = $1 AND login = $2",
            kind,
            login.lower(),
        )
        return row is not None

    async def add_to_list(self, kind: str, login: str) -> None:
        await self._execute(
            "INSERT INTO list_entries (kind, login) VALUES ($1, $2) "
            "ON CONFLICT (kind, login) DO NOTHING",
            kind,
            login.lower(),
        )

    async def remove_from_list(self, kind: str, login: str) -> None:
        await self._execute(
            "DELETE FROM list_entries WHERE kind = $1 AND login = $2",
            kind,
            login.lower(),
        )

    async def list_all(self, kind: str) -> list[str]:
        rows = await self._fetch(
            "SELECT login FROM list_entries WHERE kind = $1 ORDER BY login", kind
        )
        return [r["login"] for r in rows]

    # --- channels (with per-channel settings) ---------------------------------
    async def add_channel(self, login: str, broadcaster_id=None, defaults: Optional[dict] = None) -> None:
        d = defaults or {}
        await self._execute(
            """INSERT INTO channels
                 (login, broadcaster_id, is_armed, collect_data, age_threshold, conf_restrict, conf_monitor)
               VALUES ($1, $2, $3, $4, $5, $6, $7)
               ON CONFLICT (login) DO UPDATE
                 SET broadcaster_id = COALESCE(EXCLUDED.broadcaster_id, channels.broadcaster_id)""",
            login.lower(),
            str(broadcaster_id) if broadcaster_id is not None else None,
            bool(d.get("is_armed", False)),
            bool(d.get("collect_data", True)),
            int(d.get("age_threshold", 6)),
            float(d.get("conf_restrict", 0.9)),
            float(d.get("conf_monitor", 0.5)),
        )

    async def set_channel_id(self, login: str, broadcaster_id) -> None:
        await self._execute(
            "UPDATE channels SET broadcaster_id = $2 WHERE login = $1", login.lower(), str(broadcaster_id)
        )

    async def remove_channel(self, login: str) -> None:
        await self._execute("DELETE FROM channels WHERE login = $1", login.lower())

    async def all_channels(self) -> list[str]:
        rows = await self._fetch("SELECT login FROM channels ORDER BY login")
        return [r["login"] for r in rows]

    async def list_channels(self) -> list[dict]:
        rows = await self._fetch("SELECT * FROM channels ORDER BY login")
        return [dict(r) for r in rows]

    async def get_channel_by_login(self, login: str) -> Optional[dict]:
        row = await self._fetchrow("SELECT * FROM channels WHERE login = $1", login.lower())
        return dict(row) if row else None

    async def get_channel_by_id(self, broadcaster_id) -> Optional[dict]:
        row = await self._fetchrow("SELECT * FROM channels WHERE broadcaster_id = $1", str(broadcaster_id))
        return dict(row) if row else None

    async def update_channel_settings(self, login: str, **fields) -> None:
        allowed = ("is_armed", "collect_data", "age_threshold", "conf_restrict", "conf_monitor", "broadcaster_id")
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        assignments = ", ".join(f"{col} = ${i + 2}" for i, col in enumerate(sets))
        await self._execute(
            f"UPDATE channels SET {assignments} WHERE login = $1", login.lower(), *sets.values()
        )

    # --- settings -------------------------------------------------------------
    async def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        val = await self._fetchval("SELECT value FROM settings WHERE key = $1", key)
        return default if val is None else val

    async def set_setting(self, key: str, value: str) -> None:
        await self._execute(
            "INSERT INTO settings (key, value) VALUES ($1, $2) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            key,
            str(value),
        )

    async def incr_setting(self, key: str) -> int:
        val = await self._fetchval(
            "INSERT INTO settings (key, value) VALUES ($1, '1') "
            "ON CONFLICT (key) DO UPDATE SET value = "
            "(COALESCE(settings.value, '0')::bigint + 1)::text RETURNING value",
            key,
        )
        return int(val)

    # --- auth token persistence ----------------------------------------------
    async def load_tokens(self) -> Optional[dict]:
        row = await self._fetchrow(
            "SELECT access_token, refresh_token, scopes FROM auth_tokens WHERE id = 1"
        )
        if row is None or row["access_token"] is None:
            return None
        return dict(row)

    async def save_tokens(self, access_token: str, refresh_token: str, scopes: str = "") -> None:
        await self._execute(
            "INSERT INTO auth_tokens (id, access_token, refresh_token, scopes, updated_at) "
            "VALUES (1, $1, $2, $3, now()) "
            "ON CONFLICT (id) DO UPDATE SET access_token = $1, refresh_token = $2, "
            "scopes = $3, updated_at = now()",
            access_token,
            refresh_token,
            scopes,
        )

    # --- observations ---------------------------------------------------------
    async def record_observation(self, obs: dict[str, Any]) -> None:
        cols = [c for c in _OBS_COLUMNS if c in obs]
        if "login" not in cols:
            raise ValueError("record_observation requires a 'login'")
        placeholders = ", ".join(f"${i + 1}" for i in range(len(cols)))
        values = [obs[c] for c in cols]
        await self._execute(
            f"INSERT INTO observations ({', '.join(cols)}) VALUES ({placeholders})",
            *values,
        )

    async def recent_observations(self, channel_id=None, limit: int = 50) -> list[dict]:
        if channel_id is not None:
            rows = await self._fetch(
                "SELECT * FROM observations WHERE channel_id = $1 ORDER BY observed_at DESC LIMIT $2",
                str(channel_id),
                limit,
            )
        else:
            rows = await self._fetch(
                "SELECT * FROM observations ORDER BY observed_at DESC LIMIT $1", limit
            )
        return [dict(r) for r in rows]
