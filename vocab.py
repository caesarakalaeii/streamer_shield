import json

def save_vocab(vocab, filename='vocabulary.json'):
    with open(filename, 'w') as f:
        json.dump(list(vocab), f)

def load_vocab(filename='vocabulary.json'):
    with open(filename, 'r') as f:
        vocab = list(json.load(f))
    return vocab