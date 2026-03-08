import requests
import json

url = "http://localhost:8000/stocks/2408/kline?period=5d&interval=1m"
response = requests.get(url)
data = response.json()
print(f"Data count: {len(data['data'])}")
for r in data['data'][:10]:
    print(f"Date: {r['date']}, Close: {r['close']}, Vol: {r['volume']}")
