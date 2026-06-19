"""Environment-based configuration for StreamerShield.

Replaces the old gitignored ``config.py`` / ``end_point_config.py`` import-time
secrets. All configuration now comes from environment variables (injected by the
k8s ConfigMap + Secret in production, or a local ``.env`` file in development).

This module contains NO secrets and is safe to commit.
"""
from __future__ import annotations

import os
import ssl as _ssl
from dataclasses import dataclass
from typing import Optional

try:
    # Best-effort: load a local .env if present. In k8s there is no .env and the
    # vars come straight from the environment, so this is a harmless no-op there.
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional at runtime
    pass

from logger import Logger
from twitch_config import TwitchConfig


class ConfigError(RuntimeError):
    """Raised when a required environment variable is missing."""


def _req(name: str) -> str:
    val = os.environ.get(name)
    if val is None or val == "":
        raise ConfigError(f"Missing required environment variable: {name}")
    return val


def _opt(name: str, default: str) -> str:
    val = os.environ.get(name)
    return default if val is None or val == "" else val


def _bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None or val == "":
        return default
    return val.strip().lower() in ("1", "true", "yes", "on", "y", "t")


def _int(name: str, default: int) -> int:
    val = os.environ.get(name)
    if val is None or val == "":
        return default
    try:
        return int(val)
    except ValueError as exc:
        raise ConfigError(f"Environment variable {name}={val!r} is not an int") from exc


def _float(name: str, default: float) -> float:
    val = os.environ.get(name)
    if val is None or val == "":
        return default
    try:
        return float(val)
    except ValueError as exc:
        raise ConfigError(f"Environment variable {name}={val!r} is not a float") from exc


def build_twitch_config(logger: Optional[Logger] = None) -> TwitchConfig:
    """Construct the bot's :class:`TwitchConfig` from the environment.

    ``user_scopes`` is left empty here; the bot fills it in (it owns the twitchAPI
    import and the custom suspicious-users scope from ``helix_extra``).
    """
    return TwitchConfig(
        app_id=_req("TWITCH_APP_ID"),
        app_secret=_req("TWITCH_APP_SECRET"),
        user_name=_req("TWITCH_USER"),
        admin=_opt("ADMIN_USER", "caesarlp"),
        eventsub_url=_req("EVENTSUB_URL"),
        shield_url=_req("SHIELD_URL"),
        auth_url=_req("AUTH_URL"),
        is_armed=_bool("IS_ARMED", False),
        collect_data=_bool("COLLECT_DATA", True),
        age_threshold=_int("AGE_THRESHOLD", 6),
        max_length=_int("MAX_LENGTH", 29),
        conf_restrict=_float("CONF_RESTRICT", 0.9),
        conf_monitor=_float("CONF_MONITOR", 0.5),
        enable_cli=_bool("ENABLE_CLI", False),
        logger=logger,
    )


@dataclass(frozen=True)
class DbConfig:
    host: str
    port: int
    name: str
    user: str
    password: str
    sslmode: str = "require"

    @classmethod
    def from_env(cls) -> "DbConfig":
        return cls(
            host=_req("DB_HOST"),
            port=_int("DB_PORT", 5432),
            name=_req("DB_NAME"),
            user=_req("DB_USER"),
            password=_req("DB_PASSWORD"),
            sslmode=_opt("DB_SSLMODE", "require"),
        )

    def ssl(self):
        """Return an asyncpg-compatible ssl argument.

        CloudNativePG presents a server certificate signed by its own CA. ``require``
        means "encrypt but don't verify the CA" (libpq semantics), which is the
        pragmatic default for in-cluster traffic. ``verify-*`` returns a verifying
        context (needs the CA available to the client).
        """
        if self.sslmode in ("", "disable"):
            return False
        ctx = _ssl.create_default_context()
        if self.sslmode in ("allow", "prefer", "require"):
            ctx.check_hostname = False
            ctx.verify_mode = _ssl.CERT_NONE
        return ctx
