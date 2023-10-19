import pickle

def save_vocab(vocab, filename='shield_cnn/net/vocabulary.pkl'):
    with open(filename, 'wb') as f:
        pickle.dump(vocab, f)

def load_vocab(filename='vocabulary.pkl'):
    with open(filename, 'rb') as f:
        vocab = pickle.load(f)
    return vocab