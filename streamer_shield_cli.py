import asyncio
import json
import os
import numpy as np
from logger import Logger
from config import APP_SECRET, APP_ID, TWITCH_USER
from twitchAPI.helper import first
from twitchAPI.twitch import Twitch
from streamer_shield import StreamerShield
from twitchAPI.object.eventsub import ChannelFollowEvent
from twitchAPI.eventsub.websocket import EventSubWebsocket
from twitchAPI.type import AuthScope, ChatEvent
from twitchAPI.oauth import UserAuthenticator,UserAuthenticationStorageHelper
from twitchAPI.chat import Chat, EventData, ChatMessage, JoinEvent, JoinedEvent, ChatCommand

class TwitchConfig:
    app_id : str
    app_secret : str      
    user_scopes : [AuthScope]
    white_list_location : str
    black_list_location : str
    channel : str
    model_path : str = 'shield.h5'
    ban_reason : str = '''You've been banned by StreamerShield, if you think the was an Error, please make an unban request'''
    max_lenght : int = 30 #should be kept at 30, as the model was trained with it
    scammer_threshold : int = 0.5 #only used for test function, not used for evaluation, yet
    user_threshold : int = 0.5 #only used for test function, not used for evaluation, yet
    logger : Logger = Logger(console_log=True,
                             file_logging=True,
                             file_URI="logs/streamer_shield.log",
                             override=True)
    
    


class StreamerShieldTwitch:
    twitch : Twitch
    chat : Chat
    
    
    def __init__(self, config : TwitchConfig) -> None:
        self.__app_id = config.app_id
        self.__app_secret = config.app_secret
        self.user_scopes = config.user_scopes
        self.channel = config.channel
        self.white_list = config.white_list_location
        self.black_list = config.black_list_location
        self.ban_reason = config.ban_reason
        self.ss = StreamerShield(config.model_path,
                                 config.max_lenght,
                                 config.scammer_threshold,
                                 config.user_threshold)
        pass
    
    async def run(self):
        self.twitch = await Twitch(self.__app_id, self.__app_secret)

        target_scope = self.user_scopes
        helper = UserAuthenticationStorageHelper(self.twitch, self.user_scopes)
        await helper.bind()
        auth = UserAuthenticator(self.twitch, target_scope, force_verify=False)
        # this will open your default browser and prompt you with the twitch verification website
        token, refresh_token = await auth.authenticate()
        # add User authentication
        await self.twitch.set_user_authentication(token, target_scope, refresh_token)
        self.user = await first(self.twitch.get_users(logins=self.channel))
        
        self.chat = await Chat(self.twitch)

        # register the handlers for the events you want

        # listen to when the bot is done starting up and ready to join channels
        self.chat.register_event(ChatEvent.READY, self.on_ready)
        # listen to chat join events (might not trigger, depending channel size)
        self.chat.register_event(ChatEvent.JOIN, self.on_join)
        # listen to chat messages
        self.chat.register_event(ChatEvent.MESSAGE, self.on_message)
        # we are done with our setup, lets start this bot up!
        self.chat.register_command("whitelist", self.white_list_user)
        self.chat.register_command("blacklist", self.black_list_user)
        self.chat.register_command("unwhitelist", self.un_white_list_user)
        self.chat.register_command("unblacklist", self.un_black_list_user)
        self.chat.start()
        
        self.eventsub = EventSubWebsocket(self.twitch)
        self.eventsub.start()
        await self.eventsub.listen_channel_follow_v2(self.user.id, self.user.id, self.on_follow)
        
        
        try:
            input('press Enter to shut down...')
        except KeyboardInterrupt:
            pass
        finally:
            # stopping both eventsub as well as gracefully closing the connection to the API
            print("shutting down")
            await self.eventsub.stop()
            await self.twitch.close()
    
    
    async def on_ready(self,ready_event: EventData):
        await ready_event.chat.join_room(self.channel)
    
    async def on_joined(self, joined_event: JoinedEvent):
        await joined_event.chat.send_message(self.channel, "This Chat is now protected wit StreamerShield")
        
    async def on_message(self, msg : ChatMessage):
        name = msg.user.name
        await self.check_user(name)
        
    async def on_join(self, join_event : JoinEvent):
        name = join_event.user_name
        await self.check_user(name)
        
    async def on_follow(self, data: ChannelFollowEvent):
        name = data.event.user_name
        await self.check_user(name)
            
    async def check_user(self, name :str):
        if await self.check_white_list(name): 
            print("Whitelisted user found")
            return
        if await self.check_black_list(name): 
            print("Banned user found")
            return
            #self.twitch.ban_user(self.channel_id, self.channel_id, user.id, self.ban_reason)
        conf = self.ss.predict(name)
        if (bool(np.round(conf))):
            user = await first(self.twitch.get_users(logins=name))
            print(f'User {name} was classified as a scammer with conf {conf}')
            return
            #self.twitch.ban_user(self.channel_id, self.channel_id, user.id, self.ban_reason)
        print(f'User {name} was classified as a user with conf {conf}')
            
        
    async def user_refresh(token: str, refresh_token: str):
        print(f'my new user token is: {token}')

    async def app_refresh(token: str):
        print(f'my new app token is: {token}')
        
    async def white_list_user(self, chat_command : ChatCommand):
        if chat_command.user.mod or chat_command.user.name == self.channel:
            name = chat_command.parameter.replace(' ', '')
            self.list_update(name, self.white_list)
            await chat_command.reply(f'User {name} is now whitelisted')
        
    async def un_white_list_user(self, chat_command : ChatCommand):
        if chat_command.user.mod or chat_command.user.name == self.channel:
            name = chat_command.parameter.replace(' ', '')
            self.list_update(name, self.white_list, remove = True)
            await chat_command.reply(f'User {name} is no longer whitelisted')
        
    async def check_white_list(self, name):
        return self.check_list(name, self.white_list)
        
    async def black_list_user(self, chat_command : ChatCommand):
        if chat_command.user.mod or chat_command.user.name == self.channel:
            name = chat_command.parameter.replace(' ', '')
            self.list_update(name, self.black_list)
            await chat_command.reply(f'User {name} is now blacklisted')
        
    async def un_black_list_user(self, chat_command : ChatCommand):
        if chat_command.user.mod or chat_command.user.name == self.channel:
            name = chat_command.parameter.replace(' ', '')
            self.list_update(name, self.black_list, remove = True)
            await chat_command.reply(f'User {name} is no longer blacklisted')
    
    async def check_black_list(self, name):
        return self.check_list(name, self.black_list)
        
    def check_list(self, name, list_name):
        l = self.load_list(list_name)
        return name in l
        
    def list_update(self, name, list_name, remove=False):
        l = self.load_list(list_name)
        if name in l and not remove:
            return
        if remove:
            l.remove(name)
        else:
            l.append(name)
        self.write_list(l, list_name)

    def write_list(self, name_list, file_path):
        try:
            with open(os.path.join(file_path), "w") as f:
                f.write(json.dumps(name_list, indent=4))  # Use indent for pretty-printing
        except Exception as e:
            print(f"An error occurred while writing to {file_path}.json: {str(e)}")

    
    def load_list(self, file_path):
        if os.path.exists(file_path):
            with open(file_path, "r") as f:
                i = json.loads(f.read())
                return i
        else: 
            raise FileNotFoundError
        
        
        
        


if __name__ == "__main__":
    config = TwitchConfig
    config.app_secret = APP_SECRET
    config.app_id = APP_ID
    config.channel = TWITCH_USER
    config.user_scopes = [AuthScope.CHAT_READ,
                          AuthScope.CHAT_EDIT,
                          AuthScope.MODERATOR_READ_CHATTERS,
                          AuthScope.MODERATOR_MANAGE_BANNED_USERS,
                          AuthScope.MODERATOR_READ_FOLLOWERS]
    config.white_list_location = "whitelist.json"
    config.black_list_location = "blacklist.json"
    
    app = StreamerShieldTwitch(config)
    asyncio.run(app.run())