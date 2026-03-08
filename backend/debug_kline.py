import requests
import json
url = "http://localhost:8000/stocks/2408/kline?period=5d&interval=5m"
res = requests.get(url).json()
print("Keys:", res.keys())
data = res.get('data', [])
print("Count:", len(data))
if data:
    print("First item:", data[0])
