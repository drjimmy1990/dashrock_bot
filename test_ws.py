"""Quick check: what does Binance testnet ACTUALLY show for XAGUSDT positions + orders?"""
import asyncio, os, time, hashlib, hmac, urllib.parse, json
import httpx

BASE = "https://testnet.binancefuture.com"
KEY = ""
SECRET = ""

with open(".env") as f:
    for line in f:
        line = line.strip()
        if line.startswith("BINANCE_TESTNET_API_KEY="):
            KEY = line.split("=", 1)[1]
        elif line.startswith("BINANCE_TESTNET_API_SECRET="):
            SECRET = line.split("=", 1)[1]

async def signed_get(client, path, params=None):
    params = params or {}
    params["timestamp"] = int(time.time() * 1000)
    qs = urllib.parse.urlencode(params)
    sig = hmac.new(SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()
    qs += f"&signature={sig}"
    r = await client.get(f"{BASE}{path}?{qs}", headers={"X-MBX-APIKEY": KEY})
    data = r.json()
    if isinstance(data, dict) and "code" in data:
        print(f"  API Error: {data}")
        return []
    return data

async def main():
    async with httpx.AsyncClient() as c:
        positions = await signed_get(c, "/fapi/v2/positionRisk", {"symbol": "XAGUSDT"})
        print("=== POSITIONS ===")
        for p in positions:
            if isinstance(p, dict):
                qty = float(p.get("positionAmt", 0))
                if qty != 0:
                    print(f"  Side={'LONG' if qty > 0 else 'SHORT'} qty={abs(qty)} entry={p['entryPrice']} pnl={p['unRealizedProfit']} positionSide={p.get('positionSide')}")
                else:
                    print(f"  {p.get('positionSide', '?')}: FLAT")

        orders = await signed_get(c, "/fapi/v1/openOrders", {"symbol": "XAGUSDT"})
        print(f"\n=== OPEN ORDERS ({len(orders)}) ===")
        for o in orders:
            if isinstance(o, dict):
                ts = int(o.get("time", 0))
                dt = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts/1000)) if ts else "?"
                print(f"  [{dt}] {o['type']} {o['side']} positionSide={o.get('positionSide')} "
                      f"qty={o['origQty']} stop={o.get('stopPrice')} "
                      f"callback={o.get('callbackRate')} activate={o.get('activatePrice')} "
                      f"id={o['orderId']}")

asyncio.run(main())
