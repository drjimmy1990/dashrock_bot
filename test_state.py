"""Check current orders + position on Binance testnet."""
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
    return r.json()


async def main():
    async with httpx.AsyncClient() as c:
        # Regular orders
        reg = await signed_get(c, "/fapi/v1/openOrders", {"symbol": "XAGUSDT"})
        count = len(reg) if isinstance(reg, list) else "err"
        print(f"REGULAR ORDERS ({count}):")
        if isinstance(reg, list):
            for o in reg:
                print(f"  type={o['type']} side={o['side']} qty={o['origQty']} stop={o.get('stopPrice', '?')} id={o['orderId']}")
        else:
            print(f"  {reg}")

        # Algo orders
        algo = await signed_get(c, "/fapi/v1/openAlgoOrders", {"symbol": "XAGUSDT"})
        orders = algo.get("orders", []) if isinstance(algo, dict) else []
        print(f"\nALGO ORDERS ({len(orders)}):")
        for o in orders:
            print(f"  type={o.get('type', '?')} side={o.get('side', '?')} "
                  f"trigger={o.get('triggerPrice', '?')} callback={o.get('callbackRate', '?')} "
                  f"activate={o.get('activatePrice', '?')} id={o.get('algoId', '?')}")

        # Position
        pos = await signed_get(c, "/fapi/v2/positionRisk", {"symbol": "XAGUSDT"})
        print("\nPOSITION:")
        for p in pos:
            if isinstance(p, dict):
                qty = float(p.get("positionAmt", 0))
                if qty != 0:
                    side = "LONG" if qty > 0 else "SHORT"
                    print(f"  {side} qty={abs(qty)} entry={p['entryPrice']}")
        
        # Also check engine state
        try:
            r = await c.get("http://localhost:8000/api/status")
            data = r.json()
            for sym, s in data.get("symbols", {}).items():
                if s.get("position_state") != "FLAT":
                    print(f"\nENGINE STATE ({sym}):")
                    print(f"  position={s['position_state']} sl_id={s.get('sl_id')} tsl_id={s.get('tsl_id')} sl_price={s.get('sl_price')}")
        except Exception as e:
            print(f"\nEngine API: {e}")


asyncio.run(main())
