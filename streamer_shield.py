from streamer_shield_train import clean_data
from vocab import load_vocab
import tensorflow as tf
import numpy as np

class StreamerShield:
    
    def __init__(self, model_path, max_length, scam_threshold, user_threshold) -> None:
        print("loading model")
        self.max_length = max_length
        self.scam_threshold = scam_threshold
        self.user_threshold = user_threshold
        self.loaded_model = tf.keras.models.load_model(model_path)
        
    def preprocess(self, string, sequence_len):
        # Creating a vocab set
        vocabulary = load_vocab()
        vocab_len = len(vocabulary)

        # Creating dictionary that maps each character to an integer
        char_index = dict((c, i) for i, c in enumerate(vocabulary))

        # Convert the string to integer representation
        int_s = [char_index[c] for c in string]
        # Padding the string with 0's
        int_s = int_s[:sequence_len] + [0]*(sequence_len-len(int_s))
        
        return np.array(int_s).reshape(1, -1), vocab_len

    def predict(self,string):
        print("preprocessing name")
        string = clean_data(string)
        processed_string, _ = self.preprocess(string, self.max_length)
        print("predicting...")
        is_scammer = self.loaded_model(processed_string)
        
        return is_scammer
    
    
    def test(self, onehot):
        test_names_users = ["caesarlp", "VTNiles", "RustoCa", "norari__" ]
        test_names_scammers = ["Sophie_Howard25", "Jessica_Bell", "Amber_Brooks", "Alice_gfx"  ]
        correctly_identified_users_bool = []
        correctly_identified_users_conf = []
        correctly_identified_scammers_bool = []
        correctly_identified_scammers_conf = []
        
        if onehot:
            for user in test_names_users:
                conf = self.predict(user)[0]
                correctly_identified_users_bool.append(conf[0] < conf[1])
                correctly_identified_users_conf.append(conf)
            for user in test_names_scammers:
                conf = self.predict(user)[0]
                correctly_identified_scammers_bool.append(conf[0] > conf[1])
                correctly_identified_scammers_conf.append(conf)
        else:
            for user in test_names_users:
                conf = self.predict(user)[0][0]
                correctly_identified_users_bool.append((conf < self.user_threshold) == True)
                correctly_identified_users_conf.append(conf)
            for user in test_names_scammers:
                conf = self.predict(user)[0][0]
                correctly_identified_scammers_bool.append((conf > self.scam_threshold) == True)
                correctly_identified_scammers_conf.append(conf)
        return correctly_identified_users_bool,correctly_identified_users_conf,correctly_identified_scammers_bool, correctly_identified_scammers_conf
        
    
if __name__ == "__main__":
    ss = StreamerShield("G:\VS_repos\streamer_shield\streamershield.h5", 25, 0.8, 0.5)
    onehot = False
    
    while(True):
        name = input("Specify username\n").replace(" ", "")
        if name == "stop":
            print("Stopping...")
            break
        if name == "test":
            ss.test(onehot)
        else:
            is_scammer = ss.predict(name)
            if(onehot):
                if is_scammer[0][0]>ss.user_threshold:
                    print(f"User {name} is not a scammer! \nuser_confidence = {is_scammer[0][0]}\nscam_confidence = {is_scammer[0][1]}")
                elif is_scammer[0][1]>ss.scam_threshold:
                    print(f"User {name} is a scammer! \nuser_confidence = {is_scammer[0][0]}\nscam_confidence = {is_scammer[0][1]}")
                elif is_scammer[0][1]>is_scammer[0][0]:
                    print(f"User {name} is likely a scammer! \nuser_confidence = {is_scammer[0][0]}\nscam_confidence = {is_scammer[0][1]}")
                elif is_scammer[0][1]<is_scammer[0][0]:
                    print(f"User {name} is likely a user! \nuser_confidence = {is_scammer[0][0]}\nscam_confidence = {is_scammer[0][1]}")
                else:
                    print(f"User {name} is a mystery! \nuser_confidence = {is_scammer[0][0]}\nscam_confidence = {is_scammer[0][1]}")
            else:
                if is_scammer[0][0]<ss.user_threshold:
                    print(f"User {name} is not a scammer! \nconfidence = {is_scammer[0][0]}")
                elif is_scammer[0][0]>ss.scam_threshold:
                    print(f"User {name} is a scammer! \nconfidence = {is_scammer[0][0]}")
                else:
                    print(f"User {name} is a mystery! \nconfidence = {is_scammer[0][0]}")
            
      