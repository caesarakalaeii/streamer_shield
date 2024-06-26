import os
import json
import math
import time
import asyncio
import requests
import threading
import numpy as np
from datetime import datetime
from end_point_config import *
from twitchAPI.helper import first
from twitch_config import TwitchConfig
from quart import Quart, redirect, request
from twitchAPI.oauth import UserAuthenticator
from twitchAPI.twitch import Twitch, TwitchUser
from config import APP_SECRET, APP_ID, TWITCH_USER
from twitchAPI.eventsub.webhook import EventSubWebhook
from twitchAPI.object.eventsub import ChannelFollowEvent
from twitchAPI.type import AuthScope, ChatEvent, TwitchAPIException, EventSubSubscriptionConflict, EventSubSubscriptionError, EventSubSubscriptionTimeout, TwitchBackendException
from twitchAPI.chat import Chat, EventData, ChatMessage, JoinEvent, JoinedEvent, ChatCommand, ChatUser

init_login : bool
twitch: Twitch
auth: UserAuthenticator



class StreamerShieldTwitch:
    global twitch, auth
    chat : Chat
    commands : dict
    is_armed : bool
    
    def __init__(self, config : TwitchConfig) -> None:
        self.__app_id = config.app_id
        self.__app_secret = config.app_secret
        self.user_scopes = config.user_scopes
        self.user_name = config.user_name
        self.is_armed  = config.is_armed
        self.white_list = config.white_list_location
        self.black_list = config.black_list_location
        self.channel_location = config.channel_location
        self.known_users_location = config.known_users_location
        self.ban_reason = config.ban_reason
        self.l = config.logger
        self.await_login = True
        self.even_subs = []
        self.auth_url = config.auth_url
        self.shield_url = config.shield_url
        self.eventsub_url = config.eventsub_url
        self.collect_data = config.collect_data
        self.age_threshold = config.age_threshold
        self.admin = config.admin
        self.commands = {
        "help":{
                "help": "!help: prints all commands",
                "value": False,
                "cli_func": self.help_cli,
                "twt_func": self.help_twitch,
                "permissions": 0
            },
        "stop":{
                "help": "!stop: stops the process (Not available for Twitch)",
                "value": False,
                "cli_func": self.stop_cli,
                "twt_func": self.stop_twitch,
                "permissions": 10
        },
        "arm":{
                "help": "!arm: enables StreamerShield to ban users",
                "value": False,
                "cli_func": self.arm_cli,
                "twt_func": self.arm_twitch,
                "permissions": 10
                },
        "disarm":{
                "help": "!disarm: stops StreamerShield from banning users",
                "value": False,
                "cli_func": self.disarm_cli,
                "twt_func": self.disarm_twitch,
                "permissions": 5
                },
        "leave_me":{
                "help": "!leave_me: leaves this chat",
                "value": False,
                "cli_func": self.leave_cli,
                "twt_func": self.leave_me_twitch,
                "permissions": 5
                },
        "leave":{
                "help": "!leave chat_name: leaves a chat",
                "value": True,
                "cli_func": self.leave_cli,
                "twt_func": self.leave_twitch,
                "permissions": 10
                },
        "whitelist":{
                "help": "!whitelist user_name: whitelist user",
                "value": True,
                "cli_func": self.whitelist_cli,
                "twt_func": self.whitelist_twitch,
                "permissions": 5
                },
        "unwhitelist":{
                "help": "!unwhitelist user_name: removes user from whitelist",
                "value": True,
                "cli_func": self.unwhitelist_cli,
                "twt_func": self.unwhitelist_twitch,
                "permissions": 5
                },
        "blacklist":{
                "help": "!blacklist user_name: blacklist user",
                "value": True,
                "cli_func": self.blacklist_cli,
                "twt_func": self.blacklist_twitch,
                "permissions": 5
                },
        "unblacklist":{
                "help": "!unblacklist user_name: removes user from blacklist",
                "value": True,
                "cli_func": self.unblacklist_cli,
                "twt_func": self.unblacklist_twitch,
                "permissions": 5
                }, 
        "streamershield":{
            "help": "!streamershield : prints info about the shield",
                "value": False,
                "cli_func": self.shield_info_cli,
                "twt_func": self.shield_info_twitch,
                "permissions": 0
                },
        "shield":{
            "help": "!shield : prints info about the shield",
                "value": False,
                "cli_func": self.shield_info_cli,
                "twt_func": self.shield_info_twitch,
                "permissions": 0
                },
        "pat":{
            "help": "!pat [user_name] : pats user",
                "value": True,
                "cli_func": self.pat_cli,
                "twt_func": self.pat_twitch,
                "permissions": 0
                }
        ,
        "scam":{
            "help": "!scam [user_name] : evaluates username, if given",
                "value": True,
                "cli_func": self.scam_cli,
                "twt_func": self.scam_twitch,
                "permissions": 0
                },
        "test":{
            
            "help": "!scam [user_name] : evaluates username, if given",
                "value": True,
                "cli_func": self.test_cli,
                "twt_func": self.test_twitch,
                "permissions": 10
        }
        }
        pass
          
    
    async def run(self):
        global twitch, auth, app, init_login
        
        self.l.info("Shield Starting up")
        
        twitch = await Twitch(self.__app_id, self.__app_secret)
        auth = UserAuthenticator(twitch, TARGET_SCOPE, url=self.auth_url)
        
        while(self.await_login):
            try:
                self.l.info("Shield awaiting inital login")
                time.sleep(3)
            except KeyboardInterrupt:
                self.l.fail("Keyboard Interrupt, exiting") #not actually working
                raise KeyboardInterrupt("User specified shutdown")
        self.l.passingblue("Shield inital login successful")
        self.l.passingblue("Welcome home Chief!")
        
        self.eventsub = EventSubWebhook(self.eventsub_url, 8080, twitch, revocation_handler=self.esub_revoked)
        await self.eventsub.unsubscribe_all() # unsub, other wise stuff breaky
        self.eventsub.start()
        
        
        
        self.l.passingblue("Started EventSub")
        
        self.user = await first(twitch.get_users(logins=self.user_name))
        self.chat = await Chat(twitch)

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
        
        
        self.running = True
        
        await self.cli_run()
        
    async def esub_revoked(self, diction : dict):
        self.l.error(f"EventSub was revoked {diction}")
            
            
    ### CLI Command Handling
    async def command_handler(self, command :str):
        parts = command.split(" ")
        if parts[0] == '':
            return
        if not(parts[0] in self.commands.keys()):
            self.l.error(f'Command {parts[0]} unknown')
        if self.commands[parts[0]]['value']:
           await self.commands[parts[0]]['cli_func'](parts[0])
           return
        await self.commands[parts[0]]['cli_func']()
        
    async def cli_run(self):
        while(self.running):
            try:
                com = input("type help for available commands\n")
                await self.command_handler(com)
            except Exception as e:
                self.l.error(f'Exeption in cli_run, exiting: {e}')
                exit(1)
    
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
            await twitch.close()
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
    
    async def join_chat(self, name:str):
        global twitch
        unable_to_join =  await self.chat.join_room(name)
        
        if unable_to_join :
            self.l.error(f"Unable to join {name}: {unable_to_join}")
            #this is a bit funky
            return f"Unable to join {name}: {unable_to_join}"
        if self.chat.is_mod(name):
            self.l.passing(f"Succsessfully joined {name}")
            user = await first(twitch.get_users(logins=name))
            self.list_update(name, self.channel_location)
            try:
                await self.new_follow_esub(user.id)
            except:
                return f"Unable to init EventSub, contact Admin"
            return f"Succsessfully joined {name}"
        self.l.error(f"Succsessfully joined {name}, but no mod status")
        return f"Succsessfully joined {name}, but no mod status"
            
    async def new_follow_esub(self, id : str):
        try:
            self.l.info(f"Initializing Follow ESub")  
            await self.eventsub.listen_channel_follow_v2(id, self.user.id, self.on_follow) 
        except EventSubSubscriptionConflict as e:
            self.l.error(f'Error whilst subscribing to eventsub: EventSubSubscriptionConflict {e}')
        except EventSubSubscriptionTimeout as e:
            self.l.error(f'Error whilst subscribing to eventsub: EventSubSubscriptionTimeout {e}')
        except EventSubSubscriptionError as e:
            self.l.error(f'Error whilst subscribing to eventsub: EventSubSubscriptionError {e}')
        except TwitchBackendException as e:
            self.l.error(f'Error whilst subscribing to eventsub: TwitchBackendException {e}')
        
        
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
     
    async def scam_cli(self, name:str):
        conf = await self.request_prediction(name) #will come in *1000 for use in json
        self.l.info(f'User {name} returns conf {conf/1000}')
  
    async def pat_cli(self, name:str):
        self.l.passingblue(f"You're a good boi!" )
    
    async def test_cli(self, name:str):
        self.l.info(f'Restricting {name}')
        await self.chat.send_message('caesarlp', f'/restrict {name}')
    
    ### Twitch Command Handling
    async def shield_info_twitch(self, chat_command: ChatCommand):
         await chat_command.reply('StreamerShield is the AI ChatBot to rid twitch once and for all from scammers. More information here: https://linktr.ee/caesarlp')
    
    async def help_twitch(self, chat_command : ChatCommand):
        permission = await self.generate_permissions(chat_command)
        reply = ''
        for command, value in self.commands.items():
            if(permission < value['permissions']):
                continue
            if len(reply)+ len(f'{value["help"]}; ') > 255:
                await chat_command.reply(reply)
                reply = ''
            reply += f'{value["help"]}; '
        await chat_command.reply(reply)
        
    async def stop_twitch(self, chat_command:ChatCommand):
        if await self.verify_permission(chat_command, "disarm"):
            await chat_command.reply("StreamerShield can only be shutdown via cli")
           
    async def arm_twitch(self, chat_command : ChatCommand):
        if await self.verify_permission(chat_command, "arm"):
            await chat_command.reply("Armed StreamerShield")
            self.l.warning("Armed StreamerShield")
            self.is_armed = True
        
    async def disarm_twitch(self, chat_command : ChatCommand):
        if await self.verify_permission(chat_command, "disarm"):
            await chat_command.reply("Disarmed StreamerShield")
            self.l.warning("Disarmed StreamerShield")
            self.is_armed = False
    
    async def leave_me_twitch(self, chat_command : ChatCommand):
        if await self.verify_permission(
            chat_command, "leave_me") and (
            not chat_command.parameter == chat_command.room.name):
            await chat_command.reply("Leaving... Bye!")
            self.list_update(chat_command.parameter, self.channel_location, remove=True)
            await self.chat.leave_room(chat_command.parameter)
            
    async def leave_twitch(self, chat_command : ChatCommand):
        if await self.verify_permission(
            chat_command, "leave") and (
            not chat_command.parameter == chat_command.room.name):
            await chat_command.reply("Leaving... Bye!")
            self.list_update(chat_command.parameter, self.channel_location, remove=True)
            await self.chat.leave_room(chat_command.parameter)
        
    async def whitelist_twitch(self, chat_command : ChatCommand):
        if await self.verify_permission(chat_command, "whitelist"):
            name = chat_command.parameter.replace("@", "")
            self.list_update(name, self.white_list)
            await chat_command.reply(f'User {name} is now whitelisted')
        
    async def unwhitelist_twitch(self, chat_command : ChatCommand):
        if await self.verify_permission(chat_command, "unwhitelist"):
            name = chat_command.parameter.replace("@", "")
            self.list_update(name, self.white_list, remove = True)
            await chat_command.reply(f'User {name} is no longer whitelisted')
            
    async def blacklist_twitch(self, chat_command : ChatCommand):
        if await self.verify_permission(chat_command, "blacklist"):
            name = chat_command.parameter.replace("@", "")
            self.list_update(name, self.black_list)
            await chat_command.reply(f'User {name} is now blacklisted')
        
    async def unblacklist_twitch(self, chat_command : ChatCommand):
        if await self.verify_permission(chat_command, "unblacklist"):
            name = chat_command.parameter.replace("@", "")
            self.list_update(name, self.black_list, remove = True)
            await chat_command.reply(f'User {name} is no longer blacklisted')
    
    async def scam_twitch(self, chat_command : ChatCommand):
        try:
            name = chat_command.parameter.replace("@", "")
        except:
            pass
        if not name:
            name = chat_command.user.name
            
        conf = await self.request_prediction(name) #will come in *1000 for use in json
            
        await chat_command.reply(f'@{name} is to {conf/10}% a scammer')
        
    async def pat_twitch(self, chat_command : ChatCommand):
        self_pat = False
        try:
            name = chat_command.parameter.replace("@", "")
        except:
            pass
        if not name:
            self_pat = True
            name = chat_command.user.name
        l = self.load_list(self.known_users_location)
        for item in l:
            if "pat" in item:
                pats = item["pat"]
        pats += 1
        self.list_update({"pat": pats}, self.known_users_location)
        if self_pat:
            await chat_command.reply(f"You just gave yourself a pat on the back! well deserved LoveYourself {pats} pats have been given")
            return
        await chat_command.reply(f'@{chat_command.user.name} gives @{name} a pat! peepoPat {pats} pats have been given')
    
    async def test_twitch(self,  chat_command : ChatCommand):
        name = chat_command.parameter.replace("@", "")
        await chat_command.reply(f'Trying to restrict user {name}')
        self.l.info(f'Restricting {name}')
        await self.chat.send_raw_irc_message(f'/restrict {name}')
    ###Event Subs and Chat events
    
    async def on_ready(self,ready_event: EventData):
        channels :list = self.load_list(self.channel_location)
        channels.append(self.chat.username)
        await ready_event.chat.join_room(channels)
        for channel in channels:
            user = await first(twitch.get_users(logins = [channel]))
            try:
                await self.new_follow_esub(user.id)
            except:
                self.l.error(f"Follow ESub for {user.login} not initialized")
            self.l.info(f"Follow Esub for {user.login} initialized")  
    
    async def on_joined(self, joined_event: JoinedEvent):
        await joined_event.chat.send_message(joined_event.room_name, "This Chat is now protected with StreamerShield! protecc")
        
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
    
    
    # Onfollow will only work with headless webhook approach
       
    async def on_follow(self, data: ChannelFollowEvent):
        name = data.event.user_name
        self.l.passing(f"WE GOT A FOLLOW!!!!! {name}")
        await self.check_user(name, data.event.broadcaster_user_id)
    
    
    ### StreamerShield Main
    async def check_user(self, name :str, room_name_id):
        if await self.check_white_list(name): 
            self.l.info(f"{name} is found in whitelist")
            return
        if await self.check_black_list(name): 
            self.l.warning(f"{name} is found in blacklist")
            if self.is_armed:
                user = await first(twitch.get_users(logins=name))
                await self.chat.send_message(room_name_id, f'/restrict {name}')
                #await twitch.ban_user(room_name_id, room_name_id, user.id, self.ban_reason)
            return
        #get prediction from REST 
        conf = await self.request_prediction(name) #will come in *1000 for use in json
        
        #if datacollection is turned on, collect known users and their account age
        user = await first(twitch.get_users(logins=name))
        if self.collect_data and (not self.check_known_users(name)):
            self.list_update({name:(math.floor(conf), await self.calculate_account_age(user))}, self.known_users_location)
            
        conf = conf/1000 #turn into actual conf 0...1
        #check for account age    
        if await self.check_account_age(user=user):
            self.l.passing(f'Found Account older than {self.age_threshold} Months, name : {name}, conf: {conf})')
            return
        
        
        if (bool(np.round(conf))):
            if self.is_armed:
                #TODO: Check either for account age or follow count if possible
                self.l.fail(f'Banned user {name}')
                await twitch.ban_user(room_name_id, self.user.id, user.id, self.ban_reason) #self.user to ban using the Streamershield account
            self.l.warning(f'User {name} was classified as a scammer with conf {conf}')
            return
        self.l.passing(f'User {name} was classified as a human with conf {conf}')
            
    
    async def calculate_account_age(self, user: TwitchUser):
        current_time = datetime.now()
        creation_time = user.created_at
        age_year = current_time.year - creation_time.year
        age_months = current_time.month - creation_time.month
        age_days = current_time.day - creation_time.day
        return(age_year, age_months, age_days)
    
    ### Utility functions    
    async def check_account_age(self, user: TwitchUser):
        age = await self.calculate_account_age(user)
        
        if age[0] > 0:
            return True
        elif age[1] > self.age_threshold:
            return True
        return False
            
    
    async def generate_permissions(self, chat_command : ChatCommand):
        if(chat_command.user.name == self.admin):
            permission = 10
        elif(chat_command.user.mod or chat_command.user.name == chat_command.room.name):
            permission = 5
        elif(not (chat_command.user.mod or chat_command.user.name == chat_command.room.name)):
            permission = 0
        return permission
    
    async def verify_permission(self, chat_command : ChatCommand, command : str):
        permission = await self.generate_permissions(chat_command)
        return self.commands[command]["permissions"] <= permission
    
    async def user_refresh(token: str, refresh_token: str):
        print(f'my new user token is: {token}')

    async def app_refresh(token: str):
        print(f'my new app token is: {token}')
        
    async def check_white_list(self, name):
        return self.check_list(name, self.white_list)
    
    async def check_black_list(self, name):
        return self.check_list(name, self.black_list)
     
     
    def check_known_users(self, name:str):
        l = self.load_list(self.known_users_location)
        
        for d in l:
            if name.lower() in d:
                return True
            
        return False   
    
    def check_list(self, name : str, list_name):
        l = self.load_list(list_name)
        r = (name in l) or (name.lower() in l)
        return r
        
    def list_update(self, name, list_name, remove=False):
        l : list = self.load_list(list_name)
        if type(name) == str:
            if name.lower() in l and not remove:
                return
            if remove:
                l.remove(name.lower())
            else:
                l.append(name.lower())
        try:
            if name["pat"]: 
                for item in l:
                    if "pat" in item:
                        item["pat"] = name["pat"]
        except:
            l.append(name.lower())
            pass
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
    
    async def request_prediction(self, name : str):
        data = {"input_string": name}

        response = requests.post(self.shield_url, json=data)

        if response.status_code == 200:
            return response.json()["result"]
            
        else:
            self.l.error(response.json())


app = Quart(__name__)

chat_bot: StreamerShieldTwitch
TARGET_SCOPE : list
app.secret_key = 'your_secret_key'







@app.route('/login')
def login():
    return redirect(auth.return_auth_url())



@app.route('/login/confirm')
async def login_confirm():
    global session, chat_bot
    args = request.args
    state = request.args.get('state')
    if state != auth.state:
        return 'Bad state', 401
    code = request.args.get('code')
    if code is None:
        return 'Missing code', 400
    try:
        token, refresh = await auth.authenticate(user_token=code)
       
        if chat_bot.await_login:
            await twitch.set_user_authentication(token, TARGET_SCOPE, refresh)
            ret_val = "Welcome home chief!"
            
        user_info = await first(twitch.get_users())
        name = user_info.login
        
        if not chat_bot.await_login:
            ret_val =  await chat_bot.join_chat(name)
        
    except TwitchAPIException as e:
        return 'Failed to generate auth token', 400
    
    chat_bot.await_login = False
    return ret_val


    

 
def main():
    asyncio.run(chat_bot.run())


        
        
        



if __name__ == "__main__":
    config = TwitchConfig
    config.app_secret = APP_SECRET
    config.app_id = APP_ID
    config.max_lenght = 31
    config.user_name = TWITCH_USER
    TARGET_SCOPE = [AuthScope.CHAT_READ,
                    AuthScope.CHAT_EDIT,
                    AuthScope.MODERATOR_READ_CHATTERS,
                    AuthScope.MODERATOR_MANAGE_BANNED_USERS,
                    AuthScope.MODERATOR_READ_FOLLOWERS]
    config.user_scopes = TARGET_SCOPE
    config.white_list_location = "whitelist.json"
    config.black_list_location = "blacklist.json"
    config.channel_location = "joinable_channels.json"
    config.known_users_location = "known_users.json"
    config.collect_data = True
    config.admin = 'caesarlp'
    config.eventsub_url = EVENTSUB_URL
    config.shield_url = SHIELD_URL
    config.auth_url = AUTH_URL
    config.is_armed = True
    
    chat_bot = StreamerShieldTwitch(config)
    
    
    
    process2 = threading.Thread(target=main)

    
    process2.start()
    app.run('0.0.0.0')
    
    process2.join()
    
    