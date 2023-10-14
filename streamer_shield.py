from streamer_shield_train import preprocess_string_data, clean_data
import tensorflow as tf

class StreamerShield:
    
    def __init__(self, model_path, max_length, threshold) -> None:
        print("loading model")
        self.max_length = max_length
        self.threshold = threshold
        self.loaded_model = tf.keras.models.load_model(model_path)

    def predict(self,string):
        print("preprocessing name")
        string = clean_data(string)
        processed_string, _ = preprocess_string_data([string], self.max_length)
        print("predicting...")
        is_scammer = self.loaded_model(processed_string)
        
        return is_scammer
    
    
if __name__ == "__main__":
    ss = StreamerShield("G:\VS_repos\streamer_shield\streamershield.h5", 25, 0.8)
    while(True):
        name = input("Specify username\n")
        if name == "stop":
            print("Stopping...")
            break
        else:
            is_scammer = ss.predict(name)[0][0]
            if is_scammer>ss.threshold:
                print(f"User {name} is a scammer! confidence = {is_scammer}")
            elif is_scammer>ss.threshold-0.2:
                print(f"User {name} is likely a scammer! confidence = {is_scammer}")
            else:
                print(f"User {name} is not a scammer! confidence = {is_scammer}")
            
        