"""Add tsl_id column to engine_state table."""
import asyncio, os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

# Load DATABASE_URL from .env
with open(".env") as f:
    for line in f:
        line = line.strip()
        if line.startswith("DATABASE_URL="):
            os.environ["DATABASE_URL"] = line.split("=", 1)[1]

url = os.environ.get("DATABASE_URL", "")
if url.startswith("postgresql://"):
    url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

async def migrate():
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        try:
            await conn.execute(text("ALTER TABLE engine_state ADD COLUMN tsl_id VARCHAR(50)"))
            print("Column tsl_id added to engine_state")
        except Exception as e:
            if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                print("Column tsl_id already exists")
            else:
                print(f"Error: {e}")
    await engine.dispose()

asyncio.run(migrate())
