# ADR 0002: Self-service channel onboarding

- Status: Accepted
- Date: 2026-06-21

## Context

Adding a channel to StreamerShield was admin-only. A streamer who logged in with
their own Twitch account landed on a dead-end page telling them to "ask the admin
to add it" (`dashboard.render_no_channel`). The only code path that registered a
channel was `/admin/add-channel`, gated on `_is_admin()`.

Worse, `join_chat` only persisted the channel to the `channels` table **if the bot
was already a moderator** in that channel. A brand-new streamer has not modded the
bot yet, so even a hypothetical self-service click would have silently failed to
register them.

This admin bottleneck does not scale and is poor UX: onboarding a streamer required
out-of-band coordination with an operator.

## Decision

Onboarding is self-service and automatic at login.

1. **`join_chat` registers the channel regardless of mod status.** It joins the
   chat room, looks up the broadcaster, and writes the channel to the DB
   (observe-only by default — `is_armed` follows config, default off). Follow
   EventSub is attempted best-effort. If the bot is not yet a mod, the returned
   message asks the streamer to mod the bot to enable restrict/monitor.

2. **`_ensure_channel_onboarded(login)` runs at login.** When an identity login
   (`id_auth`) completes in `/login/confirm`, a non-admin whose channel is not yet
   registered is auto-onboarded via `join_chat`. The admin logs in for identity
   only and is skipped. The call is best-effort (wrapped so a failure never blocks
   login).

3. **`POST /channel/join` is a self-service fallback.** The no-channel page now
   shows a "Protect my channel" button instead of "ask the admin." The route lets
   a user (re)add their own channel; `_can_manage` restricts non-admins to their
   own login. The admin add-channel route is unchanged.

## Consequences

- A streamer logging in for the first time is registered automatically and lands on
  their own channel dashboard; no operator involvement.
- Channels are registered in observe-only mode before the bot is modded, so the
  dashboard and settings work immediately; restrict/monitor activate once the
  streamer mods the bot. This also fixes the prior bug where non-modded channels
  were silently not persisted.
- The admin add-channel flow still exists for adding arbitrary channels.
- A streamer can self-register any channel they own; they cannot add channels they
  don't control (enforced by `_can_manage`).
