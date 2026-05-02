import requests

url = "https://fapi.binance.com/fapi/v1/exchangeInfo"

response = requests.get(url)

if response.status_code == 200:
    exchange_info = response.json()
    usdt_tickers = []

    for symbol in exchange_info["symbols"]:
        if symbol["quoteAsset"] == "USDT" and symbol["status"] == "TRADING":
            symbol_name = symbol["symbol"]
            if symbol_name is not None:
                usdt_tickers.append(symbol_name.lower())

    print(usdt_tickers)
else:
    print("Error retrieving exchange info: " + response.text)
