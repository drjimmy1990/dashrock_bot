import asyncio
import websockets

async def test():
    async with websockets.connect('ws://127.0.0.1:8000/ws?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTc3NzM0MjE5Nn0.APW0PnUD6jsI3F0F4lfKOgQY6wLu0BqMiMJQgVqw_qM') as ws:
        print('Connected!')
        
asyncio.run(test())
