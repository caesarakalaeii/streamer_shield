from logger import Logger
from streamer_shield import StreamerShield
from streamer_shield_train import train


if __name__ == "__main__":
    l= Logger(console_log=True)
    layers = [32, 16, 8]
    attempt = 5
    sequence_len = 30
    train("generated_data.csv", f"attempt_{attempt}.h5",f"vocabulary_{attempt}.json", layers=layers, kernel=5, patience = 2, epochs = 10, sequence_len=sequence_len)
    ss = StreamerShield(f"attempt_{attempt}.h5", f"vocabulary_{attempt}.json",sequence_len)
    correctly_identified_users_bool,correctly_identified_users_conf,correctly_identified_scammers_bool, correctly_identified_scammers_conf = ss.test(False)
    user_perc = 0
    for user in correctly_identified_users_bool:
        if user == True:
            user_perc +=1
    for scammer in correctly_identified_scammers_bool:
        if scammer == True:
            user_perc +=1
            
    total_perc = user_perc/(len(correctly_identified_scammers_bool)+ len(correctly_identified_users_bool))
    if(total_perc == 1):
        l.passingblue(f"Found good candidate with {layers}, stopping!")
    l.passing(f'''
              Test results:
              Users: {correctly_identified_users_bool}
              conf: {correctly_identified_users_conf}
              Scammer: {correctly_identified_scammers_bool}
              conf: {correctly_identified_scammers_conf}
              '''.replace(' ', ''))