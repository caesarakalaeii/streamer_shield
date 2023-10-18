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
from twitchAPI.chat import Chat, EventData, ChatMessage, JoinEvent, JoinedEvent, ChatCommand, ChatUser

class TwitchConfig:
    app_id : str
    app_secret : str      
    user_scopes : [AuthScope]
    white_list_location : str
    black_list_location : str
    channel_location : str
    user_name : str
    is_armed : bool = False
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
    commands : dict
    is_armed : bool
    
    def __init__(self, config : TwitchConfig) -> None:
        self.__app_id = config.app_id
        self.__app_secret = config.app_secret
        self.user_scopes = config.user_scopes
        self.user_name = config.user_name
        self.white_list = config.white_list_location
        self.is_armed  = config.is_armed
        self.black_list = config.black_list_location
        self.channel_location = config.channel_location
        self.ban_reason = config.ban_reason
        self.ss = StreamerShield(config.model_path,
                                 config.max_lenght,
                                 config.scammer_threshold,
                                 config.user_threshold)
        self.l = config.logger
        self.commands = {
        "help":{
            "help": "!help: prints all commands",
            "value": False,
            "cli_func": self.help_cli,
            "twt_func": self.help_twitch
            },
        "stop":{
            "help": "!stop: stops the process (Not available for Twitch)",
            "value": False,
            "cli_func": self.stop_cli,
            "twt_func": self.stop_twitch
        },
        "arm":{
                "help": "!arm: enables StreamerShield to ban users",
                "value": False,
                "cli_func": self.arm_cli,
                "twt_func": self.arm_twitch
                },
        "disarm":{
                "help": "!disarm: stops StreamerShield from banning users",
                "value": False,
                "cli_func": self.disarm_cli,
                "twt_func": self.disarm_twitch
                },
        "join":{
                "help": "!join chat_name: joins a chat",
                "value": True,
                "cli_func": self.join_cli,
                "twt_func": self.join_twitch
                },
        "leave":{
                "help": "!leave chat_name: leaves a chat",
                "value": True,
                "cli_func": self.leave_cli,
                "twt_func": self.leave_twitch
                },
        "whitelist":{
                "help": "!whitelist user_name: whitelist user",
                "value": True,
                "cli_func": self.whitelist_cli,
                "twt_func": self.whitelist_twitch
                },
        "unwhitelist":{
                "help": "!unwhitelist user_name: removes user from whitelist",
                "value": True,
                "cli_func": self.unwhitelist_cli,
                "twt_func": self.unwhitelist_twitch
                },
        "blacklist":{
                "help": "!blacklist user_name: blacklist user",
                "value": True,
                "cli_func": self.blacklist_cli,
                "twt_func": self.blacklist_twitch
                },
        "unblacklist":{
                "help": "!unblacklist user_name: removes user from blacklist",
                "value": True,
                "cli_func": self.unblacklist_cli,
                "twt_func": self.unblacklist_twitch
                }, 
        "streamershield":{
            "help": "!streamershield : prints info about the shield",
                "value": False,
                "cli_func": self.shield_info_cli,
                "twt_func": self.shield_info_twitch
                }, 
        "joinme":{
            "help": "!joinme : joins user, only available in the bot chat",
                "value": False,
                "cli_func": self.join_me_cli,
                "twt_func": self.join_me_twitch
                },
        }
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
        self.user = await first(self.twitch.get_users(logins=self.user_name))
        
        self.chat = await Chat(self.twitch)

        # register the handlers for the events you want

        # listen to when the bot is done starting up and ready to join channels
        self.chat.register_event(ChatEvent.READY, self.on_ready)
        # listen to chat join events (might not trigger, depending channel size)
        self.chat.register_event(ChatEvent.JOIN, self.on_join)
        
        self.chat.register_event(ChatEvent.JOINED, self.on_joined)
        # listen to chat messages
        self.chat.register_event(ChatEvent.MESSAGE, self.on_message)
        for command, value in self.commands.items():
            self.chat.register_command(command, value['twt_func'])
        self.chat.start()
        
        self.eventsub = EventSubWebsocket(self.twitch)
        self.eventsub.start()
        await self.eventsub.listen_channel_follow_v2(self.user.id, self.user.id, self.on_follow)
        
        self.running = True
        
        await self.cli_run()
        
        
            
            
    ### CLI Command Handling
    async def command_handler(self, command :str):
        parts = command.split(" ")
        if len(parts)==0:
            return
        if not(parts[0] in self.commands.keys()):
            self.l.error(f'Command {parts[0]} unknown')
        if self.commands[parts[0]]['value']:
           await self.commands[parts[0]]['cli_func'](parts[0])
           return
        await self.commands[parts[0]]['cli_func']()
        
    async def cli_run(self):
        while(self.running):
            com = input("type help for available commands\n")
            await self.command_handler(com)
    
    async def shield_info_cli(self):
        self.l.info('''
                    StreamerShield is the AI ChatBot to rid twitch once and for all from scammers. More information here: https://linktr.ee/caesarlp
                    ''')
    
    async def help_cli(self):
        for command, value in self.commands.items():
            self.l.passing(f'{value["help"]}')
            
    async def stop_cli(self):
        self.l.fail("Stopping!")
        try:
            await self.chat.stop() #sometimes is already gone when stopped, so...
        except:
            pass
        try:
            await self.eventsub.stop()
        except:
            pass
        try:
            await self.twitch.close()
        except:
            pass
        raise Exception("Stopped by User") #not the most elegant but works
    
    async def arm_cli(self):
        self.l.warning("Armed StreamerShield")
        self.is_armed = True
        
    async def disarm_cli(self):
        self.l.warning("Disarmed StreamerShield")
        self.is_armed = False
    
    async def join_me_cli(self):
        self.l.error("Cannot invoke join_me from cli, please use join instead")
    
    async def join_cli(self, name:str):
        unable_to_join = self.chat.join_room(name)
        if not (unable_to_join == None):
            self.l.error(f"Unable to join {name}")
            return
        if self.chat.is_mod(name):
            self.l.passing(f"Succsessfully joined {name}")
            self.list_update(name, self.channel_location, remove=True)
            return
        self.l.error(f"Succsessfully joined {name}, but no mod status")
            
    async def leave_cli(self, name:str):
        self.chat.leave_room(name)
        self.list_update(name, self.channel_location, remove=True)
        self.l.passing(f"Left {name}")
        
    async def whitelist_cli(self, name:str):
        self.l.passing(f"Whitelisted {name}")
        self.list_update(name, self.white_list)    
        
    async def unwhitelist_cli(self, name:str):
        self.l.passing(f"Unwhitelisted {name}")
        self.list_update(name, self.white_list, remove= True)   
        
    async def blacklist_cli(self, name:str):
        self.l.passing(f"Blacklisted {name}")
        self.list_update(name, self.black_list)
        
    async def unblacklist_cli(self, name:str):
        self.l.passing(f"Unblacklisted {name}")
        self.list_update(name, self.black_list, remove= True)
        
    ### Twitch Command Handling
    async def shield_info_twitch(self, chat_command: ChatCommand):
         await chat_command.reply('StreamerShield is the AI ChatBot to rid twitch once and for all from scammers. More information here: https://linktr.ee/caesarlp')
    
    async def help_twitch(self, chat_command : ChatCommand):
        if(not (chat_command.user.mod or chat_command.user.name == chat_command.room.name)):
            return
        reply = ''
        for command, value in self.commands.items():
            reply += f'{value["help"]}; '
        await chat_command.reply(reply)
        
    async def stop_twitch(self, chat_command:ChatCommand):
        if(not (chat_command.user.mod or chat_command.user.name == chat_command.room.name)):
            return
        await chat_command.reply("StreamerShield can only be shutdown via cli")
        
        
    async def arm_twitch(self, chat_command : ChatCommand):
        if(not (chat_command.user.mod or chat_command.user.name == chat_command.room.name)):
            return
        await chat_command.reply("Armed StreamerShield")
        self.l.warning("Armed StreamerShield")
        self.is_armed = True
        
    async def disarm_twitch(self, chat_command : ChatCommand):
        if(not (chat_command.user.mod or chat_command.user.name == chat_command.room.name)):
            return
        await chat_command.reply("Disarmed StreamerShield")
        self.l.warning("Disarmed StreamerShield")
        self.is_armed = False
    
    async def join_me_twitch(self, chat_command : ChatCommand):
        name = chat_command.user.name
        if(not (chat_command.room.name == self.chat.username)):
            return
        unable_to_join = await self.chat.join_room(name)
        if not (unable_to_join == None):
            await chat_command.reply("Unable to join")
            self.l.error(f"Unable to join {name}")
            return
        if self.chat.is_mod(name):
            await chat_command.reply("Joined succsessfully")
            self.list_update(name, self.channel_location)
            self.l.passing(f"Succsessfully joined {name}")
            return
        await chat_command.reply(f"Succsessfully joined {name}, but no mod status")
        self.l.error(f"Succsessfully joined {name}, but no mod status")
    
    
    async def join_twitch(self, chat_command : ChatCommand):
        name = chat_command.parameter.replace("@", "")
        if(not (chat_command.user.mod or chat_command.user.name == chat_command.room.name)):
            return
        unable_to_join = await self.chat.join_room(name)
        if not (unable_to_join == None):
            await chat_command.reply("Unable to join")
            self.l.error(f"Unable to join {name}")
            return
        if self.chat.is_mod(name):
            await chat_command.reply("Joined succsessfully")
            self.list_update(name, self.channel_location)
            self.l.passing(f"Succsessfully joined {name}")
            return
        await chat_command.reply(f"Succsessfully joined {name}, but no mod status")
        self.l.error(f"Succsessfully joined {name}, but no mod status")
            
    async def leave_twitch(self, chat_command : ChatCommand):
        if(not (chat_command.user.mod or chat_command.user.name == chat_command.room.name)):
            return
        if(not chat_command.parameter == chat_command.room.name):
            await chat_command.reply("Leaving... Bye!")
            self.list_update(chat_command.parameter, self.channel_location, remove=True)
            await self.chat.leave_room(chat_command.parameter)
        
    async def whitelist_twitch(self, chat_command : ChatCommand):
        if chat_command.user.mod or chat_command.user.name == chat_command.room.name:
            name = chat_command.parameter.replace("@", "")
            self.list_update(name, self.white_list)
            await chat_command.reply(f'User {name} is now whitelisted')
        
    async def unwhitelist_twitch(self, chat_command : ChatCommand):
        if chat_command.user.mod or chat_command.user.name == chat_command.room.name:
            name = chat_command.parameter.replace("@", "")
            self.list_update(name, self.white_list, remove = True)
            await chat_command.reply(f'User {name} is no longer whitelisted')
            
    async def blacklist_twitch(self, chat_command : ChatCommand):
        if chat_command.user.mod or chat_command.user.name == chat_command.room.name:
            name = chat_command.parameter.replace("@", "")
            self.list_update(name, self.black_list)
            await chat_command.reply(f'User {name} is now blacklisted')
        
    async def unblacklist_twitch(self, chat_command : ChatCommand):
        if chat_command.user.mod or chat_command.user.name == chat_command.room.name:
            name = chat_command.parameter.replace("@", "")
            self.list_update(name, self.black_list, remove = True)
            await chat_command.reply(f'User {name} is no longer blacklisted')
    
    ###Event Subs and Chat events
    
    async def on_ready(self,ready_event: EventData):
        channels :list = self.load_list(self.channel_location)
        channels.append(self.chat.username)
        await ready_event.chat.join_room(channels)
    
    async def on_joined(self, joined_event: JoinedEvent):
        await joined_event.chat.send_message(joined_event.room_name, "This Chat is now protected with StreamerShield")
        
    async def on_message(self, msg : ChatMessage):
        name = msg.user.name
        privilege = (msg.user.mod or msg.user.vip or msg.user.subscriber or msg.user.turbo)
        if(privilege):
            self.list_update(name, self.white_list)
            return
        await self.check_user(name, msg.room.room_id)
        
    async def on_join(self, join_event : JoinEvent):
        name = join_event.user_name
        
        await self.check_user(name, join_event.room.room_id)
        
    async def on_follow(self, data: ChannelFollowEvent):
        name = data.event.user_name
        
        await self.check_user(name, data.event.broadcaster_user_id)
    
    
    ### StreamerShield Main
    async def check_user(self, name :str, room_name_id):
        if await self.check_white_list(name): 
            self.l.info("Whitelisted user found")
            return
        if await self.check_black_list(name): 
            self.l.warning("Banned user found")
            if self.is_armed:
                user = await first(self.twitch.get_users(logins=name))
                await self.twitch.ban_user(room_name_id, self.user.id, user.id, self.ban_reason)
            return
        
        conf = self.ss.predict(name)
        if (bool(np.round(conf))):
            if self.is_armed:
                user = await first(self.twitch.get_users(logins=name))
                await self.twitch.ban_user(room_name_id, self.user.id, user.id, self.ban_reason)
            self.l.warning(f'User {name} was classified as a scammer with conf {conf}')
            return
        self.l.passing(f'User {name} was classified as a user with conf {conf}')
            
        
    ### Utility functions    
    
    async def user_refresh(token: str, refresh_token: str):
        print(f'my new user token is: {token}')

    async def app_refresh(token: str):
        print(f'my new app token is: {token}')
        
    async def check_white_list(self, name):
        return self.check_list(name, self.white_list)
    
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

    async def check_for_privilege(self, user : ChatUser):
        if(user.mod or user.vip or user.subscriber or user.turbo):
            self.list_update(user.name, self.white_list)
            return True
        return False
    
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
    config.user_name = TWITCH_USER
    config.user_scopes = [AuthScope.CHAT_READ,
                          AuthScope.CHAT_EDIT,
                          AuthScope.MODERATOR_READ_CHATTERS,
                          AuthScope.MODERATOR_MANAGE_BANNED_USERS,
                          AuthScope.MODERATOR_READ_FOLLOWERS]
    config.white_list_location = "whitelist.json"
    config.black_list_location = "blacklist.json"
    config.channel_location = "joinable_channels.json"
    
    app = StreamerShieldTwitch(config)
    asyncio.run(app.run())