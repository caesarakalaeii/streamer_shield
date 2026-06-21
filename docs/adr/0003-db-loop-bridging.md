# ADR 0003: Bridge DB calls onto the pool's owning event loop

- Status: Accepted
- Date: 2026-06-21

## Context

The bot runs on a single main event loop (`asyncio.run(chat_bot.run())`), and the
asyncpg connection pool is created there (`Database.connect`). asyncpg pools and
connections are bound to the loop they were created on.

twitchAPI 4.5.0 does **not** run its Chat and EventSub clients on that loop:
`Chat.start()` spins up a dedicated `__socket_thread` with its own
`asyncio.new_event_loop()`, and `EventSubWebhook.start()` does the same with a
`__hook_thread` / `__hook_loop`. All chat and eventsub callbacks
(`on_ready`, `on_message`, `on_join`, `on_follow`) therefore run on a *different*
loop than the pool.

Every `await self.db.*` from those callbacks raised:

- `RuntimeError: got Future attached to a different loop`
- `asyncpg ... InterfaceError: another operation is in progress`
- `asyncpg ... ConnectionDoesNotExistError: connection was closed in the middle of operation`

The web/dashboard/auth paths run on the main loop (hypercorn served as a task),
so login, the dashboard, and browser-driven onboarding worked — but the bot's
moderation core did not: `on_ready` could not rejoin channels, `check_user` could
not read whitelist/blacklist/channel settings, and observations were never
recorded.

## Decision

`Database` records the loop that owns the pool at `connect()` time
(`self._loop = asyncio.get_running_loop()`), and funnels all pool primitives
(`execute`, `fetch`, `fetchrow`, `fetchval`) through a single `_run` helper:

```python
async def _run(self, coro):
    running = asyncio.get_running_loop()  # (guarded for no-loop)
    if self._loop is None or running is self._loop:
        return await coro
    fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
    return await asyncio.wrap_future(fut)
```

When a query is issued from a foreign loop it is scheduled back onto the owning
loop via `run_coroutine_threadsafe` and awaited through `wrap_future`. Calls
already on the owning loop run inline with no overhead. All public `Database`
method signatures and the 20 call sites are unchanged.

## Consequences

- DB access works uniformly from the main loop, the chat loop, and the eventsub
  loop. The bot's moderation core (channel rejoin, user checks, observations)
  functions again.
- All DB I/O is serialized onto one loop. With a single-pod deployment and a
  small pool this is fine; if throughput ever becomes a concern, the alternative
  is a per-loop pool, which this design can be swapped for behind the same `_run`
  seam.
- `connect()` must be called on the main loop (it already is). `init_schema`,
  `ping`, and `close` continue to use the pool directly on the main loop and do
  not need bridging.
