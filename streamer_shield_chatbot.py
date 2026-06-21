import os
import sys
import signal
import asyncio
import contextlib
from datetime import datetime, timezone
from typing import Optional

import httpx
from quart import Quart, redirect, request, session
from twitchAPI.helper import first
from twitchAPI.oauth import UserAuthenticator, validate_token
from twitchAPI.twitch import Twitch, TwitchUser
from twitchAPI.eventsub.webhook import EventSubWebhook
from twitchAPI.object.eventsub import ChannelFollowEvent
from twitchAPI.type import (
    AuthScope,
    ChatEvent,
    TwitchAPIException,
    EventSubSubscriptionConflict,
    EventSubSubscriptionError,
    EventSubSubscriptionTimeout,
    TwitchBackendException,
)
from twitchAPI.chat import Chat, EventData, ChatMessage, JoinEvent, JoinedEvent, ChatCommand

from hypercorn.asyncio import serve
from hypercorn.config import Config as HyperConfig

import dashboard
import features
from config import build_twitch_config, DbConfig
from db import Database
from helix_extra import (
    LowTrustStatus,
    SUSPICIOUS_MANAGE_SCOPE,
    decide_status,
    remove_suspicious_status,
    set_suspicious_status,
)
from logger import Logger
from twitch_config import TwitchConfig

init_login: bool
twitch: Twitch
auth: UserAuthenticator


class StreamerShieldTwitch:
    global twitch
    chat: Chat
    commands: dict
    is_armed: bool

    def __init__(self, config: TwitchConfig, db: Database) -> None:
        self.__app_id = config.app_id
        self.__app_secret = config.app_secret
        self.user_scopes = config.user_scopes
        self.user_name = config.user_name
        self.is_armed = config.is_armed
        self.l = config.logger or Logger(console_log=True)
        self.db = db
        self.db_cfg = DbConfig.from_env()
        self.await_login = True
        self.even_subs = []
        self.auth_url = config.auth_url
        self.shield_url = config.shield_url
        self.eventsub_url = config.eventsub_url
        self.collect_data = config.collect_data
        self.age_threshold = config.age_threshold
        self.conf_restrict = config.conf_restrict
        self.conf_monitor = config.conf_monitor
        self.enable_cli = config.enable_cli
        self.admin = config.admin
        self.running = False
        self._stopping = False
        self._db_healthy = False
        self._shutdown_event: Optional[asyncio.Event] = None
        self.commands = {
            "help": {"help": "!help: prints all commands", "value": False, "cli_func": self.help_cli, "twt_func": self.help_twitch, "permissions": 0},
            "stop": {"help": "!stop: stops the process (Not available for Twitch)", "value": False, "cli_func": self.stop_cli, "twt_func": self.stop_twitch, "permissions": 10},
            "arm": {"help": "!arm: enables StreamerShield to restrict users", "value": False, "cli_func": self.arm_cli, "twt_func": self.arm_twitch, "permissions": 10},
            "disarm": {"help": "!disarm: stops StreamerShield from restricting users", "value": False, "cli_func": self.disarm_cli, "twt_func": self.disarm_twitch, "permissions": 5},
            "leave_me": {"help": "!leave_me: leaves this chat", "value": False, "cli_func": self.leave_cli, "twt_func": self.leave_me_twitch, "permissions": 5},
            "leave": {"help": "!leave chat_name: leaves a chat", "value": True, "cli_func": self.leave_cli, "twt_func": self.leave_twitch, "permissions": 10},
            "whitelist": {"help": "!whitelist user_name: whitelist user", "value": True, "cli_func": self.whitelist_cli, "twt_func": self.whitelist_twitch, "permissions": 5},
            "unwhitelist": {"help": "!unwhitelist user_name: removes user from whitelist", "value": True, "cli_func": self.unwhitelist_cli, "twt_func": self.unwhitelist_twitch, "permissions": 5},
            "blacklist": {"help": "!blacklist user_name: blacklist user", "value": True, "cli_func": self.blacklist_cli, "twt_func": self.blacklist_twitch, "permissions": 5},
            "unblacklist": {"help": "!unblacklist user_name: removes user from blacklist + clears their suspicious status here", "value": True, "cli_func": self.unblacklist_cli, "twt_func": self.unblacklist_twitch, "permissions": 5},
            "unrestrict": {"help": "!unrestrict user_name: clears a user's suspicious status in this channel", "value": True, "cli_func": self.unrestrict_cli, "twt_func": self.unrestrict_twitch, "permissions": 5},
            "streamershield": {"help": "!streamershield : prints info about the shield", "value": False, "cli_func": self.shield_info_cli, "twt_func": self.shield_info_twitch, "permissions": 0},
            "shield": {"help": "!shield : prints info about the shield", "value": False, "cli_func": self.shield_info_cli, "twt_func": self.shield_info_twitch, "permissions": 0},
            "pat": {"help": "!pat [user_name] : pats user", "value": True, "cli_func": self.pat_cli, "twt_func": self.pat_twitch, "permissions": 0},
            "scam": {"help": "!scam [user_name] : evaluates username, if given", "value": True, "cli_func": self.scam_cli, "twt_func": self.scam_twitch, "permissions": 0},
        }

    # ------------------------------------------------------------------ startup
    async def run(self):
        global twitch, bot_auth, id_auth
        self.l.info("Shield starting up")

        await self.db.connect(self.db_cfg)
        await self.db.init_schema()

        twitch = await Twitch(self.__app_id, self.__app_secret)
        twitch.user_auth_refresh_callback = self._on_token_refresh
        # Two authenticators share the /login/confirm callback (routed by OAuth state):
        #   bot_auth: full scopes, used once to authorize the bot account.
        #   id_auth:  no scopes, used for dashboard identity logins (streamers + admin).
        bot_auth = UserAuthenticator(twitch, TARGET_SCOPE, url=self.auth_url)
        id_auth = UserAuthenticator(twitch, [], url=self.auth_url, force_verify=False)

        # Serve OAuth + /health (Quart) on this same event loop; no second thread.
        self._shutdown_event = asyncio.Event()
        hyper = HyperConfig()
        hyper.bind = ["0.0.0.0:5000"]
        hyper.accesslog = "-"
        self._web_task = asyncio.create_task(
            serve(app, hyper, shutdown_trigger=self._shutdown_event.wait)
        )
        self._db_task = asyncio.create_task(self._db_health_loop())

        # Restore auth from a previous run so restarts are unattended.
        tokens = await self.db.load_tokens()
        if tokens:
            try:
                await twitch.set_user_authentication(
                    tokens["access_token"], TARGET_SCOPE, tokens["refresh_token"], validate=False
                )
                self.await_login = False
                self.l.passingblue("Restored user authentication from database")
            except Exception as exc:  # noqa: BLE001
                self.l.error(f"stored token unusable, awaiting web login: {exc}")

        if self.await_login:
            self.l.info(f"Awaiting initial login — open {self.auth_url.rsplit('/login', 1)[0]}/login")
        while self.await_login and not self._stopping:
            await asyncio.sleep(2)
        if self._stopping:
            return await self._shutdown()
        self.l.passingblue("Welcome home Chief!")

        self.eventsub = EventSubWebhook(self.eventsub_url, 8080, twitch, revocation_handler=self.esub_revoked)
        await self.eventsub.unsubscribe_all()
        self.eventsub.start()
        self.l.passingblue("Started EventSub")

        self.user = await first(twitch.get_users(logins=self.user_name))
        self.chat = await Chat(twitch)
        self.chat.register_event(ChatEvent.READY, self.on_ready)
        self.chat.register_event(ChatEvent.JOIN, self.on_join)
        self.chat.register_event(ChatEvent.JOINED, self.on_joined)
        self.chat.register_event(ChatEvent.MESSAGE, self.on_message)
        for command, value in self.commands.items():
            self.chat.register_command(command, value["twt_func"])
        self.chat.start()
        self.running = True

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, self._request_shutdown)

        if self.enable_cli and sys.stdin and sys.stdin.isatty():
            await self.cli_run()
        else:
            self.l.info("Running headless; send SIGTERM to stop")
            await self._shutdown_event.wait()
        await self._shutdown()

    def _request_shutdown(self):
        self.l.warning("Shutdown requested")
        self._stopping = True
        self.running = False
        if self._shutdown_event is not None:
            self._shutdown_event.set()

    async def _shutdown(self):
        self.running = False
        with contextlib.suppress(Exception):
            await self.chat.stop()
        with contextlib.suppress(Exception):
            await self.eventsub.stop()
        with contextlib.suppress(Exception):
            await twitch.close()
        with contextlib.suppress(Exception):
            await self.db.close()
        if self._shutdown_event is not None:
            self._shutdown_event.set()
        self.l.fail("StreamerShield stopped")

    async def _db_health_loop(self):
        while not self._stopping:
            self._db_healthy = await self.db.ping()
            await asyncio.sleep(15)

    async def _on_token_refresh(self, token: str, refresh_token: str):
        """Persist refreshed tokens so restarts don't require a new web login."""
        scopes = " ".join(s.value for s in TARGET_SCOPE)
        with contextlib.suppress(Exception):
            await self.db.save_tokens(token, refresh_token, scopes)
        self.l.info("Persisted refreshed user token")

    async def esub_revoked(self, diction: dict):
        self.l.error(f"EventSub was revoked {diction}")

    # ----------------------------------------------------------------- CLI glue
    async def command_handler(self, command: str):
        parts = command.split(" ")
        if parts[0] == "":
            return
        if parts[0] not in self.commands.keys():
            self.l.error(f"Command {parts[0]} unknown")
            return
        if self.commands[parts[0]]["value"]:
            await self.commands[parts[0]]["cli_func"](parts[0])
            return
        await self.commands[parts[0]]["cli_func"]()

    async def cli_run(self):
        while self.running:
            try:
                com = await asyncio.to_thread(input, "type help for available commands\n")
                await self.command_handler(com)
            except (EOFError, KeyboardInterrupt):
                self._request_shutdown()
                return
            except Exception as exc:  # noqa: BLE001
                self.l.error(f"Exception in cli_run: {exc}")

    async def shield_info_cli(self):
        self.l.info("StreamerShield is the AI ChatBot to rid twitch of scammers. https://linktr.ee/caesarlp")

    async def help_cli(self):
        for _, value in self.commands.items():
            self.l.passing(f'{value["help"]}')

    async def stop_cli(self):
        self._request_shutdown()

    async def arm_cli(self):
        self.l.warning("Armed StreamerShield")
        self.is_armed = True

    async def disarm_cli(self):
        self.l.warning("Disarmed StreamerShield")
        self.is_armed = False

    def _channel_defaults(self) -> dict:
        """Global config values used to seed a newly added channel's settings."""
        return {
            "is_armed": self.is_armed,
            "collect_data": self.collect_data,
            "age_threshold": self.age_threshold,
            "conf_restrict": self.conf_restrict,
            "conf_monitor": self.conf_monitor,
        }

    async def join_chat(self, name: str):
        global twitch
        name = name.lower()
        unable_to_join = await self.chat.join_room(name)
        if unable_to_join:
            self.l.error(f"Unable to join {name}: {unable_to_join}")
            return f"Unable to join {name}: {unable_to_join}"
        user = await first(twitch.get_users(logins=name))
        if user is None:
            self.l.error(f"Could not look up user {name}")
            return f"Could not find Twitch user {name}"
        # Register the channel regardless of mod status: it starts observe-only
        # (is_armed follows config, default off) so self-service onboarding works
        # before the streamer mods the bot. Restrict/monitor activate once modded.
        await self.db.add_channel(name, broadcaster_id=user.id, defaults=self._channel_defaults())
        with contextlib.suppress(Exception):
            await self.new_follow_esub(user.id)
        if self.chat.is_mod(name):
            self.l.passing(f"Successfully joined {name}")
            return f"Successfully joined {name}"
        self.l.warning(f"Joined {name} without mod status")
        return f"Joined {name}. Make @{self.user_name} a moderator to enable restrict/monitor."

    async def new_follow_esub(self, id: str):
        try:
            self.l.info("Initializing Follow ESub")
            await self.eventsub.listen_channel_follow_v2(id, self.user.id, self.on_follow)
        except EventSubSubscriptionConflict as e:
            self.l.error(f"EventSubSubscriptionConflict {e}")
        except EventSubSubscriptionTimeout as e:
            self.l.error(f"EventSubSubscriptionTimeout {e}")
        except EventSubSubscriptionError as e:
            self.l.error(f"EventSubSubscriptionError {e}")
        except TwitchBackendException as e:
            self.l.error(f"TwitchBackendException {e}")

    async def leave_cli(self, name: str):
        await self.chat.leave_room(name)
        await self.db.remove_channel(name)
        self.l.passing(f"Left {name}")

    async def whitelist_cli(self, name: str):
        await self.db.add_to_list("whitelist", name)
        self.l.passing(f"Whitelisted {name}")

    async def unwhitelist_cli(self, name: str):
        await self.db.remove_from_list("whitelist", name)
        self.l.passing(f"Unwhitelisted {name}")

    async def blacklist_cli(self, name: str):
        await self.db.add_to_list("blacklist", name)
        self.l.passing(f"Blacklisted {name}")

    async def unblacklist_cli(self, name: str):
        await self.db.remove_from_list("blacklist", name)
        self.l.passing(f"Unblacklisted {name}")

    async def scam_cli(self, name: str):
        conf = await self._score_name(name)
        self.l.info(f"User {name} returns conf {conf}")

    async def pat_cli(self, name: str):
        self.l.passingblue("You're a good boi!")

    # ----------------------------------------------------------- Twitch commands
    async def shield_info_twitch(self, chat_command: ChatCommand):
        await chat_command.reply("StreamerShield is the AI ChatBot to rid twitch of scammers. https://linktr.ee/caesarlp")

    async def help_twitch(self, chat_command: ChatCommand):
        permission = await self.generate_permissions(chat_command)
        reply = ""
        for _, value in self.commands.items():
            if permission < value["permissions"]:
                continue
            if len(reply) + len(f'{value["help"]}; ') > 255:
                await chat_command.reply(reply)
                reply = ""
            reply += f'{value["help"]}; '
        await chat_command.reply(reply)

    async def stop_twitch(self, chat_command: ChatCommand):
        if await self.verify_permission(chat_command, "disarm"):
            await chat_command.reply("StreamerShield can only be shut down via cli")

    async def arm_twitch(self, chat_command: ChatCommand):
        if await self.verify_permission(chat_command, "arm"):
            await self.db.update_channel_settings(chat_command.room.name, is_armed=True)
            await chat_command.reply("Armed StreamerShield for this channel")
            self.l.warning(f"Armed {chat_command.room.name}")

    async def disarm_twitch(self, chat_command: ChatCommand):
        if await self.verify_permission(chat_command, "disarm"):
            await self.db.update_channel_settings(chat_command.room.name, is_armed=False)
            await chat_command.reply("Disarmed StreamerShield for this channel")
            self.l.warning(f"Disarmed {chat_command.room.name}")

    async def leave_me_twitch(self, chat_command: ChatCommand):
        if await self.verify_permission(chat_command, "leave_me") and (not chat_command.parameter == chat_command.room.name):
            await chat_command.reply("Leaving... Bye!")
            await self.db.remove_channel(chat_command.parameter)
            await self.chat.leave_room(chat_command.parameter)

    async def leave_twitch(self, chat_command: ChatCommand):
        if await self.verify_permission(chat_command, "leave") and (not chat_command.parameter == chat_command.room.name):
            await chat_command.reply("Leaving... Bye!")
            await self.db.remove_channel(chat_command.parameter)
            await self.chat.leave_room(chat_command.parameter)

    async def whitelist_twitch(self, chat_command: ChatCommand):
        if await self.verify_permission(chat_command, "whitelist"):
            name = chat_command.parameter.replace("@", "")
            await self.db.add_to_list("whitelist", name)
            await chat_command.reply(f"User {name} is now whitelisted")

    async def unwhitelist_twitch(self, chat_command: ChatCommand):
        if await self.verify_permission(chat_command, "unwhitelist"):
            name = chat_command.parameter.replace("@", "")
            await self.db.remove_from_list("whitelist", name)
            await chat_command.reply(f"User {name} is no longer whitelisted")

    async def blacklist_twitch(self, chat_command: ChatCommand):
        if await self.verify_permission(chat_command, "blacklist"):
            name = chat_command.parameter.replace("@", "")
            await self.db.add_to_list("blacklist", name)
            await chat_command.reply(f"User {name} is now blacklisted")

    async def unblacklist_twitch(self, chat_command: ChatCommand):
        if await self.verify_permission(chat_command, "unblacklist"):
            name = chat_command.parameter.replace("@", "")
            await self.db.remove_from_list("blacklist", name)
            await self._remove_suspicious(chat_command.room.room_id, name)
            await chat_command.reply(f"User {name} is no longer blacklisted")

    async def unrestrict_cli(self, name: str):
        self.l.warning("unrestrict needs a channel context; use a chat command or the dashboard")

    async def unrestrict_twitch(self, chat_command: ChatCommand):
        if await self.verify_permission(chat_command, "unrestrict"):
            name = chat_command.parameter.replace("@", "")
            ok = await self._remove_suspicious(chat_command.room.room_id, name)
            await chat_command.reply(
                f"Cleared suspicious status for {name}" if ok else f"Could not clear status for {name}"
            )

    async def scam_twitch(self, chat_command: ChatCommand):
        name = chat_command.parameter.replace("@", "") if chat_command.parameter else chat_command.user.name
        conf = await self._score_name(name, chat_command.room.room_id)
        if conf is None:
            await chat_command.reply(f"Could not evaluate @{name}")
            return
        await chat_command.reply(f"@{name} is to {round(conf * 100)}% a scammer")

    async def pat_twitch(self, chat_command: ChatCommand):
        self_pat = not chat_command.parameter
        name = chat_command.user.name if self_pat else chat_command.parameter.replace("@", "")
        pats = await self.db.incr_setting("pat_count")
        if self_pat:
            await chat_command.reply(f"You just gave yourself a pat on the back! well deserved LoveYourself {pats} pats given")
            return
        await chat_command.reply(f"@{chat_command.user.name} gives @{name} a pat! peepoPat {pats} pats given")

    # --------------------------------------------------------- events & checking
    async def on_ready(self, ready_event: EventData):
        channels = await self.db.all_channels()
        channels.append(self.chat.username)
        await ready_event.chat.join_room(channels)
        for channel in channels:
            user = await first(twitch.get_users(logins=[channel]))
            await self.db.set_channel_id(channel, user.id)
            try:
                await self.new_follow_esub(user.id)
                self.l.info(f"Follow ESub for {user.login} initialized")
            except Exception:
                self.l.error(f"Follow ESub for {channel} not initialized")

    async def on_joined(self, joined_event: JoinedEvent):
        await joined_event.chat.send_message(joined_event.room_name, "This Chat is now protected with StreamerShield! protecc")

    async def on_message(self, msg: ChatMessage):
        name = msg.user.name
        if msg.user.mod or msg.user.vip or msg.user.subscriber or msg.user.turbo:
            await self.db.add_to_list("whitelist", name)
            return
        await self.check_user(name, msg.room.room_id)

    async def on_join(self, join_event: JoinEvent):
        await self.check_user(join_event.user_name, join_event.room.room_id)

    async def on_follow(self, data: ChannelFollowEvent):
        name = data.event.user_name
        self.l.passing(f"New follow: {name}")
        await self.check_user(name, data.event.broadcaster_user_id)

    async def check_user(self, name: str, channel_id):
        if await self.db.is_listed("whitelist", name):
            self.l.info(f"{name} is found in whitelist")
            return
        user = await first(twitch.get_users(logins=name))
        if user is None:
            self.l.error(f"Could not look up user {name}")
            return

        # Effective settings are per-channel; fall back to the global config defaults.
        cs = await self.db.get_channel_by_id(channel_id)
        armed = cs["is_armed"] if cs else self.is_armed
        collect = cs["collect_data"] if cs else self.collect_data
        age_threshold = cs["age_threshold"] if cs else self.age_threshold
        conf_restrict = cs["conf_restrict"] if cs else self.conf_restrict
        conf_monitor = cs["conf_monitor"] if cs else self.conf_monitor

        if await self.db.is_listed("blacklist", name):
            self.l.warning(f"{name} is found in blacklist")
            if armed:
                await self._apply_suspicious(channel_id, user.id, LowTrustStatus.RESTRICTED)
            await self._maybe_record(user, channel_id, None, None, "blacklisted", collect)
            return

        payload = await self._gather(user, channel_id)
        conf = await self.request_prediction(payload)
        if conf is None:
            self.l.error(f"No prediction for {name}; skipping")
            await self._maybe_record(user, channel_id, payload, None, "prediction_failed", collect)
            return

        if payload["account_age_days"] >= age_threshold * 30:
            self.l.passing(f"{name} older than {age_threshold} months (conf {conf:.2f}); trusted")
            await self._maybe_record(user, channel_id, payload, conf, "aged_out", collect)
            return

        status = decide_status(conf, conf_restrict, conf_monitor)
        if status != LowTrustStatus.NONE and armed:
            ok = await self._apply_suspicious(channel_id, user.id, status)
            action = status if ok else f"{status}_failed"
        elif status != LowTrustStatus.NONE:
            action = f"unarmed_{status}"  # would have acted, but the channel is disarmed
        else:
            action = LowTrustStatus.NONE

        if status != LowTrustStatus.NONE:
            self.l.warning(f"{name} conf {conf:.2f} -> {action}")
        else:
            self.l.passing(f"{name} conf {conf:.2f} -> human")
        await self._maybe_record(user, channel_id, payload, conf, action, collect)

    async def _apply_suspicious(self, broadcaster_id, user_id, status) -> bool:
        ok = await set_suspicious_status(twitch, str(broadcaster_id), self.user.id, str(user_id), status, logger=self.l)
        if ok:
            self.l.fail(f"Set suspicious status '{status}' on {user_id} in {broadcaster_id}")
        return ok

    async def _remove_suspicious(self, broadcaster_id, name) -> bool:
        user = await first(twitch.get_users(logins=name))
        if user is None:
            return False
        ok = await remove_suspicious_status(twitch, str(broadcaster_id), self.user.id, str(user.id), logger=self.l)
        if ok:
            self.l.passing(f"Cleared suspicious status on {name} in {broadcaster_id}")
        return ok

    async def _gather(self, user: TwitchUser, channel_id) -> dict:
        """Build the JSON-safe prediction payload from a Twitch user + follow signal."""
        follows, follow_age = await self._follow_signal(channel_id, user.id)
        return {
            "login": user.login,
            "display_name": user.display_name,
            "description": user.description,
            "account_age_days": features.account_age_days(user.created_at),
            "follower_count": await self._best_effort_follower_count(user.id),
            "follows_channel": follows,
            "follow_age_days": follow_age,
            "broadcaster_type": user.broadcaster_type,
            "profile_image_url": user.profile_image_url,
            "has_default_avatar": features.has_default_avatar(user.profile_image_url),
        }

    async def _follow_signal(self, channel_id, user_id):
        """Does this user follow the protected channel, and for how long? (bot is a mod there)."""
        try:
            res = await twitch.get_channel_followers(broadcaster_id=str(channel_id), user_id=str(user_id))
            if res.total and res.total >= 1 and res.data:
                age = (datetime.now(timezone.utc) - res.data[0].followed_at).days
                return True, max(0, age)
            return False, None
        except Exception as exc:  # noqa: BLE001
            self.l.warning(f"follow signal unavailable for {user_id}: {exc}")
            return None, None

    async def _best_effort_follower_count(self, user_id) -> Optional[int]:
        """The suspect's own follower count — only obtainable where we mod their channel."""
        try:
            res = await twitch.get_channel_followers(broadcaster_id=str(user_id))
            return res.total
        except Exception:  # noqa: BLE001 - expected for arbitrary users
            return None

    async def _score_name(self, name: str, channel_id=None) -> Optional[float]:
        user = await first(twitch.get_users(logins=name))
        if user is None:
            return None
        return await self.request_prediction(await self._gather(user, channel_id))

    async def _maybe_record(self, user, channel_id, payload, conf, action, collect=None):
        if collect is None:
            collect = self.collect_data
        if not collect:
            return
        obs = {
            "twitch_user_id": user.id,
            "login": user.login,
            "display_name": user.display_name,
            "description": user.description,
            "account_created_at": user.created_at,
            "broadcaster_type": user.broadcaster_type,
            "profile_image_url": user.profile_image_url,
            "has_default_avatar": features.has_default_avatar(user.profile_image_url),
            "model_confidence": conf,
            "action_taken": action,
            "is_armed": self.is_armed,
            "channel_id": str(channel_id),
        }
        if payload is not None:
            obs.update(
                follower_count=payload["follower_count"],
                follows_channel=payload["follows_channel"],
                follow_age_days=payload["follow_age_days"],
            )
        with contextlib.suppress(Exception):
            await self.db.record_observation(obs)

    async def request_prediction(self, payload: dict) -> Optional[float]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self.shield_url, json=payload)
                resp.raise_for_status()
                return float(resp.json()["result"])
        except Exception as exc:  # noqa: BLE001
            self.l.error(f"prediction request failed: {exc}")
            return None

    # --------------------------------------------------------------- permissions
    async def generate_permissions(self, chat_command: ChatCommand):
        if chat_command.user.name == self.admin:
            return 10
        if chat_command.user.mod or chat_command.user.name == chat_command.room.name:
            return 5
        return 0

    async def verify_permission(self, chat_command: ChatCommand, command: str):
        permission = await self.generate_permissions(chat_command)
        return self.commands[command]["permissions"] <= permission


app = Quart(__name__)
chat_bot: StreamerShieldTwitch
TARGET_SCOPE: list
bot_auth: UserAuthenticator
id_auth: UserAuthenticator
app.secret_key = os.environ.get("FLASK_SECRET", "streamer-shield-dev-secret")


def _session_login():
    return session.get("login")


def _is_admin() -> bool:
    return _session_login() == (chat_bot.admin or "").lower()


def _can_manage(channel_login: str) -> bool:
    return _is_admin() or (_session_login() == (channel_login or "").lower())


def _int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _float(v, default):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


async def _set_session_from_token(token: str):
    info = await validate_token(token, auth_base_url=twitch.auth_base_url)
    session["login"] = (info.get("login") or "").lower()
    session["user_id"] = info.get("user_id")


async def _ensure_channel_onboarded(login: str):
    """Self-service onboarding: a streamer's first login registers their channel.

    Removes the admin bottleneck — no manual add step. The admin logs in for
    identity only, so they're skipped. Failures must not block login, so the
    join is best-effort; the streamer can retry from the dashboard button.
    """
    if not login or login == (chat_bot.admin or "").lower():
        return
    if await chat_bot.db.get_channel_by_login(login):
        return
    with contextlib.suppress(Exception):
        await chat_bot.join_chat(login)


@app.route("/health")
async def health():
    # Readiness gates Service membership, and the Service is how the one-time OAuth
    # login (/login) and EventSub webhooks reach this pod. So readiness must report
    # ready as soon as the web server is serving (it answered this probe) and the DB
    # is reachable — it must NOT wait for the post-login `running` flag. Gating on
    # `running` deadlocks: unready pod -> excluded from the Service -> /login
    # unreachable -> admin can never log in -> `running` never set -> never ready.
    ok = getattr(chat_bot, "_db_healthy", False)
    return ("", 200) if ok else ("not ready", 503)


@app.route("/login")
def login():
    # First-time setup: the bot account authorizes itself (full scopes). Afterwards
    # everyone (streamers + admin) logs in for identity only (no scopes).
    if getattr(chat_bot, "await_login", False):
        return redirect(bot_auth.return_auth_url())
    return redirect(id_auth.return_auth_url())


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.route("/login/confirm")
async def login_confirm():
    state = request.args.get("state")
    code = request.args.get("code")
    if code is None:
        return "Missing code", 400
    try:
        if chat_bot.await_login and state == bot_auth.state:
            token, refresh = await bot_auth.authenticate(user_token=code)
            await twitch.set_user_authentication(token, TARGET_SCOPE, refresh, validate=False)
            await chat_bot.db.save_tokens(token, refresh, " ".join(s.value for s in TARGET_SCOPE))
            chat_bot.await_login = False
            await _set_session_from_token(token)
            return redirect("/")
        if state == id_auth.state:
            token, _ = await id_auth.authenticate(user_token=code)
            await _set_session_from_token(token)
            await _ensure_channel_onboarded(session.get("login"))
            return redirect("/")
    except TwitchAPIException:
        return "Failed to generate auth token", 400
    return "Bad state", 401


@app.route("/")
async def index():
    user = _session_login()
    if not user:
        return dashboard.render_landing()
    if _is_admin():
        channels = await chat_bot.db.list_channels()
        wl = await chat_bot.db.list_all("whitelist")
        bl = await chat_bot.db.list_all("blacklist")
        obs = await chat_bot.db.recent_observations(limit=50)
        return dashboard.render_admin(user, channels, wl, bl, obs)
    channel = await chat_bot.db.get_channel_by_login(user)
    if not channel:
        return dashboard.render_no_channel(user)
    obs = await chat_bot.db.recent_observations(channel_id=channel.get("broadcaster_id"), limit=50)
    return dashboard.render_streamer(user, channel, obs)


@app.route("/channel/settings", methods=["POST"])
async def channel_settings():
    if not _session_login():
        return redirect("/login")
    form = await request.form
    channel = (form.get("channel") or "").lower()
    if not _can_manage(channel):
        return "Forbidden", 403
    await chat_bot.db.update_channel_settings(
        channel,
        is_armed=form.get("is_armed") is not None,
        collect_data=form.get("collect_data") is not None,
        age_threshold=_int(form.get("age_threshold"), 6),
        conf_restrict=_float(form.get("conf_restrict"), 0.9),
        conf_monitor=_float(form.get("conf_monitor"), 0.5),
    )
    return redirect("/")


@app.route("/channel/leave", methods=["POST"])
async def channel_leave():
    if not _session_login():
        return redirect("/login")
    form = await request.form
    channel = (form.get("channel") or "").lower()
    if not _can_manage(channel):
        return "Forbidden", 403
    with contextlib.suppress(Exception):
        await chat_bot.chat.leave_room(channel)
    await chat_bot.db.remove_channel(channel)
    return redirect("/")


@app.route("/channel/join", methods=["POST"])
async def channel_join():
    # Self-service: a streamer (re)adds their own channel. Auto-onboarding at login
    # covers the common case; this is the dashboard fallback / retry. Admins may add
    # any channel; everyone else only their own, enforced by _can_manage.
    user = _session_login()
    if not user:
        return redirect("/login")
    form = await request.form
    channel = (form.get("channel") or user).strip().lower()
    if not _can_manage(channel):
        return "Forbidden", 403
    await chat_bot.join_chat(channel)
    return redirect("/")


@app.route("/admin/add-channel", methods=["POST"])
async def admin_add_channel():
    if not _is_admin():
        return "Forbidden", 403
    form = await request.form
    channel = (form.get("channel") or "").strip().lower()
    if channel:
        await chat_bot.join_chat(channel)
    return redirect("/")


@app.route("/admin/list", methods=["POST"])
async def admin_list():
    if not _is_admin():
        return "Forbidden", 403
    form = await request.form
    kind = form.get("kind")
    action = form.get("action")
    entry = (form.get("login") or "").strip()
    if kind in ("whitelist", "blacklist") and entry:
        if action == "add":
            await chat_bot.db.add_to_list(kind, entry)
        elif action == "remove":
            await chat_bot.db.remove_from_list(kind, entry)
    return redirect("/")


@app.route("/observation/unrestrict", methods=["POST"])
async def observation_unrestrict():
    if not _session_login():
        return redirect("/login")
    form = await request.form
    channel_id = form.get("channel_id")
    user_login = (form.get("login") or "").strip()
    ch = await chat_bot.db.get_channel_by_id(channel_id) if channel_id else None
    owner = ch["login"] if ch else None
    if not (_is_admin() or (owner and _session_login() == owner)):
        return "Forbidden", 403
    if channel_id and user_login:
        await chat_bot._remove_suspicious(channel_id, user_login)
    return redirect("/")


def _build_target_scope():
    return [
        AuthScope.CHAT_READ,
        AuthScope.CHAT_EDIT,
        AuthScope.MODERATOR_READ_CHATTERS,
        AuthScope.MODERATOR_READ_FOLLOWERS,
        AuthScope.MODERATOR_READ_SUSPICIOUS_USERS,
        SUSPICIOUS_MANAGE_SCOPE,
    ]


if __name__ == "__main__":
    logger = Logger(console_log=True)
    config = build_twitch_config(logger)
    TARGET_SCOPE = _build_target_scope()
    config.user_scopes = TARGET_SCOPE
    database = Database(logger)
    chat_bot = StreamerShieldTwitch(config, database)
    asyncio.run(chat_bot.run())
