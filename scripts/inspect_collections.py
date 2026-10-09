import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
import asyncio
from app.database import connect_to_mongo, close_mongo_connection, get_database

async def main():
    await connect_to_mongo()
    db = get_database()
    f_cnt = await db.folders.count_documents({})
    p_cnt = await db.playlists.count_documents({})
    print(f"Folders count: {f_cnt}")
    print(f"Playlists count: {p_cnt}")
    
    print("\n--- SAMPLE FOLDERS ---")
    async for f in db.folders.find().limit(5):
        print(f"Folder: id={f['_id']}, name={f.get('name')}, is_default={f.get('is_default')}, drive_id={f.get('drive_folder_id')}, songs={len(f.get('song_ids', []))}")
        
    print("\n--- SAMPLE PLAYLISTS ---")
    async for p in db.playlists.find().limit(5):
        print(f"Playlist: id={p['_id']}, name={p.get('name')}, is_default={p.get('is_default')}, drive_id={p.get('drive_folder_id')}, songs={len(p.get('song_ids', []))}")

    await close_mongo_connection()

if __name__ == "__main__":
    asyncio.run(main())
