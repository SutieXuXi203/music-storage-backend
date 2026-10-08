import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone
from bson import ObjectId
from app.database import connect_to_mongo, get_database
from app.services.drive_service import drive_service

sys.stdout.reconfigure(encoding='utf-8')

async def migrate():
    await connect_to_mongo()
    db = get_database()
    users = await db.users.find().to_list(100)
    print(f"Total users to check: {len(users)}")

    for u in users:
        user_id_str = str(u['_id'])
        user_name = (u.get('full_name') or u.get('username') or 'User').strip()
        drive_folder_id = u.get('drive_folder_id')

        # 1. Update Drive folder metadata if exists
        if drive_folder_id:
            try:
                drive_service._get_service().files().update(
                    fileId=drive_folder_id,
                    body={
                        'description': f'User ID: {user_id_str}',
                        'appProperties': {'user_id': user_id_str},
                    },
                    supportsAllDrives=True
                ).execute()
                print(f"Updated Drive folder metadata for {user_name} ({drive_folder_id}) -> User ID: {user_id_str}")
            except Exception as e:
                print(f"Drive update warning for {user_name}: {e}")

        # 2. Check existing folder document in db.folders
        existing = await db.folders.find_one({'user_id': user_id_str, 'is_default': True})
        if not existing:
            existing = await db.folders.find_one({'user_id': user_id_str})

        songs_cursor = db.songs.find({'user_id': user_id_str})
        user_song_ids = [str(s['_id']) async for s in songs_cursor]
        now = datetime.now(timezone.utc)

        if not existing:
            folder_doc = {
                'name': user_name,
                'user_id': user_id_str,
                'user_username': u.get('username'),
                'drive_folder_id': drive_folder_id,
                'is_default': True,
                'song_ids': user_song_ids,
                'created_at': now,
                'updated_at': now,
            }
            res = await db.folders.insert_one(folder_doc)
            folder_id_str = str(res.inserted_id)
            print(f"Created folder in collection folders for user '{user_name}' -> ID: {folder_id_str}, songs: {len(user_song_ids)}")
            await db.users.update_one({'_id': u['_id']}, {'$set': {'default_folder_id': folder_id_str}})
        else:
            folder_id_str = str(existing['_id'])
            await db.folders.update_one(
                {'_id': existing['_id']},
                {'$set': {
                    'name': user_name,
                    'user_id': user_id_str,
                    'user_username': u.get('username'),
                    'drive_folder_id': drive_folder_id,
                    'is_default': True,
                    'song_ids': user_song_ids,
                    'updated_at': now,
                }}
            )
            print(f"Updated folder in collection folders for user '{user_name}' -> ID: {folder_id_str}, songs: {len(user_song_ids)}")
            await db.users.update_one({'_id': u['_id']}, {'$set': {'default_folder_id': folder_id_str}})

    print("\n=== MIGRATION COMPLETED SUCCESSFULLY ===")
    print("Listing all folders in collection 'folders':")
    folders = await db.folders.find().to_list(100)
    for f in folders:
        print({
            '_id': str(f.get('_id')),
            'name': f.get('name'),
            'user_id': f.get('user_id'),
            'user_username': f.get('user_username'),
            'drive_folder_id': f.get('drive_folder_id'),
            'is_default': f.get('is_default'),
            'song_ids': f.get('song_ids'),
            'song_count': len(f.get('song_ids', [])),
        })

if __name__ == '__main__':
    asyncio.run(migrate())
