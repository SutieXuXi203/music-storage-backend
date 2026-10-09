import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
import asyncio
from app.database import connect_to_mongo, close_mongo_connection, get_database

async def main():
    await connect_to_mongo()
    db = get_database()
    
    print("--- TRƯỚC KHI DỌN DẸP ---")
    f_count_before = await db.folders.count_documents({})
    p_count_before = await db.playlists.count_documents({})
    print(f"Tổng số Folders: {f_count_before}")
    print(f"Tổng số Playlists: {p_count_before}")
    
    # Tìm các bản ghi trong db.playlists có _id trùng với db.folders (do sync sao chép)
    # hoặc có is_default=True hoặc drive_folder_id (thuộc tính của thư mục Drive)
    folder_ids = [f["_id"] async for f in db.folders.find({}, {"_id": 1})]
    delete_filter = {
        "$or": [
            {"_id": {"$in": folder_ids}},
            {"is_default": True},
            {"drive_folder_id": {"$ne": None}},
        ]
    }
    
    deleted_result = await db.playlists.delete_many(delete_filter)
    print(f"\n=> Đã xóa {deleted_result.deleted_count} bản ghi thư mục sao chép thừa trong collection 'playlists'.")
    
    print("\n--- SAU KHI DỌN DẸP ---")
    f_count_after = await db.folders.count_documents({})
    p_count_after = await db.playlists.count_documents({})
    print(f"Folders count: {f_count_after}")
    print(f"Playlists count: {p_count_after}")
    
    print("\n--- DANH SÁCH FOLDERS HIỆN TẠI ---")
    async for f in db.folders.find():
        print(f"Folder: id={f['_id']}, name={f.get('name')}, is_default={f.get('is_default')}, songs={len(f.get('song_ids', []))}")
        
    print("\n--- DANH SÁCH PLAYLISTS HIỆN TẠI ---")
    async for p in db.playlists.find():
        print(f"Playlist: id={p['_id']}, name={p.get('name')}, songs={len(p.get('song_ids', []))}")

    await close_mongo_connection()

if __name__ == "__main__":
    asyncio.run(main())
