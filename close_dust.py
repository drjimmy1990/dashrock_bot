import asyncio, httpx, hashlib, hmac, time

async def main():
    key = "70xpJyFswCgujJKamazYaDiqkgzofi7KgO3ilMvULJ0lc2JJhRUYD3NiTOpSJTYh"
    secret = "W87lj9rlei7L7J5BpXbDh2p6bJmQSnrdOs5vigA1aMUDGOq5614rUMXKhspZQewD"
    base = "https://testnet.binancefuture.com"
    async with httpx.AsyncClient() as c:
        ts = int(time.time()*1000)
        q = f"symbol=XAGUSDT&timestamp={ts}&recvWindow=5000"
        sig = hmac.new(secret.encode(), q.encode(), hashlib.sha256).hexdigest()
        r = await c.get(f"{base}/fapi/v2/positionRisk?{q}&signature={sig}", headers={"X-MBX-APIKEY": key})
        for p in r.json():
            if p["symbol"] == "XAGUSDT":
                amt = float(p["positionAmt"])
                entry = p["entryPrice"]
                if amt != 0:
                    print(f"Position: {amt} XAG @ {entry}")
                    side = "BUY" if amt < 0 else "SELL"
                    qty = abs(amt)
                    ts2 = int(time.time()*1000)
                    q2 = f"symbol=XAGUSDT&side={side}&type=MARKET&quantity={qty}&reduceOnly=true&timestamp={ts2}&recvWindow=5000"
                    sig2 = hmac.new(secret.encode(), q2.encode(), hashlib.sha256).hexdigest()
                    r2 = await c.post(f"{base}/fapi/v1/order?{q2}&signature={sig2}", headers={"X-MBX-APIKEY": key})
                    print(f"Close dust: {r2.status_code} {r2.text[:300]}")
                else:
                    print("No position to close")

asyncio.run(main())
