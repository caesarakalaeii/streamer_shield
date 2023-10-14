from streamer_shield_train import preprocess_string_data, clean_data
import tensorflow as tf

class StreamerShield:
    
    def __init__(self, model_path, max_length, scam_threshold, user_threshold) -> None:
        print("loading model")
        self.max_length = max_length
        self.scam_threshold = scam_threshold
        self.user_threshold = user_threshold
        self.loaded_model = tf.keras.models.load_model(model_path)

    def predict(self,string):
        print("preprocessing name")
        string = clean_data(string)
        processed_string, _ = preprocess_string_data([string], self.max_length)
        print("predicting...")
        is_scammer = self.loaded_model(processed_string)
        
        return is_scammer
    
    
if __name__ == "__main__":
    ss = StreamerShield("G:\VS_repos\streamer_shield\streamershield.h5", 25, 0.8, 0.5)
    onehot = False
    test_names_users = ["caesarlp", "VTNiles", "RustoCa", "norari__" ]
    test_names_scammers = ["Sophie_Howard25", "Jessica_Bell", "Amber_Brooks", "Alice_gfx"  ]
    while(True):
        name = input("Specify username\n").replace(" ", "")
        if name == "stop":
            print("Stopping...")
            break
        if name == "test":
            if onehot:
                for user in test_names_users:
                    conf = ss.predict(user)[0]
                    print(f"{conf[0] < conf[1]} user: {user} \nconf: {conf}")
                for user in test_names_scammers:
                    conf = ss.predict(user)[0]
                    print(f"{conf[0] > conf[1]} scammer: {user} \nconf: {conf}")
            else:
                for user in test_names_users:
                    conf = ss.predict(user)[0][0]
                    print(f"{conf < ss.user_threshold} user: {user} \nconf: {conf}")
                for user in test_names_scammers:
                    conf = ss.predict(user)[0][0]
                    print(f"{conf > ss.scam_threshold} scammer: {user} \nconf: {conf}")
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
            
        