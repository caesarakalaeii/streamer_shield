"""Retrain the multi-feature model from labelled observations in Postgres.

This is the real training path once data has been collected. Rows are labelled by
setting ``observations.label`` (0/1) — e.g. with a repurposed classification_helper
or a manual SQL update / review UI.

Run in an environment with BOTH asyncpg and tensorflow available (the dev venv plus
``pip install tensorflow-cpu``, or a combined image). DB connection comes from the
same env vars as the bot (DB_HOST, DB_USER, ...).

    python train_from_db.py --min-rows 500 --out streamershield.keras
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone

import features
from config import DbConfig

_QUERY = """
SELECT login, display_name, description, account_created_at, follower_count,
       follows_channel, follow_age_days, broadcaster_type, has_default_avatar, label
FROM observations
WHERE label IS NOT NULL
"""


async def fetch_rows() -> list[dict]:
    import asyncpg

    cfg = DbConfig.from_env()
    pool = await asyncpg.create_pool(
        host=cfg.host, port=cfg.port, user=cfg.user, password=cfg.password,
        database=cfg.name, ssl=cfg.ssl(),
    )
    try:
        recs = await pool.fetch(_QUERY)
    finally:
        await pool.close()

    now = datetime.now(timezone.utc)
    rows: list[dict] = []
    for r in recs:
        rows.append(
            {
                "login": r["login"],
                "display_name": r["display_name"],
                "description": r["description"],
                "account_age_days": features.account_age_days(r["account_created_at"], now),
                "follower_count": r["follower_count"],
                "follows_channel": r["follows_channel"],
                "follow_age_days": r["follow_age_days"],
                "broadcaster_type": r["broadcaster_type"],
                "has_default_avatar_value": r["has_default_avatar"],
                "label": int(r["label"]),
            }
        )
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="streamershield.keras")
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--min-rows", type=int, default=500)
    args = ap.parse_args()

    rows = asyncio.run(fetch_rows())
    pos = sum(r["label"] for r in rows)
    print(f"fetched {len(rows)} labelled rows ({pos} scammers / {len(rows) - pos} humans)")
    if len(rows) < args.min_rows:
        raise SystemExit(
            f"only {len(rows)} labelled rows (< --min-rows {args.min_rows}); "
            "collect/label more before retraining."
        )

    from streamer_shield_train import train_from_rows

    train_from_rows(rows, model_path=args.out, epochs=args.epochs)


if __name__ == "__main__":
    main()
