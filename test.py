import asyncio
import httpx

async def test():
    async with httpx.AsyncClient() as client:
        resp = await client.get('https://testnet.binancefuture.com/fapi/v1/exchangeInfo')
        symbols = [s['symbol'] for s in resp.json()['symbols']]
        print('XAGUSDT in testnet:', 'XAGUSDT' in symbols)

asyncio.run(test())
