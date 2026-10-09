import os
import sys
import asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings

async def main():
    print("Connecting to MongoDB...")
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.DATABASE_NAME]
    
    cols = await db.list_collection_names()
    print(f"Collections before: {cols}")
    
    if "playlists" in cols:
        await db.drop_collection("playlists")
        print("Successfully dropped 'playlists' collection.")
    else:
        print("'playlists' collection not found or already dropped.")
        
    cols_after = await db.list_collection_names()
    print(f"Collections after: {cols_after}")
    client.close()

if __name__ == "__main__":
    asyncio.run(main())
