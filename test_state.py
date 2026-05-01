import httpx, asyncio, json

async def check():
    async with httpx.AsyncClient() as c:
        r = await c.post("http://localhost:8000/api/auth/login", json={"username":"admin","password":"admin"})
        token = r.json().get("access_token","")
        h = {"Authorization": f"Bearer {token}"}
        r = await c.get("http://localhost:8000/api/state", headers=h)
        state = r.json()
        for sym, s in state.get("symbols", {}).items():
            print(f"Symbol: {sym}")
            print(f"  position_state: {s.get('position_state')}")
            print(f"  position_qty:   {s.get('position_qty')}")
            print(f"  entry_price:    {s.get('entry_price')}")
            print(f"  sl_id:          {s.get('sl_id')}")
            print(f"  sl_price:       {s.get('sl_price')}")
            print(f"  tp_id:          {s.get('tp_id')}")
            print(f"  cooldown:       {s.get('cooldown_remaining')}")

asyncio.run(check())
