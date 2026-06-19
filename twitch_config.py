"""Runtime configuration for the StreamerShield bot.

This is a plain data holder. Values are populated from environment variables by
:func:`config.build_twitch_config`. It deliberately does not import twitchAPI so
it stays cheap to import and easy to construct in tests.
"""
from dataclasses import dataclass, field
from typing import Any, List, Optional

from logger import Logger


@dataclass
class TwitchConfig:
    # Twitch app credentials + bot identity
    app_id: str
    app_secret: str
    user_name: str
    admin: str

    # Public URLs
    eventsub_url: str
    shield_url: str
    auth_url: str

    # OAuth scopes (list of twitchAPI AuthScope / Enum members). Filled in by the
    # bot which owns the twitchAPI import; left empty here to avoid the dependency.
    user_scopes: List[Any] = field(default_factory=list)

    # Behaviour
    is_armed: bool = False
    collect_data: bool = True
    age_threshold: int = 6          # months; accounts older than this skip the model
    max_length: int = 29            # model username sequence length (mirrors the API)

    # Confidence -> action thresholds (tiered monitor/restrict)
    conf_restrict: float = 0.9      # >= this -> "restricted"
    conf_monitor: float = 0.5       # >= this (and < restrict) -> "active_monitoring"

    # Only run the interactive stdin CLI when explicitly enabled (never in k8s)
    enable_cli: bool = False

    logger: Optional[Logger] = None
