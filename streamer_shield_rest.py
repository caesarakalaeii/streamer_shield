import json
from flask import Flask, request, jsonify
import numpy as np

from streamer_shield import StreamerShield

app = Flask(__name__)
shield = StreamerShield("shield_len_30.h5","vocab_len_30.pkl" ,  30)

# Create an endpoint that accepts a string and returns a float
@app.route('/api/predict', methods=['POST'])
def calculate():
    try:
        data = request.get_json()
        
        input_string = data['input_string']

        # You can perform your calculations here and return a float
        result = predict(input_string).numpy()

        return jsonify({'result': np.floor(result[0][0]*1000)})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

def predict(input_string):
    return shield.predict(input_string)

if __name__ == '__main__':
    app.run(debug=False, port=38080)