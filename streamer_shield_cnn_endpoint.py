from flask import Flask, request

app = Flask(__name__)

@app.route('/post_endpoint', methods=['POST'])
def handle_post_request():
    data = request.data  # Get the request data
    return f"Received POST request data: {data.decode('utf-8')}"

if __name__ == '__main__':
    port = 18080  # Change this to the port you want to use
    app.run(host='0.0.0.0', port=port)