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
