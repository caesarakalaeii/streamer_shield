from streamer_shield_train import train
from streamer_shield import StreamerShield
from logger import Logger
import random

if __name__ == "__main__":
    max_layer_len = 128
    min_layer_len = 16
    step = 16
    l = Logger(ros_log= False, console_log= True, file_logging=True)
    correctly_identified_users = []
    correctly_identified_scammers = []
    good_values = []
    prev_best = 0
    try:
        for l1 in range(min_layer_len,max_layer_len,step):
            for l2 in range(min_layer_len,max_layer_len,step):
                for l3 in range(min_layer_len,max_layer_len,step):
                    if good_values == []:
                        good_values = [l1, l2, l3]
                    l.passing(f"Using {[l1, l2, l3]} as layers:")
                    l.info("Training...")
                    train("generated_data.csv", "auto_gen.h5", layers=[l1, l2, l3], patience = 10, epochs = 50)
                    l.info("Evaluating...")
                    ss = StreamerShield("auto_gen.h5",25, 0.5,0.5)
                    correctly_identified_users_bool,correctly_identified_users_conf,correctly_identified_scammers_bool, correctly_identified_scammers_conf = ss.test(False)
                    user_perc = 0
                    for user in correctly_identified_users_bool:
                        if user == True:
                            user_perc +=1
                    for scammer in correctly_identified_scammers_bool:
                        if scammer == True:
                            user_perc +=1
                            
                    total_perc = user_perc/(len(correctly_identified_scammers_bool)+ len(correctly_identified_users_bool))
                    if(total_perc>prev_best):
                        good_values = [l1, l2, l3]
                        l.passing(f"New best found: {[l1, l2, l3]}")
                        l.passing(f"conf is:\nUser: {correctly_identified_users_conf}\nScammer: {correctly_identified_scammers_conf}")
                    if(total_perc == 1):
                        l.passingblue(f"Found good candidate with {[l1, l2, l3]}, stopping!")
                        raise ValueError
    except:
        l.error(f"Error: Best try was: {good_values}")
        
    