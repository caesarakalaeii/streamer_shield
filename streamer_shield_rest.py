from flask import Flask, request, jsonify

from streamer_shield import StreamerShield

app = Flask(__name__)
shield = StreamerShield("shield.h5", 31, 0.5,.05)

# Create an endpoint that accepts a string and returns a float
@app.route('/api/predict', methods=['POST'])
def calculate():
    try:
        data = request.get_json()
        input_string = data['input_string']

        # You can perform your calculations here and return a float
        result = predict(input_string)

        return jsonify({'result': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

def predict(input_string):
    return shield.predict_with_process(input_string)

if __name__ == '__main__':
    app.run(debug=True)