"""Quick manual check against a running prediction API (dev helper)."""
import httpx

URL = "http://localhost:38080/api/predict"
payload = {
    "login": "jessica_howard472",
    "display_name": "JessicaHoward",
    "description": "FREE gift cards!! check my discord.gg/abc",
    "account_age_days": 3,
    "broadcaster_type": "",
    "follows_channel": True,
    "follow_age_days": 0,
    "has_default_avatar": True,
}

resp = httpx.post(URL, json=payload, timeout=10)
if resp.status_code == 200:
    print("Result:", resp.json())
else:
    print("Error:", resp.status_code, resp.text)
