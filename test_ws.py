"""Check ALL open orders on Binance (both regular + algo)"""
import asyncio, os, time, hashlib, hmac, urllib.parse
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
    return r.json()

async def main():
    async with httpx.AsyncClient() as c:
        # Regular open orders
        reg = await signed_get(c, "/fapi/v1/openOrders", {"symbol": "XAGUSDT"})
        print(f"=== REGULAR OPEN ORDERS ({len(reg) if isinstance(reg, list) else 'ERR'}) ===")
        if isinstance(reg, list):
            for o in reg:
                print(f"  {o['type']} {o['side']} qty={o['origQty']} stop={o.get('stopPrice')} id={o['orderId']}")
        else:
            print(f"  {reg}")

        # Algo open orders
        algo = await signed_get(c, "/fapi/v1/openAlgoOrders", {"symbol": "XAGUSDT"})
        algo_orders = algo.get("orders", algo) if isinstance(algo, dict) else algo
        print(f"\n=== ALGO OPEN ORDERS ({len(algo_orders) if isinstance(algo_orders, list) else 'ERR'}) ===")
        if isinstance(algo_orders, list):
            for o in algo_orders:
                print(f"  {o.get('type','?')} {o.get('side','?')} qty={o.get('origQty','?')} "
                      f"stop={o.get('triggerPrice','?')} callback={o.get('callbackRate','?')} "
                      f"activate={o.get('activatePrice','?')} id={o.get('algoId', o.get('orderId','?'))}")
        else:
            print(f"  {algo_orders}")

        # Position check
        positions = await signed_get(c, "/fapi/v2/positionRisk", {"symbol": "XAGUSDT"})
        print(f"\n=== POSITION ===")
        for p in positions:
            if isinstance(p, dict):
                qty = float(p.get("positionAmt", 0))
                if qty != 0:
                    print(f"  {'LONG' if qty > 0 else 'SHORT'} qty={abs(qty)} entry={p['entryPrice']}")

asyncio.run(main())
