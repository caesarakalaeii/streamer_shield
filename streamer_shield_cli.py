import asyncio
import json
import os
import numpy as np
from logger import Logger
from flask import Flask, redirect, request
from config import APP_SECRET, APP_ID, TWITCH_USER
from twitchAPI.helper import first, build_scope
from twitchAPI.twitch import Twitch , TwitchUser
from streamer_shield import StreamerShield
from twitchAPI.object.eventsub import ChannelFollowEvent
from twitchAPI.eventsub.webhook import EventSubWebhook
from twitchAPI.type import AuthScope, ChatEvent, TwitchAPIException
from twitchAPI.oauth import UserAuthenticator,UserAuthenticationStorageHelper
from twitchAPI.chat import Chat, EventData, ChatMessage, JoinEvent, JoinedEvent, ChatCommand, ChatUser

twitch:Twitch
auth : UserAuthenticator
chat : Chat
eventsubs : dict
running : bool
l : Logger
target_scope : list
app_id : str
app_secret: str
app_id : str   
white_list_location : str
black_list_location : str
channel_location : str
user_name : str
webhook_url : str
is_armed : bool = False
model_path : str = 'shield.h5'
ban_reason : str = '''You've been banned by StreamerShield, if you think the was an Error, please make an unban request'''
max_lenght : int = 30 #should be kept at 30, as the model was trained with it
scammer_threshold : int = 0.5 #only used for test function, not used for evaluation, yet
user_threshold : int = 0.5 #only used for test function, not used for evaluation, yet



app = Flask(__name__)
    
@app.route('/login')
def login():
    return redirect(auth.return_auth_url())


@app.route('/login/confirm')
async def login_confirm():
    state = request.args.get('state')
    if state != auth.state:
        return 'Bad state', 401
    code = request.args.get('code')
    if code is None:
        return 'Missing code', 400
    try:
        token, refresh = await auth.authenticate(user_token=code)
        await twitch.set_user_authentication(token, user_scopes, refresh)
    except TwitchAPIException as e:
        return 'Failed to generate auth token', 400
    return 'Sucessfully authenticated!'
# register the handlers for the events you want

class TwitchConfig:
    app_id : str
    app_secret : str      
    user_scopes : [AuthScope]
    white_list_location : str
    black_list_location : str
    channel_location : str
    user_name : str
    webhook_url : str
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
    
    



        

async def run():
    global twitch , auth, chat, eventsubs, running, target_scope, helper, user, app_id, app_secret
    twitch = await Twitch(app_id,app_secret)

    target_scope = user_scopes
    helper = UserAuthenticationStorageHelper(twitch, user_scopes)
    await helper.bind()
    auth = UserAuthenticator(twitch, target_scope, force_verify=False, url=webhook_url)
    # this will open your default browser and prompt you with the twitch verification website
    
    await auth.authenticate()
    # add User authentication
    user = await first(twitch.get_users(logins=user_name))
    
    chat = await Chat(twitch)
    

    # listen to when the bot is done starting up and ready to join channels
    chat.register_event(ChatEvent.READY, on_ready)
    # listen to chat join events (might not trigger, depending channel size)
    chat.register_event(ChatEvent.JOIN, on_join)
    
    chat.register_event(ChatEvent.JOINED, on_joined)
    # listen to chat messages
    chat.register_event(ChatEvent.MESSAGE, on_message)
    for command, value in commands.items():
        chat.register_command(command, value['twt_func'])
    chat.start()
    
    await new_event_sub(user)    
    
    running = True
    
    await cli_run()
    
    
async def new_event_sub( user : TwitchUser):
    global eventsubs
    eventsub = EventSubWebhook(webhook_url, 8080,twitch)
    eventsub.start()
    await eventsub.listen_channel_follow_v2(user.id, user.id, on_follow)
    eventsubs[f"{user.login}"] = eventsub
        
async def remove_event_sub( user_name):
    global eventsubs
    try:
        eventsub : EventSubWebhook = eventsubs.pop(user_name)
        await eventsub.unsubscribe_all()
        await eventsub.stop()
    except KeyError:
        pass
        
### CLI Command Handling
async def command_handler( command :str):
    global commands
    parts = command.split(" ")
    if parts[0] == '':
        return
    if not(parts[0] in commands.keys()):
        l.error(f'Command {parts[0]} unknown')
    if commands[parts[0]]['value']:
        await commands[parts[0]]['cli_func'](parts[0])
        return
    await commands[parts[0]]['cli_func']()
    
async def cli_run():
    global running
    while(running):
        com = input("type help for available commands\n")
        await command_handler(com)

async def shield_info_cli():
    global l
    l.info('''
                StreamerShield is the AI ChatBot to rid twitch once and for all from scammers. More information here: https://linktr.ee/caesarlp
                ''')

async def help_cli():
    global l,commands
    for command, value in commands.items():
        l.passing(f'{value["help"]}')
        
async def stop_cli():
    global l, chat, eventsubs, twitch
    l.fail("Stopping!")
    try:
        await chat.stop() #sometimes is already gone when stopped, so...
    except:
        pass
    try:
        async for sub in eventsubs.values():
            sub.stop()
    except:
        pass
    try:
        await twitch.close()
    except:
        pass
    raise Exception("Stopped by User") #not the most elegant but works

async def arm_cli():
    global l, is_armed
    l.warning("Armed StreamerShield")
    is_armed = True
    
async def disarm_cli():
    global l, is_armed
    l.warning("Disarmed StreamerShield")
    is_armed = False

async def join_me_cli():
    global l
    l.error("Cannot invoke join_me from cli, please use join instead")

async def join_cli( name:str):
    global chat, channel_location, l, twitch
    unable_to_join = chat.join_room(name)
    if not (unable_to_join == None):
        l.error(f"Unable to join {name}")
        return
    if chat.is_mod(name):
        l.passing(f"Succsessfully joined {name}")
        user = await first(twitch.get_users(logins=name))
        await new_event_sub(user)
        list_update(name, channel_location, remove=True)
        return
    l.error(f"Succsessfully joined {name}, but no mod status")
        
async def leave_cli( name:str):
    global chat, channel_location, l
    chat.leave_room(name)
    list_update(name, channel_location, remove=True)
    l.passing(f"Left {name}")
    
async def whitelist_cli( name:str):
    global l, white_list
    l.passing(f"Whitelisted {name}")
    list_update(name, white_list)    
    
async def unwhitelist_cli( name:str):
    global l, white_list
    l.passing(f"Unwhitelisted {name}")
    list_update(name, white_list, remove= True)   
    
async def blacklist_cli( name:str):
    global l, black_list
    l.passing(f"Blacklisted {name}")
    list_update(name, black_list)
    
async def unblacklist_cli( name:str):
    global l, black_list
    l.passing(f"Unblacklisted {name}")
    list_update(name, black_list, remove= True)
    
### Twitch Command Handling
async def shield_info_twitch( chat_command: ChatCommand):
    await chat_command.reply('StreamerShield is the AI ChatBot to rid twitch once and for all from scammers. More information here: https://linktr.ee/caesarlp')

async def help_twitch( chat_command : ChatCommand):
    global commands
    if(not (chat_command.user.mod or chat_command.user.name == chat_command.room.name)):
        return
    reply = ''
    for command, value in commands.items():
        reply += f'{value["help"]}; '
    await chat_command.reply(reply)
    
async def stop_twitch( chat_command:ChatCommand):
    if(not (chat_command.user.mod or chat_command.user.name == chat_command.room.name)):
        return
    await chat_command.reply("StreamerShield can only be shutdown via cli")
        
async def arm_twitch( chat_command : ChatCommand):
    global is_armed, l
    if(not (chat_command.user.mod or chat_command.user.name == chat_command.room.name)):
        return
    await chat_command.reply("Armed StreamerShield")
    l.warning("Armed StreamerShield")
    is_armed = True
    
async def disarm_twitch( chat_command : ChatCommand):
    global is_armed, l
    if(not (chat_command.user.mod or chat_command.user.name == chat_command.room.name)):
        return
    await chat_command.reply("Disarmed StreamerShield")
    l.warning("Disarmed StreamerShield")
    is_armed = False

async def join_me_twitch( chat_command : ChatCommand):
    global twitch , chat, channel_location, l
    name = chat_command.user.name
    if(not (chat_command.room.name == chat.username)):
        return
    await chat_command.reply(f"Please Login using this Link: https://id.twitch.tv/oauth2/authorize?client_id={app_id}&redirect_uri={webhook_url}&response_type=code&scope={build_scope(user_scopes)}")
    await asyncio.sleep(15)
    unable_to_join = await chat.join_room(name)
    if not (unable_to_join == None):
        await chat_command.reply("Unable to join")
        l.error(f"Unable to join {name}")
        return
    if chat.is_mod(name):
        await chat_command.reply("Joined succsessfully")
        user = await first(twitch.get_users(logins=name))
        await new_event_sub(user)
        list_update(name, channel_location)
        l.passing(f"Succsessfully joined {name}")
        return
    await chat_command.reply(f"Succsessfully joined {name}, but no mod status")
    l.error(f"Succsessfully joined {name}, but no mod status")

async def join_twitch( chat_command : ChatCommand):
    global twitch , chat, channel_location, l
    name = chat_command.parameter.replace("@", "")
    if(not (chat_command.user.mod or chat_command.user.name == chat_command.room.name)):
        return
    unable_to_join = await chat.join_room(name)
    if not (unable_to_join == None):
        await chat_command.reply("Unable to join")
        l.error(f"Unable to join {name}")
        return
    if chat.is_mod(name):
        await chat_command.reply("Joined succsessfully")
        user = await first(twitch.get_users(logins=name))
        await new_event_sub(user)
        list_update(name, channel_location)
        l.passing(f"Succsessfully joined {name}")
        return
    await chat_command.reply(f"Succsessfully joined {name}, but no mod status")
    l.error(f"Succsessfully joined {name}, but no mod status")
        
async def leave_twitch( chat_command : ChatCommand):
    global chat, channel_location
    if(not (chat_command.user.mod or chat_command.user.name == chat_command.room.name)):
        return
    if(not chat_command.parameter == chat_command.room.name):
        await chat_command.reply("Leaving... Bye!")
        list_update(chat_command.parameter, channel_location, remove=True)
        await chat.leave_room(chat_command.parameter)
    
async def whitelist_twitch( chat_command : ChatCommand):
    global white_list
    if chat_command.user.mod or chat_command.user.name == chat_command.room.name:
        name = chat_command.parameter.replace("@", "")
        list_update(name, white_list)
        await chat_command.reply(f'User {name} is now whitelisted')
    
async def unwhitelist_twitch( chat_command : ChatCommand):
    global white_list
    if chat_command.user.mod or chat_command.user.name == chat_command.room.name:
        name = chat_command.parameter.replace("@", "")
        list_update(name, white_list, remove = True)
        await chat_command.reply(f'User {name} is no longer whitelisted')
        
async def blacklist_twitch( chat_command : ChatCommand):
    global black_list
    if chat_command.user.mod or chat_command.user.name == chat_command.room.name:
        name = chat_command.parameter.replace("@", "")
        list_update(name, black_list)
        await chat_command.reply(f'User {name} is now blacklisted')
    
async def unblacklist_twitch( chat_command : ChatCommand):
    global black_list
    if chat_command.user.mod or chat_command.user.name == chat_command.room.name:
        name = chat_command.parameter.replace("@", "")
        list_update(name, black_list, remove = True)
        await chat_command.reply(f'User {name} is no longer blacklisted')

###Event Subs and Chat events

async def on_ready(ready_event: EventData):
    global channel_location
    channels :list = load_list(channel_location)
    channels.append(chat.username)
    await ready_event.chat.join_room(channels)

async def on_joined(joined_event: JoinedEvent):
    await joined_event.chat.send_message(joined_event.room_name, "This Chat is now protected with StreamerShield")
    
async def on_message( msg : ChatMessage):
    global white_list
    name = msg.user.name
    privilege = (msg.user.mod or msg.user.vip or msg.user.subscriber or msg.user.turbo)
    if(privilege):
        list_update(name, white_list)
        return
    await check_user(name, msg.room.room_id)
    
async def on_join( join_event : JoinEvent):
    name = join_event.user_name
    
    await check_user(name, join_event.room.room_id)
    
async def on_follow( data: ChannelFollowEvent):
    name = data.event.user_name
    
    await check_user(name, data.event.broadcaster_user_id)


### StreamerShield Main
async def check_user( name :str, room_name_id):
    global twitch, l, is_armed
    if await check_white_list(name): 
        l.info("Whitelisted user found")
        return
    if await check_black_list(name): 
        l.warning("Banned user found")
        if is_armed:
            user = await first(twitch.get_users(logins=name))
            await twitch.ban_user(room_name_id, user.id, user.id, ban_reason)
        return
    
    conf = ss.predict(name)
    if (bool(np.round(conf))):
        if is_armed:
            user = await first(twitch.get_users(logins=name))
            #TODO: CHeck either for account age or follow count if possible
            await twitch.ban_user(room_name_id, user.id, user.id, ban_reason)
        l.warning(f'User {name} was classified as a scammer with conf {conf}')
        return
    l.passing(f'User {name} was classified as a user with conf {conf}')
        
    
### Utility functions    

async def user_refresh(token: str, refresh_token: str):
    print(f'my new user token is: {token}')

async def app_refresh(token: str):
    print(f'my new app token is: {token}')
    
async def check_white_list( name):
    global white_list
    return check_list(name, white_list)

async def check_black_list( name):
    global black_list
    return check_list(name, black_list)
    
def check_list( name, list_name):
    l = load_list(list_name)
    return name in l
    
def list_update( name, list_name, remove=False):
    l : list = load_list(list_name)
    if name in l and not remove:
        return
    if remove:
        l.remove(name)
    else:
        l.append(name)
    write_list(l, list_name)

def write_list( name_list, file_path):
    try:
        with open(os.path.join(file_path), "w") as f:
            f.write(json.dumps(name_list, indent=4))  # Use indent for pretty-printing
    except Exception as e:
        print(f"An error occurred while writing to {file_path}.json: {str(e)}")

async def check_for_privilege( user : ChatUser):
    global white_list
    if(user.mod or user.vip or user.subscriber or user.turbo):
        list_update(user.name, white_list)
        return True
    return False

def load_list( file_path):
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            i = json.loads(f.read())
            return i
    else: 
        raise FileNotFoundError
    
    
    
        



app_secret = APP_SECRET
app_id = APP_ID
max_lenght = 31
webhook_url = "http://localhost:17563/login/confirm"
user_name = TWITCH_USER
user_scopes = [AuthScope.CHAT_READ,
                        AuthScope.CHAT_EDIT,
                        AuthScope.MODERATOR_READ_CHATTERS,
                        AuthScope.MODERATOR_MANAGE_BANNED_USERS,
                        AuthScope.MODERATOR_READ_FOLLOWERS]
white_list_location = "whitelist.json"
black_list_location = "blacklist.json"
channel_location = "joinable_channels.json"

ss = StreamerShield(model_path,
                    max_lenght,
                    scammer_threshold,
                    user_threshold)
l= Logger(console_log=True, file_logging=True)

commands = {
"help":{
    "help": "!help: prints all commands",
    "value": False,
    "cli_func": help_cli,
    "twt_func": help_twitch
    },
"stop":{
    "help": "!stop: stops the process (Not available for Twitch)",
    "value": False,
    "cli_func": stop_cli,
    "twt_func": stop_twitch
},
"arm":{
        "help": "!arm: enables StreamerShield to ban users",
        "value": False,
        "cli_func": arm_cli,
        "twt_func": arm_twitch
        },
"disarm":{
        "help": "!disarm: stops StreamerShield from banning users",
        "value": False,
        "cli_func": disarm_cli,
        "twt_func": disarm_twitch
        },
"join":{
        "help": "!join chat_name: joins a chat",
        "value": True,
        "cli_func": join_cli,
        "twt_func": join_twitch
        },
"leave":{
        "help": "!leave chat_name: leaves a chat",
        "value": True,
        "cli_func": leave_cli,
        "twt_func": leave_twitch
        },
"whitelist":{
        "help": "!whitelist user_name: whitelist user",
        "value": True,
        "cli_func": whitelist_cli,
        "twt_func": whitelist_twitch
        },
"unwhitelist":{
        "help": "!unwhitelist user_name: removes user from whitelist",
        "value": True,
        "cli_func": unwhitelist_cli,
        "twt_func": unwhitelist_twitch
        },
"blacklist":{
        "help": "!blacklist user_name: blacklist user",
        "value": True,
        "cli_func": blacklist_cli,
        "twt_func": blacklist_twitch
        },
"unblacklist":{
        "help": "!unblacklist user_name: removes user from blacklist",
        "value": True,
        "cli_func": unblacklist_cli,
        "twt_func": unblacklist_twitch
        }, 
"streamershield":{
    "help": "!streamershield : prints info about the shield",
        "value": False,
        "cli_func": shield_info_cli,
        "twt_func": shield_info_twitch
        }, 
"joinme":{
    "help": "!joinme : joins user, only available in the bot chat",
        "value": False,
        "cli_func": join_me_cli,
        "twt_func": join_me_twitch
        },
}


## program entry:

asyncio.run(run())