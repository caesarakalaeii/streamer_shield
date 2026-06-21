"""The asyncpg pool is bound to the loop it was created on, but twitchAPI runs
Chat and EventSub callbacks on their own threads/loops. These tests verify the
Database bridges foreign-loop calls back onto the pool's owning loop instead of
raising 'attached to a different loop'.
"""
import asyncio
import threading

import db as dbmod


class _FakePool:
    """Records the loop each call actually executed on."""

    def __init__(self):
        self.ran_on = None

    async def fetchval(self, *args, **kwargs):
        self.ran_on = asyncio.get_running_loop()
        return 42


async def test_db_call_runs_directly_on_owning_loop():
    pool = _FakePool()
    d = dbmod.Database()
    d._pool = pool
    d._loop = asyncio.get_running_loop()

    result = await d._fetchval("SELECT 1")

    assert result == 42
    assert pool.ran_on is asyncio.get_running_loop()


async def test_db_call_bridges_from_foreign_loop():
    # Owner loop lives in a background thread; the pool "belongs" to it.
    owner_loop = asyncio.new_event_loop()
    t = threading.Thread(target=owner_loop.run_forever, daemon=True)
    t.start()
    try:
        pool = _FakePool()
        d = dbmod.Database()
        d._pool = pool
        d._loop = owner_loop

        # We're on pytest's loop, which is NOT owner_loop -> must bridge.
        result = await d._fetchval("SELECT 1")

        assert result == 42
        assert pool.ran_on is owner_loop
    finally:
        owner_loop.call_soon_threadsafe(owner_loop.stop)
        t.join(timeout=2)
