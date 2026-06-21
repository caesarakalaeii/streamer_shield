import dashboard


def test_landing_renders_with_login_link():
    out = dashboard.render_landing()
    assert "<html" in out and "/login" in out


def test_no_channel_escapes_login():
    out = dashboard.render_no_channel("<script>evil</script>")
    assert "<script>evil" not in out
    assert "&lt;script&gt;" in out


def test_no_channel_offers_self_service_join():
    # Onboarding must not be an admin-only dead-end: the streamer gets a
    # self-service action to protect their own channel.
    out = dashboard.render_no_channel("streamer")
    assert 'action="/channel/join"' in out
    assert "ask the admin" not in out.lower()


def test_streamer_view_reflects_settings_and_escapes_bio():
    channel = {
        "login": "caesarlp", "is_armed": True, "collect_data": True,
        "age_threshold": 6, "conf_restrict": 0.9, "conf_monitor": 0.5, "broadcaster_id": "123",
    }
    obs = [{
        "login": "scammer", "model_confidence": 0.97, "action_taken": "RESTRICTED",
        "description": "<img src=x onerror=alert(1)>", "observed_at": "2026-06-19T10:00:00",
        "channel_id": "123",
    }]
    out = dashboard.render_streamer("caesarlp", channel, obs)
    assert "caesarlp" in out
    assert "checked" in out  # armed + collect checkboxes
    # attacker-controlled bio must be escaped (no live HTML/JS)
    assert "onerror=alert(1)>" not in out
    assert "&lt;img" in out
    assert "unrestrict" in out  # a restricted observation exposes an unrestrict action


def test_admin_view_lists_channels_lists_and_addform():
    channels = [{
        "login": "caesarlp", "is_armed": False, "collect_data": True,
        "age_threshold": 6, "conf_restrict": 0.9, "conf_monitor": 0.5,
    }]
    out = dashboard.render_admin("caesarlp", channels, ["gooduser"], ["baduser"], [])
    assert "caesarlp" in out and "gooduser" in out and "baduser" in out
    assert "add-channel" in out
