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
    
    # Remove is_default field or set to False for all folders
    res = await db.folders.update_many(
        {},
        {"$set": {"is_default": False}}
    )
    print(f"Updated {res.modified_count} folders: is_default set to False.")
    
    # Inspect all folders
    cursor = db.folders.find({})
    async for f in cursor:
        print(f"Folder: id={f['_id']}, name={f.get('name')}, is_default={f.get('is_default')}, cover_url={f.get('cover_url')}")
        
    client.close()

if __name__ == "__main__":
    asyncio.run(main())
