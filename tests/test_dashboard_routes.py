"""Smoke the Quart app wiring for the unauthenticated landing page.

Authenticated views require a live bot/db, so they're covered by the pure
dashboard rendering tests instead; this just confirms the app + route + session
plumbing works end-to-end.
"""
import streamer_shield_chatbot as cb


async def test_landing_route_serves_html_without_session():
    client = cb.app.test_client()
    resp = await client.get("/")
    assert resp.status_code == 200
    body = await resp.get_data(as_text=True)
    assert "Log in with Twitch" in body
    assert "<html" in body


class _HealthStub:
    """Minimal stand-in for chat_bot exposing only what /health reads."""

    def __init__(self, *, running: bool, db_healthy: bool):
        self.running = running
        self._db_healthy = db_healthy


async def test_health_ready_while_awaiting_login():
    # Readiness must report ready before the one-time OAuth login: the pod has to
    # join the Service (which only routes to ready pods) so /login can reach it.
    # Gating readiness on post-login `running` deadlocks the login flow.
    cb.chat_bot = _HealthStub(running=False, db_healthy=True)
    resp = await cb.app.test_client().get("/health")
    assert resp.status_code == 200


async def test_health_ready_when_running():
    cb.chat_bot = _HealthStub(running=True, db_healthy=True)
    resp = await cb.app.test_client().get("/health")
    assert resp.status_code == 200


async def test_health_not_ready_when_db_down():
    cb.chat_bot = _HealthStub(running=True, db_healthy=False)
    resp = await cb.app.test_client().get("/health")
    assert resp.status_code == 503
