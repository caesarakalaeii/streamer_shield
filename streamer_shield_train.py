import re
import numpy as np
import pandas as pd
import tensorflow as tf
from vocab import load_vocab, save_vocab
import classification_helper
import matplotlib.pyplot as plt
from sklearn.preprocessing import LabelEncoder, OneHotEncoder
from sklearn.model_selection import train_test_split


def percentage_scammer(data, percentage):
    
    df = pd.DataFrame(data, columns=["names", "scammer"])
    scammers = df[df["scammer"] == "1"] 
    users = df[df["scammer"] == "0"] 
    usersample = users.sample(int(len(scammers)*(1-percentage)))
    train_set = np.concatenate((scammers.to_numpy(),usersample.to_numpy()), axis=0)
    train_set
    return train_set #works as intended
    
def clean_data(string):
    string = re.sub('[^a-zA-Z0-9_]', ' ',string)
    string = string.lower()
    return string


# Preprocess the string data to adapt for the CNN model
def preprocess_string_data(strings, sequence_len , vocab_path):
    # Creating a vocab set
    vocabulary = set(''.join(strings))
    save_vocab(vocabulary, filename=vocab_path)
    vocab_len = len(vocabulary)
    vocabulary = load_vocab(filename=vocab_path)#vocab changes after loading for some reason

    # Creating dictionary that maps each character to an integer
    char_index = dict((c, i) for i, c in enumerate(vocabulary))

    # Convert the string dataset to integer representation
    int_strings = []
    for s in strings:
        int_s = [char_index[c] for c in s]
        # Padding the string with 0's
        int_s = int_s[:sequence_len] + [0]*(sequence_len-len(int_s))
        int_strings.append(int_s)

    return np.array(int_strings), vocab_len


# Assuming your raw data looks like this
# It should be replaced with your actual dataset
def train(data_path, model_path,vocabulary_path ,layers = [32,32,32,1], kernel = 3, oneHot = False,balancing = 0.5,test_size = 0.3,  sequence_len = 25, patience = 5, epochs = 20):
    tf.config.list_physical_devices('GPU')
    train_data = np.array(classification_helper.load_csv(data_path))
    #train_data = percentage_scammer(train_data, balancing)
    np.random.shuffle(train_data)
    for i in range(len(train_data)):
        train_data[i] = [clean_data(train_data[i,0]),int(train_data[i,1])]
    

    
    int_strings, vocab_len = preprocess_string_data(train_data[:,0], sequence_len, vocabulary_path)
    if oneHot:
        encoder = OneHotEncoder(sparse=False)
        int_labels = encoder.fit_transform(np.array(train_data[:,1]).reshape(-1, 1))
    else:
        encoder = LabelEncoder()
        int_labels = encoder.fit_transform(train_data[:,1])
    x_train, x_test, y_train, y_test = train_test_split(int_strings, int_labels, test_size=test_size, random_state=42)

    # CNN model 
    if oneHot:
        model = tf.keras.models.Sequential([
        tf.keras.layers.Embedding(vocab_len+1, 64, input_length=sequence_len),
        tf.keras.layers.Conv1D(128, 5, activation='relu'),
        tf.keras.layers.GlobalAveragePooling1D(),
        tf.keras.layers.Dense(64, activation='relu'),
        tf.keras.layers.Dense(2, activation='softmax')
        ])
        model.compile(loss='categorical_crossentropy',optimizer='adam',metrics=['accuracy'])
    else:
        model = tf.keras.models.Sequential([
            tf.keras.layers.Embedding(vocab_len+1, layers[0], input_length=sequence_len),
            tf.keras.layers.Conv1D(layers[1], kernel, activation='relu'),
            tf.keras.layers.GlobalAveragePooling1D(),
            tf.keras.layers.Dense(layers[2], activation='relu'),
            tf.keras.layers.Dense(1, activation='sigmoid')
        ])

        model.compile(loss='binary_crossentropy',optimizer='adam',metrics=['accuracy'])

    earlystop  = tf.keras.callbacks.EarlyStopping(monitor='val_loss', 
                                                  patience=patience, 
                                                  verbose=True,  
                                                  restore_best_weights=True)
    callbacksList = [earlystop]
    
    history = model.fit(x_train, y_train,
                        epochs=epochs,
                        validation_data=(x_test, y_test),
                        callbacks=callbacksList,
                        verbose=True,
                        use_multiprocessing=True)


    # Save the trained model to a file
    model.save(model_path)
    
    lossMonitor = np.array(history.history['loss'])
    valLossMonitor = np.array(history.history['val_loss'])
    counts = np.arange(lossMonitor.shape[0])
    fig = plt.figure()
    ax = fig.add_subplot(1,1,1)
    ax.plot(counts,lossMonitor,'k', label='Trainingsdata')
    ax.plot(counts,valLossMonitor,'r:', label='Testdata')
    ax.set_xlabel('Epoch')
    ax.set_ylabel('Error')
    ax.legend()
    fig.savefig("shield_train.png")
   
   
