import requests

url = "http://localhost:38080/api/predict"
data = {"input_string": "rooooooberrrrrt"}

response = requests.post(url, json=data)

if response.status_code == 200:
    result = response.json()["result"]
    print("Result:", result/1000)
else:
    print("Error:", response.json())