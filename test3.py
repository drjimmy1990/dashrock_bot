import asyncio
from dashrock.market.symbol_registry import SymbolRegistry

async def test():
    r = SymbolRegistry()
    await r.load_from_binance('https://testnet.binancefuture.com')
    info = r.get('XAGUSDT')
    print('XAGUSDT in registry:', info is not None)
    if info:
        print(info)

asyncio.run(test())
