import helix_extra
from helix_extra import LowTrustStatus, decide_status


def test_decide_status_tiers():
    assert decide_status(0.95, 0.9, 0.5) == LowTrustStatus.RESTRICTED
    assert decide_status(0.90, 0.9, 0.5) == LowTrustStatus.RESTRICTED
    assert decide_status(0.70, 0.9, 0.5) == LowTrustStatus.ACTIVE_MONITORING
    assert decide_status(0.50, 0.9, 0.5) == LowTrustStatus.ACTIVE_MONITORING
    assert decide_status(0.20, 0.9, 0.5) == LowTrustStatus.NONE


def test_suspicious_manage_scope_serializes_to_raw_string():
    # build_scope joins .value; our custom Enum must carry the literal scope string.
    from twitchAPI.helper import build_scope

    assert build_scope([helix_extra.SUSPICIOUS_MANAGE_SCOPE]) == "moderator:manage:suspicious_users"


class _Capture:
    """Fake Twitch whose _api_request records the call and returns a fixed status."""

    def __init__(self, status=200):
        self.base_url = "https://api.twitch.tv/helix/"
        self.session_timeout = None
        self._status = status
        self.captured = {}

    async def _api_request(self, method, session, url, auth_type, required_scope, data=None, retries=1):
        self.captured.update(method=method, url=url, data=data, scope=required_scope, auth=auth_type)
        outer = self

        class _Resp:
            status = outer._status

            async def text(self):
                return ""

        return _Resp()


async def test_set_suspicious_status_success_builds_request():
    tw = _Capture(status=200)
    ok = await helix_extra.set_suspicious_status(tw, "broad1", "mod1", "user1", LowTrustStatus.RESTRICTED)
    assert ok is True
    c = tw.captured
    assert c["method"] == "POST"
    assert "moderation/suspicious_users" in c["url"]
    assert "broadcaster_id=broad1" in c["url"] and "moderator_id=mod1" in c["url"]
    assert "user_id=" not in c["url"]  # user_id goes in the BODY, not the query
    assert c["data"] == {"user_id": "user1", "status": "RESTRICTED"}
    assert c["scope"] == []  # no client-side scope enforcement


async def test_set_suspicious_status_rejects_non_settable():
    tw = _Capture(status=200)
    ok = await helix_extra.set_suspicious_status(tw, "b", "m", "u", LowTrustStatus.NONE)
    assert ok is False
    assert tw.captured == {}  # never hits the API


async def test_remove_suspicious_status_uses_delete_with_query():
    tw = _Capture(status=200)
    ok = await helix_extra.remove_suspicious_status(tw, "broad1", "mod1", "user1")
    assert ok is True
    c = tw.captured
    assert c["method"] == "DELETE"
    assert "broadcaster_id=broad1" in c["url"] and "moderator_id=mod1" in c["url"]
    assert "user_id=user1" in c["url"]  # removal passes user_id in the query
    assert c["data"] is None


async def test_set_suspicious_status_handles_failure():
    class FakeResp:
        status = 400

        async def text(self):
            return '{"error":"bad"}'

    class FakeTwitch:
        base_url = "https://api.twitch.tv/helix/"
        session_timeout = None

        async def _api_request(self, *a, **k):
            return FakeResp()

    ok = await helix_extra.set_suspicious_status(
        FakeTwitch(), "b", "m", "u", LowTrustStatus.ACTIVE_MONITORING
    )
    assert ok is False
