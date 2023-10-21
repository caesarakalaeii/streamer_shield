from twitchAPI.type import AuthScope
from logger import Logger

class TwitchConfig:
    app_id : str
    app_secret : str      
    user_scopes : [AuthScope]
    white_list_location : str
    black_list_location : str
    channel_location : str
    known_users_location : str
    user_name : str
    shield_url : str
    is_armed : bool = False
    auth_url : str
    eventsub_url : str
    collect_data : bool
    admin : str
    age_threshold : int = 6
    ban_reason : str = '''You've been banned by StreamerShield, if you think the was an Error, please make an unban request'''
    logger : Logger = Logger(console_log=True)