from twitchAPI.type import AuthScope
from logger import Logger

class TwitchConfig:
    app_id : str
    app_secret : str      
    user_scopes : [AuthScope]
    white_list_location : str
    black_list_location : str
    channel_location : str
    user_name : str
    shield_url : str
    is_armed : bool = False
    auth_url : str
    model_path : str = 'shield_cnn/net/shield.h5'
    ban_reason : str = '''You've been banned by StreamerShield, if you think the was an Error, please make an unban request'''
    max_lenght : int = 30 #should be kept at 30, as the model was trained with it
    scammer_threshold : int = 0.5 #only used for test function, not used for evaluation, yet
    user_threshold : int = 0.5 #only used for test function, not used for evaluation, yet
    logger : Logger = Logger(console_log=True)