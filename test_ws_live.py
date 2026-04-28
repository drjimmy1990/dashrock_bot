"""Quick WS test: connect and listen for 15 seconds."""
import asyncio
import json
import websockets
import urllib.request
import dotenv, os

dotenv.load_dotenv()

admin_user = os.getenv("ADMIN_USERNAME", "admin")
admin_pass = os.getenv("ADMIN_PASSWORD", "")
print(f"Logging in as: {admin_user}")

req = urllib.request.Request(
    "http://127.0.0.1:8000/api/auth/login",
    data=json.dumps({"username": admin_user, "password": admin_pass}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
resp = urllib.request.urlopen(req)
token_data = json.loads(resp.read().decode())
token = token_data["access_token"]
print(f"Got token: {token[:30]}...")

async def listen():
    url = f"ws://127.0.0.1:8000/ws?token={token}"
    print(f"Connecting to WS...")
    async with websockets.connect(url) as ws:
        print("✅ WS Connected! Listening for 15 seconds...")
        count = 0
        try:
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=15)
                data = json.loads(msg)
                event_type = data.get("type", "?")
                count += 1
                print(f"  [{count}] {event_type}: {json.dumps(data.get('data', {}))[:120]}")
        except asyncio.TimeoutError:
            print("(timed out waiting for next message)")
        print(f"\nTotal messages received in 15s: {count}")

asyncio.run(listen())
