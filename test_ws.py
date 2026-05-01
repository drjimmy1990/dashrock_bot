"""Full live Binance Futures connectivity test."""
import asyncio, json, time
import websockets, httpx

async def test():
    print("=== LIVE BINANCE FUTURES CONNECTIVITY TEST ===\n")

    # 1. REST API
    print("1. REST API (fapi/v1/ticker/price)")
    async with httpx.AsyncClient(timeout=10) as c:
        for sym in ["BTCUSDT", "XAGUSDT"]:
            try:
                r = await c.get("https://fapi.binance.com/fapi/v1/ticker/price", params={"symbol": sym})
                if r.status_code == 200:
                    price = r.json()["price"]
                    print(f"   {sym}: OK - price={price}")
                else:
                    print(f"   {sym}: HTTP {r.status_code}")
            except Exception as e:
                print(f"   {sym}: FAIL - {e}")

    # 2. WebSocket kline via /market
    print("\n2. WebSocket KLINE via /market route")
    for sym in ["btcusdt", "xagusdt"]:
        url = f"wss://fstream.binance.com/market/ws/{sym}@kline_1m"
        try:
            async with websockets.connect(url, open_timeout=5) as ws:
                msg = await asyncio.wait_for(ws.recv(), timeout=15)
                data = json.loads(msg)
                k = data.get("k", {})
                print(f"   {sym}: OK - close={k.get('c','?')} vol={k.get('v','?')}")
        except asyncio.TimeoutError:
            print(f"   {sym}: TIMEOUT - no data")
        except Exception as e:
            print(f"   {sym}: FAIL - {type(e).__name__}: {e}")

    # 3. WebSocket bookTicker via /public
    print("\n3. WebSocket BOOKTICKER via /public route")
    for sym in ["btcusdt", "xagusdt"]:
        url = f"wss://fstream.binance.com/public/ws/{sym}@bookTicker"
        try:
            async with websockets.connect(url, open_timeout=5) as ws:
                msg = await asyncio.wait_for(ws.recv(), timeout=10)
                data = json.loads(msg)
                print(f"   {sym}: OK - bid={data.get('b','?')} ask={data.get('a','?')}")
        except asyncio.TimeoutError:
            print(f"   {sym}: TIMEOUT - no data")
        except Exception as e:
            print(f"   {sym}: FAIL - {type(e).__name__}: {e}")

    # 4. Combined stream (how the engine uses it)
    print("\n4. Combined stream (engine mode)")
    sym = "xagusdt"
    got_kline = False
    got_book = False
    try:
        ws_m = await websockets.connect(
            f"wss://fstream.binance.com/market/stream?streams={sym}@kline_1m",
            open_timeout=5,
        )
        ws_p = await websockets.connect(
            f"wss://fstream.binance.com/public/stream?streams={sym}@bookTicker",
            open_timeout=5,
        )

        async def read_market():
            nonlocal got_kline
            msg = await asyncio.wait_for(ws_m.recv(), timeout=15)
            got_kline = True
            d = json.loads(msg)
            return d

        async def read_public():
            nonlocal got_book
            msg = await asyncio.wait_for(ws_p.recv(), timeout=10)
            got_book = True
            d = json.loads(msg)
            return d

        results = await asyncio.gather(read_market(), read_public(), return_exceptions=True)
        await ws_m.close()
        await ws_p.close()

        print(f"   kline (/market):      {'OK' if got_kline else 'FAIL'}")
        print(f"   bookTicker (/public): {'OK' if got_book else 'FAIL'}")
    except Exception as e:
        print(f"   FAIL - {e}")

    all_ok = got_kline and got_book
    print(f"\n{'=' * 50}")
    if all_ok:
        print("RESULT: ALL PASS - Live trading ready!")
    else:
        print("RESULT: ISSUES FOUND - check above")
    print(f"{'=' * 50}")

asyncio.run(test())
