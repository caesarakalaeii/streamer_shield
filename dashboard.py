"""HTML rendering for the StreamerShield dashboard.

Pure functions: take data, return HTML strings. No bot/DB coupling (the routes in
streamer_shield_chatbot.py fetch data and call these). All user-controlled values —
logins, display names, and especially scammer bios — are escaped to avoid stored XSS.
"""
from __future__ import annotations

import html
from typing import Optional

_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; font: 15px/1.5 system-ui, sans-serif; background: #0e0f13; color: #e6e6e6; }
.wrap { max-width: 980px; margin: 0 auto; padding: 24px; }
h1 { font-size: 22px; } h2 { font-size: 18px; margin-top: 28px; } h3 { margin: 0 0 12px; }
a { color: #9b8cff; } .muted { color: #8a8f98; }
.nav { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #23252b; padding-bottom: 12px; }
.card { background: #16181d; border: 1px solid #23252b; border-radius: 10px; padding: 16px; margin: 14px 0; }
.card.danger { border-color: #5a2230; }
label { display: block; margin: 8px 0; }
input[type=number], input[type=text] { background: #0e0f13; color: #e6e6e6; border: 1px solid #2c2f37; border-radius: 6px; padding: 6px 8px; width: 160px; }
button { background: #6c5ce7; color: #fff; border: 0; border-radius: 6px; padding: 8px 14px; cursor: pointer; font-size: 14px; }
button.secondary { background: #2c2f37; } button.danger { background: #b3304a; } button.link { background: none; color: #9b8cff; padding: 0; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #23252b; vertical-align: top; }
.pill { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 12px; }
.on { background: #14361f; color: #6ee7a0; } .off { background: #3a1d23; color: #ff9bb0; }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
"""


def _page(title: str, body: str, login: Optional[str] = None) -> str:
    nav_right = (
        f'<span class="muted">{html.escape(login)}</span> · <a href="/logout">logout</a>'
        if login
        else '<a href="/login">login</a>'
    )
    return (
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{html.escape(title)}</title><style>{_CSS}</style></head><body><div class='wrap'>"
        f"<div class='nav'><h1>🛡️ StreamerShield</h1><div>{nav_right}</div></div>"
        f"{body}</div></body></html>"
    )


def render_landing() -> str:
    body = (
        "<div class='card'><h3>Welcome</h3>"
        "<p class='muted'>Log in with Twitch to manage StreamerShield for your channel.</p>"
        "<p><a href='/login'><button>Log in with Twitch</button></a></p></div>"
    )
    return _page("StreamerShield", body)


def render_no_channel(login: str) -> str:
    safe = html.escape(login)
    body = (
        f"<div class='card'><h3>Hi {safe}</h3>"
        "<p class='muted'>Your channel isn't protected by StreamerShield yet.</p>"
        '<form method="post" action="/channel/join">'
        f'<input type="hidden" name="channel" value="{safe}">'
        "<button type='submit'>Protect my channel</button></form>"
        "<p class='muted'>Then make <b>StreamerShield</b> a moderator in your channel "
        "to enable restrict/monitor.</p></div>"
    )
    return _page("StreamerShield", body, login)


def _settings_form(ch: dict) -> str:
    login = html.escape(ch["login"])
    armed = "checked" if ch.get("is_armed") else ""
    collect = "checked" if ch.get("collect_data") else ""
    return f"""
    <form method="post" action="/channel/settings" class="card">
      <input type="hidden" name="channel" value="{login}">
      <h3>{login}</h3>
      <label><input type="checkbox" name="is_armed" {armed}> Armed — actually apply monitor/restrict (off = observe only)</label>
      <label><input type="checkbox" name="collect_data" {collect}> Collect data on checked users</label>
      <label>Trusted account age (months)
        <input type="number" name="age_threshold" value="{int(ch.get('age_threshold', 6))}" min="0" max="120"></label>
      <label>Restrict at confidence ≥
        <input type="number" step="0.01" min="0" max="1" name="conf_restrict" value="{float(ch.get('conf_restrict', 0.9))}"></label>
      <label>Monitor at confidence ≥
        <input type="number" step="0.01" min="0" max="1" name="conf_monitor" value="{float(ch.get('conf_monitor', 0.5))}"></label>
      <div class="row"><button type="submit">Save settings</button></div>
    </form>
    <form method="post" action="/channel/leave" class="card danger"
          onsubmit="return confirm('Remove StreamerShield from {login}? The bot will leave the channel.')">
      <input type="hidden" name="channel" value="{login}">
      <p class="muted">Remove StreamerShield from this channel — the bot leaves and stops protecting it.</p>
      <button type="submit" class="danger">Remove bot from {login}</button>
    </form>"""


def _obs_table(observations: list[dict]) -> str:
    rows = []
    for o in observations:
        login = html.escape(str(o.get("login", "")))
        conf = o.get("model_confidence")
        conf_s = f"{conf:.2f}" if conf is not None else "—"
        action = html.escape(str(o.get("action_taken", "")))
        desc = html.escape((o.get("description") or "")[:80])
        when = html.escape(str(o.get("observed_at", ""))[:19])
        unrestrict = ""
        if str(o.get("action_taken", "")).upper() in ("RESTRICTED", "ACTIVE_MONITORING") and o.get("channel_id"):
            unrestrict = (
                f"<form method='post' action='/observation/unrestrict' style='display:inline'>"
                f"<input type='hidden' name='channel_id' value='{html.escape(str(o.get('channel_id')))}'>"
                f"<input type='hidden' name='login' value='{login}'>"
                f"<button class='link'>unrestrict</button></form>"
            )
        rows.append(
            f"<tr><td>{when}</td><td>{login}</td><td>{conf_s}</td>"
            f"<td>{action}</td><td>{desc}</td><td>{unrestrict}</td></tr>"
        )
    body = "".join(rows) or "<tr><td colspan='6' class='muted'>No observations yet.</td></tr>"
    return (
        "<table><thead><tr><th>When (UTC)</th><th>User</th><th>Conf</th>"
        "<th>Action</th><th>Bio</th><th></th></tr></thead><tbody>"
        f"{body}</tbody></table>"
    )


def render_streamer(login: str, channel: dict, observations: list[dict]) -> str:
    body = (
        f"<p class='muted'>Managing your channel <b>{html.escape(channel['login'])}</b>.</p>"
        f"{_settings_form(channel)}"
        "<h2>Recent checks</h2>"
        f"<div class='card'>{_obs_table(observations)}</div>"
    )
    return _page("StreamerShield — your channel", body, login)


def _list_card(title: str, kind: str, entries: list[str]) -> str:
    items = "".join(
        f"<tr><td>{html.escape(e)}</td><td>"
        f"<form method='post' action='/admin/list' style='display:inline'>"
        f"<input type='hidden' name='kind' value='{kind}'>"
        f"<input type='hidden' name='action' value='remove'>"
        f"<input type='hidden' name='login' value='{html.escape(e)}'>"
        f"<button class='link'>remove</button></form></td></tr>"
        for e in entries
    ) or "<tr><td colspan='2' class='muted'>empty</td></tr>"
    return f"""
    <div class="card"><h3>{html.escape(title)}</h3>
      <table><tbody>{items}</tbody></table>
      <form method="post" action="/admin/list" class="row" style="margin-top:10px">
        <input type="hidden" name="kind" value="{kind}">
        <input type="hidden" name="action" value="add">
        <input type="text" name="login" placeholder="username" required>
        <button type="submit" class="secondary">Add</button>
      </form>
    </div>"""


def render_admin(login: str, channels: list[dict], whitelist: list[str], blacklist: list[str], observations: list[dict]) -> str:
    chan_rows = []
    for c in channels:
        pill = "<span class='pill on'>armed</span>" if c.get("is_armed") else "<span class='pill off'>observe</span>"
        chan_rows.append(
            f"<tr><td>{html.escape(c['login'])}</td><td>{pill}</td>"
            f"<td class='muted'>monitor≥{float(c.get('conf_monitor',0.5))} · restrict≥{float(c.get('conf_restrict',0.9))} · age {int(c.get('age_threshold',6))}m</td></tr>"
        )
    chan_table = "".join(chan_rows) or "<tr><td colspan='3' class='muted'>No channels yet.</td></tr>"
    settings_forms = "".join(_settings_form(c) for c in channels)
    body = (
        f"<p class='muted'>Admin view ({html.escape(login)}). You manage all channels, lists, and onboarding.</p>"
        "<h2>Channels</h2>"
        f"<div class='card'><table><thead><tr><th>Channel</th><th>Status</th><th>Settings</th></tr></thead>"
        f"<tbody>{chan_table}</tbody></table>"
        "<form method='post' action='/admin/add-channel' class='row' style='margin-top:12px'>"
        "<input type='text' name='channel' placeholder='channel login to add' required>"
        "<button type='submit'>Add channel</button></form>"
        "<p class='muted'>The bot must be made a moderator in that channel for restrict/monitor to work.</p></div>"
        "<h2>Lists (global)</h2>"
        f"{_list_card('Whitelist', 'whitelist', whitelist)}"
        f"{_list_card('Blacklist', 'blacklist', blacklist)}"
        "<h2>Per-channel settings</h2>"
        f"{settings_forms or '<div class=card class=muted>No channels.</div>'}"
        "<h2>Recent checks (all channels)</h2>"
        f"<div class='card'>{_obs_table(observations)}</div>"
    )
    return _page("StreamerShield — admin", body, login)
