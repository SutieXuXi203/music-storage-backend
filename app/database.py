import certifi
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.config import settings

class DatabaseManager:
    client: AsyncIOMotorClient = None
    db: AsyncIOMotorDatabase = None

db_manager = DatabaseManager()

async def connect_to_mongo():
    try:
        print(f"Connecting to MongoDB at {settings.MONGODB_URL}...")
        db_manager.client = AsyncIOMotorClient(
            settings.MONGODB_URL,
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=5000,
        )
        db_manager.db = db_manager.client[settings.DATABASE_NAME]
        # Ping database to confirm connection
        await db_manager.client.admin.command('ping')
        print(f"Connected to MongoDB database: '{settings.DATABASE_NAME}' successfully.")
    except Exception as e:
        print(f"[CẢNH BÁO] Chưa thể kết nối MongoDB ngay lúc này: {e}")

async def close_mongo_connection():
    if db_manager.client:
        print("Closing MongoDB connection...")
        db_manager.client.close()
        print("MongoDB connection closed.")

def get_database() -> AsyncIOMotorDatabase:
    return db_manager.db
