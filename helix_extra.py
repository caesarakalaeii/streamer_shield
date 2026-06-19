"""Helix calls that the installed twitchAPI version does not wrap.

As of pytwitchAPI 4.5.0 there is no wrapper for the Suspicious-User management
endpoints, and ``AuthScope`` has no ``MODERATOR_MANAGE_SUSPICIOUS_USERS`` member.
We therefore:

  * carry the manage scope in a plain ``Enum`` (``SUSPICIOUS_MANAGE_SCOPE``) so
    ``build_scope()`` serialises it via ``.value`` in the OAuth consent URL, and
  * call the endpoint through the library's authenticated request helper with an
    empty ``required_scope`` so the client-side enum check is skipped — Twitch
    enforces the real scope server-side.

The exact wire format (verb / path / status field) is isolated in the constants
below; confirm against the live reference before arming in production:
https://dev.twitch.tv/docs/api/reference/#add-suspicious-status-to-chat-user
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from aiohttp import ClientError, ClientSession
from twitchAPI.helper import build_url
from twitchAPI.type import AuthType, TwitchAPIException, TwitchBackendException


class CustomAuthScope(Enum):
    """Scopes missing from the installed AuthScope enum. ``.value`` is what the
    OAuth layer serialises, so this slots into the scope list transparently."""

    MODERATOR_MANAGE_SUSPICIOUS_USERS = "moderator:manage:suspicious_users"


SUSPICIOUS_MANAGE_SCOPE = CustomAuthScope.MODERATOR_MANAGE_SUSPICIOUS_USERS


class LowTrustStatus:
    """Suspicious-user statuses. ACTIVE_MONITORING / RESTRICTED are the values Twitch
    accepts on the add endpoint; NONE is an internal "take no action" sentinel
    (clearing a status is a separate DELETE call, which Twitch reports as NO_TREATMENT)."""

    NONE = "NONE"
    ACTIVE_MONITORING = "ACTIVE_MONITORING"
    RESTRICTED = "RESTRICTED"


# --- endpoint wire format (confirmed against the Twitch API reference) --------
# Add:    POST   /helix/moderation/suspicious_users?broadcaster_id=&moderator_id=
#                body {"user_id": ..., "status": "ACTIVE_MONITORING"|"RESTRICTED"}  -> 200
# Remove: DELETE /helix/moderation/suspicious_users?broadcaster_id=&moderator_id=&user_id=  -> 200
_PATH = "moderation/suspicious_users"  # appended to twitch.base_url (".../helix/")
_SETTABLE = (LowTrustStatus.ACTIVE_MONITORING, LowTrustStatus.RESTRICTED)


def decide_status(conf: float, conf_restrict: float, conf_monitor: float) -> str:
    """Tiered mapping of model confidence to a suspicious-user treatment."""
    if conf >= conf_restrict:
        return LowTrustStatus.RESTRICTED
    if conf >= conf_monitor:
        return LowTrustStatus.ACTIVE_MONITORING
    return LowTrustStatus.NONE


async def _request(twitch, method: str, url: str, body, who, logger) -> bool:
    timeout = getattr(twitch, "session_timeout", None)
    try:
        async with ClientSession(timeout=timeout) as session:
            # required_scope=[] -> skip the client-side AuthScope membership check;
            # moderator:manage:suspicious_users is enforced by Twitch server-side.
            resp = await twitch._api_request(method, session, url, AuthType.USER, [], data=body)
            if resp.status == 200:
                return True
            text = await resp.text()
            if logger:
                logger.error(f"{method} suspicious_users for {who} failed: HTTP {resp.status} {text}")
            return False
    except (TwitchAPIException, TwitchBackendException, ClientError) as exc:
        if logger:
            logger.error(f"suspicious_users {method} error for {who}: {exc}")
        return False


async def set_suspicious_status(twitch, broadcaster_id, moderator_id, user_id, status, logger=None) -> bool:
    """Apply ACTIVE_MONITORING or RESTRICTED to a user (POST).

    ``moderator_id`` must be a moderator of ``broadcaster_id``'s channel (else 403) — the
    same precondition the old ban path had. Returns True on HTTP 200.
    """
    if status not in _SETTABLE:
        if logger:
            logger.error(f"refusing to set non-settable status {status!r}; use remove_suspicious_status to clear")
        return False
    url = build_url(
        twitch.base_url + _PATH,
        {"broadcaster_id": str(broadcaster_id), "moderator_id": str(moderator_id)},
    )
    return await _request(twitch, "POST", url, {"user_id": str(user_id), "status": status}, user_id, logger)


async def remove_suspicious_status(twitch, broadcaster_id, moderator_id, user_id, logger=None) -> bool:
    """Clear a user's suspicious status (DELETE; Twitch reports NO_TREATMENT)."""
    url = build_url(
        twitch.base_url + _PATH,
        {"broadcaster_id": str(broadcaster_id), "moderator_id": str(moderator_id), "user_id": str(user_id)},
    )
    return await _request(twitch, "DELETE", url, None, user_id, logger)
