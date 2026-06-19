"""Self-contained synthetic data generator for bootstrapping the multi-feature model.

The original seed CSVs (data_for_gen.csv / names.csv / surnames.csv) are not in the
repo, so this module generates plausible labelled examples from small inline corpora.
It is a BOOTSTRAP only: the username/avatar/age/bio-flag signals it encodes are real,
but the model's accuracy on the new features will only become meaningful once
``train_from_db.py`` retrains on real collected observations.

Returns rows of raw fields that ``features.build_model_inputs`` understands, plus a
``label`` (1 = scammer, 0 = human). Deterministic given a seed.
"""
from __future__ import annotations

import random
from typing import Optional

_FIRST_NAMES = [
    "alice", "amber", "jessica", "sophie", "emily", "olivia", "mia", "bella",
    "lucas", "noah", "liam", "ethan", "mason", "logan", "james", "ryan",
    "anna", "laura", "nina", "kate", "lena", "marco", "leon", "felix",
]
_SURNAMES = [
    "howard", "bell", "brooks", "shriver", "miller", "smith", "jones", "evans",
    "clark", "young", "walker", "hughes", "reed", "cole", "ross", "ward",
]
_REAL_HANDLES = [
    "caesarlp", "vtniles", "rustoca", "norari", "creak_creak", "spyfox",
    "pixelpaladin", "shadowfox", "questgiver", "midnightowl", "frostbyte",
    "ramen_lord", "couchpotato", "bitwise", "synthwave", "gigglefin",
]
_GAMES = ["souls", "valorant", "minecraft", "league", "apex", "tarkov", "factorio", "stardew"]

_SCAM_BIOS = [
    "FREE gift cards!! check my discord.gg/{w}",
    "18+ content here -> t.me/{w}",
    "cheap viewers and followers, dm me!",
    "crypto investment, double your bitcoin {w}",
    "click my bio for free nudes {w}",
    "sub for sub f4f follow back instantly",
    "giveaway winner!! claim here {w}.xyz",
    "",
]
_HUMAN_BIOS = [
    "just here to play {g} and chill",
    "variety streamer | {g} mostly | she/her",
    "coffee, code, and {g}",
    "dad of two, casual {g} enjoyer",
    "competitive {g} player, ex-pro",
    "",
    "art streams on weekends, games on weekdays",
    "",
]

_DEFAULT_AVATAR = "https://static-cdn.jtvnw.net/user-default-pictures-uv/abcd.png"
_REAL_AVATAR = "https://static-cdn.jtvnw.net/jtv_user_pictures/real-{n}.png"


def _rand_digits(rng: random.Random, lo: int = 2, hi: int = 5) -> str:
    return "".join(str(rng.randint(0, 9)) for _ in range(rng.randint(lo, hi)))


def _scammer(rng: random.Random) -> dict:
    style = rng.random()
    fn, sn = rng.choice(_FIRST_NAMES), rng.choice(_SURNAMES)
    if style < 0.4:
        login = f"{fn}_{sn}{_rand_digits(rng)}"
    elif style < 0.6:
        login = f"{fn}{sn}{_rand_digits(rng)}"
    elif style < 0.8:
        login = rng.choice([f"{fn}_gfx", f"gfx_{fn}", f"{fn}{sn}_gfx"])
    else:
        login = f"{rng.choice(_REAL_HANDLES)}{_rand_digits(rng, 3, 6)}"
    bio = rng.choice(_SCAM_BIOS).format(w=fn + _rand_digits(rng, 1, 3))
    return {
        "login": login,
        "display_name": login.capitalize() if rng.random() < 0.5 else f"{fn.title()}{sn.title()}",
        "description": bio,
        "account_age_days": float(rng.randint(0, 120)),
        "follower_count": None if rng.random() < 0.6 else rng.randint(0, 5),
        "follows_channel": rng.random() < 0.7,
        "follow_age_days": rng.randint(0, 3),
        "broadcaster_type": "",
        "profile_image_url": _DEFAULT_AVATAR if rng.random() < 0.8 else _REAL_AVATAR.format(n=rng.randint(1, 999)),
        "label": 1,
    }


def _human(rng: random.Random) -> dict:
    style = rng.random()
    if style < 0.6:
        login = rng.choice(_REAL_HANDLES) + (("_" + rng.choice(_GAMES)) if rng.random() < 0.3 else "")
    elif style < 0.8:
        login = f"{rng.choice(_FIRST_NAMES)}_{rng.choice(_GAMES)}"
    else:
        login = rng.choice(_FIRST_NAMES) + (_rand_digits(rng, 1, 2) if rng.random() < 0.3 else "")
    bio = rng.choice(_HUMAN_BIOS).format(g=rng.choice(_GAMES))
    bt = rng.choices(["", "affiliate", "partner"], weights=[0.45, 0.4, 0.15])[0]
    return {
        "login": login,
        "display_name": login.replace("_", " ").title() if rng.random() < 0.7 else login,
        "description": bio,
        "account_age_days": float(rng.randint(120, 3500)),
        "follower_count": None if rng.random() < 0.3 else rng.randint(5, 50000),
        "follows_channel": rng.random() < 0.4,
        "follow_age_days": rng.randint(1, 1200),
        "broadcaster_type": bt,
        "profile_image_url": _REAL_AVATAR.format(n=rng.randint(1, 999)) if rng.random() < 0.9 else _DEFAULT_AVATAR,
        "label": 0,
    }


def generate(n_per_class: int = 4000, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    rows = [_scammer(rng) for _ in range(n_per_class)] + [_human(rng) for _ in range(n_per_class)]
    rng.shuffle(rows)
    return rows
