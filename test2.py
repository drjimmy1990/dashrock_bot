import asyncio
import httpx

async def test():
    async with httpx.AsyncClient() as client:
        resp = await client.get('https://testnet.binancefuture.com/fapi/v1/exchangeInfo')
        s = next((s for s in resp.json()['symbols'] if s['symbol'] == 'XAGUSDT'), None)
        print(s['contractType'], s['quoteAsset'], s['status'])

asyncio.run(test())
