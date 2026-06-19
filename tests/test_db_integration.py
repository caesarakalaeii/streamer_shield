"""Integration test for db.Database. Skipped unless DB_HOST is set.

Run against a local Postgres, e.g.:
    DB_HOST=localhost DB_PORT=55432 DB_NAME=streamer_shield \\
    DB_USER=streamer_shield_user DB_PASSWORD=devpass DB_SSLMODE=disable \\
    .venv/bin/pytest tests/test_db_integration.py -q
"""
import os
from datetime import datetime, timezone

import pytest

from config import DbConfig
from db import Database

pytestmark = pytest.mark.skipif(
    not os.environ.get("DB_HOST"), reason="set DB_* env to run the DB integration test"
)


async def test_full_roundtrip():
    db = Database()
    await db.connect(DbConfig.from_env())
    await db.init_schema()
    assert await db.ping() is True

    # lists (case-insensitive)
    await db.add_to_list("whitelist", "Alice")
    await db.add_to_list("whitelist", "alice")  # upsert, no dupe
    assert await db.is_listed("whitelist", "ALICE")
    assert await db.list_all("whitelist") == ["alice"]
    await db.remove_from_list("whitelist", "alice")
    assert not await db.is_listed("whitelist", "alice")

    # channels
    await db.add_channel("Caesarlp")
    assert "caesarlp" in await db.all_channels()
    await db.remove_channel("caesarlp")

    # settings / atomic counter
    first = await db.incr_setting("pat_count")
    second = await db.incr_setting("pat_count")
    assert second == first + 1
    await db.set_setting("k", "v")
    assert await db.get_setting("k") == "v"
    assert await db.get_setting("missing", "default") == "default"

    # token persistence
    await db.save_tokens("acc1", "ref1", "scopeA scopeB")
    await db.save_tokens("acc2", "ref2", "scopeA")  # upsert single row
    tok = await db.load_tokens()
    assert tok["access_token"] == "acc2" and tok["refresh_token"] == "ref2"

    # observation with nullable follower_count + datetime
    await db.record_observation(
        {
            "login": "scammer1",
            "twitch_user_id": "123",
            "display_name": "Scammer One",
            "description": "free gift discord.gg/x",
            "account_created_at": datetime.now(timezone.utc),
            "follower_count": None,
            "follows_channel": True,
            "follow_age_days": 0,
            "broadcaster_type": "",
            "profile_image_url": "https://x/default.png",
            "has_default_avatar": True,
            "model_confidence": 0.97,
            "action_taken": "restricted",
            "is_armed": True,
            "channel_id": "999",
        }
    )
    await db.close()


async def test_channel_settings_roundtrip():
    db = Database()
    await db.connect(DbConfig.from_env())
    await db.init_schema()

    await db.add_channel(
        "CaesarLP",
        broadcaster_id="555",
        defaults={"is_armed": True, "collect_data": True, "age_threshold": 3,
                  "conf_restrict": 0.8, "conf_monitor": 0.4},
    )
    ch = await db.get_channel_by_id("555")
    assert ch and ch["login"] == "caesarlp" and ch["is_armed"] is True and ch["age_threshold"] == 3

    await db.update_channel_settings("caesarlp", is_armed=False, conf_restrict=0.95)
    ch2 = await db.get_channel_by_login("caesarlp")
    assert ch2["is_armed"] is False and abs(ch2["conf_restrict"] - 0.95) < 1e-6

    assert any(c["login"] == "caesarlp" for c in await db.list_channels())

    await db.record_observation(
        {"login": "sus", "channel_id": "555", "model_confidence": 0.9, "action_taken": "RESTRICTED"}
    )
    recent = await db.recent_observations(channel_id="555", limit=10)
    assert recent and recent[0]["login"] == "sus"

    await db.remove_channel("caesarlp")
    assert await db.get_channel_by_id("555") is None
    await db.close()
