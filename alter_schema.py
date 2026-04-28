import asyncio
from dashrock.config import load_config
from dashrock.persistence.database import Database
from sqlalchemy import text
from pathlib import Path

from dotenv import load_dotenv

async def main():
    load_dotenv()
    cfg = load_config(Path("config.yaml"))
    db = Database(cfg.database)
    async with db._engine.begin() as conn:
        await conn.execute(text("ALTER TABLE trades ALTER COLUMN side TYPE VARCHAR(10);"))
        await conn.execute(text("ALTER TABLE orders ALTER COLUMN side TYPE VARCHAR(10);"))
        print("Schema altered successfully.")

asyncio.run(main())
