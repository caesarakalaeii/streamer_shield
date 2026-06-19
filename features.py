"""Shared feature engineering for StreamerShield.

Single source of truth that turns a Twitch user into the model's inputs. Imported
by the bot (gathers the raw fields from Twitch), the prediction API (receives them
as JSON), and the training pipeline (computes them from labelled rows) so the
feature contract can never drift between train and serve.

Intentionally dependency-free (no numpy / no tensorflow) so the bot image can use
it without pulling heavy ML deps.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Optional

# --- username cleaning (mirrors the original char-CNN preprocessing) ----------
_USERNAME_RE = re.compile(r"[^a-zA-Z0-9_]")


def clean_username(name: str) -> str:
    return _USERNAME_RE.sub(" ", name or "").lower()


def clean_bio(description: str) -> str:
    """Light normalisation for the text branch; the model's TextVectorization layer
    does the rest (lowercase + punctuation stripping)."""
    return re.sub(r"\s+", " ", (description or "").strip())


# --- bio signal detectors -----------------------------------------------------
_URL_RE = re.compile(
    r"(https?://|www\.|discord\.gg|t\.me/|telegram|whatsapp|\b\w+\.(?:gg|com|net|ru|xyz|link|io|me)\b)",
    re.IGNORECASE,
)

# Tokens that frequently appear in scam / engagement-bait bios.
SCAM_KEYWORDS = (
    "free", "gift", "giveaway", "cheap", "viewers", "followers", "promo",
    "discord", "telegram", "whatsapp", "crypto", "bitcoin", "invest",
    "onlyfans", "nudes", "18+", "click", "check my", "sub for sub", "f4f",
    "dm me", "earn", "$", "💸", "🎁",
)

# Twitch default avatars are served from a well-known path.
_DEFAULT_AVATAR_MARKERS = ("user-default-pictures", "default-pictures-uv", "/xarth/")


def bio_has_url(description: str) -> bool:
    return bool(_URL_RE.search(description or ""))


def bio_has_scam_keyword(description: str) -> bool:
    low = (description or "").lower()
    return any(kw in low for kw in SCAM_KEYWORDS)


def has_default_avatar(profile_image_url: Optional[str]) -> bool:
    url = (profile_image_url or "").lower()
    return any(marker in url for marker in _DEFAULT_AVATAR_MARKERS)


def name_display_mismatch(login: str, display_name: Optional[str]) -> bool:
    """True when the display name is not just a capitalisation of the login
    (a weak signal: many bot accounts have unrelated display names)."""
    if not display_name:
        return False
    return (login or "").lower() != display_name.lower()


def account_age_days(created_at: Optional[datetime], now: Optional[datetime] = None) -> float:
    if created_at is None:
        return 0.0
    now = now or datetime.now(timezone.utc)
    # Tolerate naive datetimes by assuming UTC.
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return max(0.0, (now - created_at).total_seconds() / 86400.0)


# --- numeric feature vector ---------------------------------------------------
# ORDER IS PART OF THE MODEL CONTRACT. Appending is safe; reordering/removing
# requires retraining. Keep in sync with the Normalization layer adapt step.
NUMERIC_FEATURE_NAMES = (
    "account_age_days",
    "follower_count_log",
    "follower_known",
    "follows_channel",
    "follow_age_days",
    "broadcaster_affiliate",
    "broadcaster_partner",
    "has_default_avatar",
    "name_display_mismatch",
    "bio_len",
    "bio_has_url",
    "bio_has_scam_keyword",
)
NUM_NUMERIC_FEATURES = len(NUMERIC_FEATURE_NAMES)


def numeric_vector(
    *,
    account_age_days: float,
    follower_count: Optional[int],
    follows_channel: Optional[bool],
    follow_age_days: Optional[int],
    broadcaster_type: Optional[str],
    has_default_avatar: bool,
    name_display_mismatch: bool,
    bio_len: int,
    bio_has_url: bool,
    bio_has_scam_keyword: bool,
) -> list[float]:
    bt = (broadcaster_type or "").lower()
    return [
        float(account_age_days),
        math.log1p(follower_count) if follower_count is not None else 0.0,
        1.0 if follower_count is not None else 0.0,
        1.0 if follows_channel else 0.0,
        float(follow_age_days) if (follows_channel and follow_age_days is not None) else -1.0,
        1.0 if bt == "affiliate" else 0.0,
        1.0 if bt == "partner" else 0.0,
        1.0 if has_default_avatar else 0.0,
        1.0 if name_display_mismatch else 0.0,
        float(bio_len),
        1.0 if bio_has_url else 0.0,
        1.0 if bio_has_scam_keyword else 0.0,
    ]


def build_model_inputs(
    *,
    login: str,
    display_name: Optional[str] = None,
    description: Optional[str] = None,
    account_age_days: float = 0.0,
    follower_count: Optional[int] = None,
    follows_channel: Optional[bool] = None,
    follow_age_days: Optional[int] = None,
    broadcaster_type: Optional[str] = None,
    profile_image_url: Optional[str] = None,
    has_default_avatar_value: Optional[bool] = None,
) -> dict:
    """Build the three model inputs (username string, bio string, numeric vector)
    from raw Twitch fields. Works identically on the bot and API sides."""
    desc = description or ""
    default_av = (
        has_default_avatar_value
        if has_default_avatar_value is not None
        else has_default_avatar(profile_image_url)
    )
    return {
        "username": clean_username(login),
        "bio": clean_bio(desc),
        "numeric": numeric_vector(
            account_age_days=account_age_days,
            follower_count=follower_count,
            follows_channel=follows_channel,
            follow_age_days=follow_age_days,
            broadcaster_type=broadcaster_type,
            has_default_avatar=default_av,
            name_display_mismatch=name_display_mismatch(login, display_name),
            bio_len=len(desc),
            bio_has_url=bio_has_url(desc),
            bio_has_scam_keyword=bio_has_scam_keyword(desc),
        ),
    }
