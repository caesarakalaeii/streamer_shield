# ADR 0001: Readiness is independent of the OAuth login state

- Status: Accepted
- Date: 2026-06-21

## Context

The bot pod serves its OAuth login flow (`/login`, `/login/confirm`) and the
Twitch EventSub webhook over HTTP on port 5000, exposed publicly through the
`streamer-shield-bot-service` Service and the nginx Ingress at
`shield.caes.ar` / `eventsub.caes.ar`.

Twitch user authentication is required before the bot can join chat. The bot
already persists the user access/refresh tokens in Postgres (`auth_tokens`,
`db.save_tokens`/`load_tokens`) and restores them on startup
(`StreamerShieldTwitch.run`), so a pod that has tokens comes up unattended. The
admin only needs to log in **once**, the very first time, via
`https://shield.caes.ar/login`.

The readiness probe was wired to `/health`, which returned `200` only after
`running` became `True` — and `running` is set *after* the one-time login
completes. This created a deadlock for the first login:

1. New pod starts, awaiting login → `/health` returns `503` → pod is **not Ready**.
2. A Kubernetes Service only routes to Ready endpoints, so the pod is excluded.
3. The Ingress therefore cannot route `shield.caes.ar/login` to the new pod.
4. The admin can never reach the pod to complete the login → `running` is never
   set → the pod is never Ready.

In practice the admin's login landed on whatever older, already-Ready pod was
still in the Service, so the new pod was stranded and every rollout appeared to
"need a login again."

## Decision

Readiness reports ready as soon as the web server is serving (it answered the
probe) and the database is reachable (`_db_healthy`). It does **not** wait for
the post-login `running` flag.

```python
@app.route("/health")
async def health():
    ok = getattr(chat_bot, "_db_healthy", False)
    return ("", 200) if ok else ("not ready", 503)
```

Liveness stays a `tcpSocket` check (unchanged) so a pod awaiting login is not
SIGKILLed in a crash loop.

## Consequences

- The pod joins the Service while still awaiting the first login, so the admin
  can actually reach `/login` and complete the one-time authorization.
- Once that first login is persisted to Postgres, subsequent restarts restore
  the token at startup and never prompt again — restarts are unattended.
- Readiness no longer signals "the bot is in chat." That operational state is
  tracked by `running` but is not a traffic-routing concern: the pod's inbound
  HTTP (login + EventSub) must be reachable regardless. If a "fully operational"
  signal is later needed (e.g. for dashboards), add a separate `/status`
  endpoint rather than re-coupling it to readiness.
- A Service backed by a pod that is awaiting login will briefly route EventSub
  callbacks to a not-yet-running bot; this only occurs in the one-time
  pre-first-login window and is acceptable.
