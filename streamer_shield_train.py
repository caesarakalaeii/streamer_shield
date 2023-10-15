import re
import numpy as np
import pandas as pd
import tensorflow as tf
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
    string = re.sub('[^a-zA-Z0-9]', ' ',string)
    string = string.lower()
    return string


# Preprocess the string data to adapt for the CNN model
def preprocess_string_data(strings, sequence_len):
    # Creating a vocab set
    vocabulary = set(''.join(strings))
    vocab_len = len(vocabulary)

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
if __name__ == "__main__":
    train_data = np.array(classification_helper.load_csv("generated_data.csv"))
    #train_data = percentage_scammer(raw_train_data, 0.0)
    #test_data = np.array(classification_helper.load_csv("train_data.csv"))
    np.random.shuffle(train_data)
    #np.random.shuffle(test_data)
    oneHot = False
    for i in range(len(train_data)):
        train_data[i] = [clean_data(train_data[i,0]),int(train_data[i,1])]
    #cleaned_test = []
    #for i in range(len(test_data)):
    #    try:
    #        if train_data[i,0] == test_data[i,0]:
    #            continue
    #    except IndexError:
    #        pass
    #    cleaned_test.append([clean_data(test_data[i,0]), int(test_data[i,1])])
    # Parameters
    #test_data = np.array(cleaned_test)
    sequence_len = 25

    # Get processed data
    #test = train_data[:,0] #just the names
    #test = train_data[:,1] #just the classification
    
    int_strings, vocab_len = preprocess_string_data(train_data[:,0], sequence_len)
    #int_strings_test, _ = preprocess_string_data(test_data[:,0], sequence_len)
    # Encoding labels
    if oneHot:
        encoder = OneHotEncoder(sparse=False)
        int_labels = encoder.fit_transform(np.array(train_data[:,1]).reshape(-1, 1))
    else:
        encoder = LabelEncoder()
        int_labels = encoder.fit_transform(train_data[:,1])
    #int_labels_test = encoder.fit_transform(test_data[:,1])

    # Splitting the dataset into train and test datasets
    #x_train = int_strings
    #y_train = int_labels
    #x_test = int_strings_test
    #y_test = int_labels_test
    x_train, x_test, y_train, y_test = train_test_split(int_strings, int_labels, test_size=0.60)

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
            tf.keras.layers.Embedding(vocab_len+1, 32, input_length=sequence_len),
            tf.keras.layers.Conv1D(32, 3, activation='relu'),
            tf.keras.layers.GlobalAveragePooling1D(),
            tf.keras.layers.Dense(32, activation='relu'),
            tf.keras.layers.Dense(1, activation='sigmoid')
        ])

        model.compile(loss='binary_crossentropy',optimizer='adam',metrics=['accuracy'])

    earlystop  = tf.keras.callbacks.EarlyStopping(monitor='val_loss', patience=5, verbose=True,  restore_best_weights=True)
    callbacksList = [earlystop]
    
    history = model.fit(x_train, y_train, epochs=20, validation_data=(x_test, y_test), callbacks=callbacksList, verbose=True)


    # Save the trained model to a file
    if oneHot:
        model.save('streamershield_onehot.h5')
    else:
        model.save('streamershield.h5')
    
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
   
    