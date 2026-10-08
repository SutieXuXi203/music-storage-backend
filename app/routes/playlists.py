from datetime import datetime, timezone
from typing import List, Optional
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from app.database import get_database
from app.models import (
    AddSongToPlaylistRequest,
    PlaylistCreate,
    PlaylistUpdate,
)
from app.routes.auth import get_current_user
from app.routes.songs import serialize_song

# Router chính cho Playlists
router = APIRouter(prefix="/api/playlists", tags=["Quản lý Playlist"])
# Router tương thích ngược cho Folders
folders_router = APIRouter(prefix="/api/folders", tags=["Quản lý thư mục (Tương thích)"])


async def _sync_legacy_folders_if_needed(db, user_id_str: str):
    """Đảm bảo dữ liệu giữa playlists và folders được đồng bộ"""
    p_count = await db.playlists.count_documents({"user_id": user_id_str})
    if p_count == 0:
        cursor = db.folders.find({"user_id": user_id_str})
        async for f_doc in cursor:
            # Check xem đã tồn tại bên playlists theo _id chưa
            exists = await db.playlists.find_one({"_id": f_doc["_id"]})
            if not exists:
                await db.playlists.insert_one(f_doc)


async def _get_playlist_cover(db, song_ids: List[str]) -> Optional[str]:
    """Lấy cover_url của bài hát đầu tiên trong playlist nếu có"""
    if not song_ids:
        return None
    try:
        first_song_id = song_ids[0]
        if not ObjectId.is_valid(first_song_id):
            return None
        song_doc = await db.songs.find_one({"_id": ObjectId(first_song_id)})
        if song_doc:
            s = serialize_song(song_doc)
            return s.get("cover_url")
    except Exception:
        pass
    return None


def serialize_playlist_summary(doc: dict, cover_url: Optional[str] = None) -> dict:
    song_ids = doc.get("song_ids", [])
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name", ""),
        "user_id": doc.get("user_id", ""),
        "user_username": doc.get("user_username", ""),
        "drive_folder_id": doc.get("drive_folder_id"),
        "is_default": doc.get("is_default", False),
        "song_ids": song_ids,
        "song_count": len(song_ids),
        "cover_url": cover_url,
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at") or doc.get("created_at"),
    }


# Handler implementations
async def _handle_list_playlists(current_user: dict):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=500, detail="Chưa kết nối cơ sở dữ liệu MongoDB.")

    user_id_str = str(current_user["_id"])
    from app.routes.auth import get_or_create_user_drive_folder
    try:
        await get_or_create_user_drive_folder(current_user)
    except Exception as e:
        print(f"[List Playlists] Cảnh báo đồng bộ thư mục người dùng: {e}")

    await _sync_legacy_folders_if_needed(db, user_id_str)

    cursor = db.playlists.find({"user_id": user_id_str}).sort([("is_default", -1), ("created_at", -1)])
    playlists = []

    async for doc in cursor:
        song_ids = doc.get("song_ids", [])
        cover_url = await _get_playlist_cover(db, song_ids)
        playlists.append(serialize_playlist_summary(doc, cover_url))

    return {
        "status": "success",
        "total": len(playlists),
        "data": playlists,
    }


async def _handle_create_playlist(req: PlaylistCreate, current_user: dict):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=500, detail="Chưa kết nối cơ sở dữ liệu MongoDB.")

    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Tên playlist không được để trống.")

    user_id_str = str(current_user["_id"])
    now = datetime.now(timezone.utc)

    playlist_doc = {
        "name": name,
        "user_id": user_id_str,
        "user_username": current_user.get("username"),
        "is_default": False,
        "song_ids": [],
        "created_at": now,
        "updated_at": now,
    }

    result = await db.playlists.insert_one(playlist_doc)
    playlist_doc["_id"] = result.inserted_id

    # Đồng bộ sang collection folders để tương thích ngược
    try:
        await db.folders.insert_one(dict(playlist_doc))
    except Exception:
        pass

    return {
        "status": "success",
        "message": f"Đã tạo playlist '{name}' thành công.",
        "data": serialize_playlist_summary(playlist_doc),
    }


async def _handle_get_playlist(playlist_id: str, current_user: dict):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=500, detail="Chưa kết nối cơ sở dữ liệu MongoDB.")

    if not ObjectId.is_valid(playlist_id):
        raise HTTPException(status_code=400, detail="Mã playlist không hợp lệ.")

    playlist = await db.playlists.find_one({"_id": ObjectId(playlist_id)})
    if not playlist:
        # Fallback thử tìm trong folders
        playlist = await db.folders.find_one({"_id": ObjectId(playlist_id)})
        if not playlist:
            raise HTTPException(status_code=404, detail="Không tìm thấy playlist.")

    if str(playlist.get("user_id")) != str(current_user["_id"]):
        raise HTTPException(status_code=403, detail="Bạn không có quyền truy cập playlist này.")

    song_ids = playlist.get("song_ids", [])
    valid_obj_ids = [ObjectId(sid) for sid in song_ids if ObjectId.is_valid(sid)]

    songs_map = {}
    if valid_obj_ids:
        cursor = db.songs.find({
            "_id": {"$in": valid_obj_ids},
            "user_id": str(current_user["_id"]),
        })
        async for s_doc in cursor:
            s_dict = serialize_song(s_doc)
            songs_map[s_dict["id"]] = s_dict

    ordered_songs = []
    for sid in song_ids:
        if sid in songs_map:
            ordered_songs.append(songs_map[sid])

    cover_url = ordered_songs[0].get("cover_url") if ordered_songs else None

    summary = serialize_playlist_summary(playlist, cover_url)
    summary["songs"] = ordered_songs

    return {
        "status": "success",
        "data": summary,
    }


async def _handle_update_playlist(playlist_id: str, req: PlaylistUpdate, current_user: dict):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=500, detail="Chưa kết nối cơ sở dữ liệu MongoDB.")

    if not ObjectId.is_valid(playlist_id):
        raise HTTPException(status_code=400, detail="Mã playlist không hợp lệ.")

    playlist = await db.playlists.find_one({"_id": ObjectId(playlist_id)})
    if not playlist:
        playlist = await db.folders.find_one({"_id": ObjectId(playlist_id)})
        if not playlist:
            raise HTTPException(status_code=404, detail="Không tìm thấy playlist.")

    if str(playlist.get("user_id")) != str(current_user["_id"]):
        raise HTTPException(status_code=403, detail="Bạn không có quyền chỉnh sửa playlist này.")

    new_name = req.name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="Tên playlist không được để trống.")

    now = datetime.now(timezone.utc)
    await db.playlists.update_one(
        {"_id": ObjectId(playlist_id)},
        {"$set": {"name": new_name, "updated_at": now}},
    )
    await db.folders.update_one(
        {"_id": ObjectId(playlist_id)},
        {"$set": {"name": new_name, "updated_at": now}},
    )

    playlist["name"] = new_name
    playlist["updated_at"] = now
    cover_url = await _get_playlist_cover(db, playlist.get("song_ids", []))

    return {
        "status": "success",
        "message": f"Đã đổi tên playlist thành '{new_name}'.",
        "data": serialize_playlist_summary(playlist, cover_url),
    }


async def _handle_delete_playlist(playlist_id: str, current_user: dict):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=500, detail="Chưa kết nối cơ sở dữ liệu MongoDB.")

    if not ObjectId.is_valid(playlist_id):
        raise HTTPException(status_code=400, detail="Mã playlist không hợp lệ.")

    playlist = await db.playlists.find_one({"_id": ObjectId(playlist_id)})
    if not playlist:
        playlist = await db.folders.find_one({"_id": ObjectId(playlist_id)})
        if not playlist:
            raise HTTPException(status_code=404, detail="Không tìm thấy playlist.")

    if str(playlist.get("user_id")) != str(current_user["_id"]):
        raise HTTPException(status_code=403, detail="Bạn không có quyền xóa playlist này.")

    if playlist.get("is_default"):
        raise HTTPException(status_code=400, detail="Không thể xóa playlist mặc định của tài khoản.")

    await db.playlists.delete_one({"_id": ObjectId(playlist_id)})
    await db.folders.delete_one({"_id": ObjectId(playlist_id)})

    return {
        "status": "success",
        "message": f"Đã xóa playlist '{playlist.get('name')}' thành công.",
    }


async def _handle_add_or_move_song(playlist_id: str, req: AddSongToPlaylistRequest, current_user: dict):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=500, detail="Chưa kết nối cơ sở dữ liệu MongoDB.")

    if not ObjectId.is_valid(playlist_id):
        raise HTTPException(status_code=400, detail="Mã playlist không hợp lệ.")

    playlist = await db.playlists.find_one({"_id": ObjectId(playlist_id)})
    if not playlist:
        playlist = await db.folders.find_one({"_id": ObjectId(playlist_id)})
        if not playlist:
            raise HTTPException(status_code=404, detail="Không tìm thấy playlist đích.")

    if str(playlist.get("user_id")) != str(current_user["_id"]):
        raise HTTPException(status_code=403, detail="Bạn không có quyền thao tác trên playlist này.")

    song_id = req.song_id.strip()
    if not ObjectId.is_valid(song_id):
        raise HTTPException(status_code=400, detail="Mã bài hát không hợp lệ.")

    song = await db.songs.find_one({"_id": ObjectId(song_id)})
    if not song:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài hát.")

    if song.get("user_id") and str(song.get("user_id")) != str(current_user["_id"]):
        raise HTTPException(status_code=403, detail="Bạn không có quyền thêm bài hát của người khác vào playlist.")

    now = datetime.now(timezone.utc)
    from_id = req.from_playlist_id or req.from_folder_id

    # 1. Nếu chuyển từ playlist khác
    if from_id and from_id != playlist_id and ObjectId.is_valid(from_id):
        await db.playlists.update_one(
            {"_id": ObjectId(from_id), "user_id": str(current_user["_id"])},
            {"$pull": {"song_ids": song_id}, "$set": {"updated_at": now}},
        )
        await db.folders.update_one(
            {"_id": ObjectId(from_id), "user_id": str(current_user["_id"])},
            {"$pull": {"song_ids": song_id}, "$set": {"updated_at": now}},
        )

    # 2. Thêm vào playlist đích
    await db.playlists.update_one(
        {"_id": ObjectId(playlist_id)},
        {"$addToSet": {"song_ids": song_id}, "$set": {"updated_at": now}},
    )
    await db.folders.update_one(
        {"_id": ObjectId(playlist_id)},
        {"$addToSet": {"song_ids": song_id}, "$set": {"updated_at": now}},
    )

    updated_playlist = await db.playlists.find_one({"_id": ObjectId(playlist_id)}) or await db.folders.find_one({"_id": ObjectId(playlist_id)})
    cover_url = await _get_playlist_cover(db, updated_playlist.get("song_ids", []))

    return {
        "status": "success",
        "message": f"Đã thêm bài hát '{song.get('title')}' vào playlist '{playlist.get('name')}'.",
        "data": serialize_playlist_summary(updated_playlist, cover_url),
    }


async def _handle_remove_song(playlist_id: str, song_id: str, current_user: dict):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=500, detail="Chưa kết nối cơ sở dữ liệu MongoDB.")

    if not ObjectId.is_valid(playlist_id):
        raise HTTPException(status_code=400, detail="Mã playlist không hợp lệ.")

    playlist = await db.playlists.find_one({"_id": ObjectId(playlist_id)})
    if not playlist:
        playlist = await db.folders.find_one({"_id": ObjectId(playlist_id)})
        if not playlist:
            raise HTTPException(status_code=404, detail="Không tìm thấy playlist.")

    if str(playlist.get("user_id")) != str(current_user["_id"]):
        raise HTTPException(status_code=403, detail="Bạn không có quyền thao tác trên playlist này.")

    now = datetime.now(timezone.utc)
    await db.playlists.update_one(
        {"_id": ObjectId(playlist_id)},
        {"$pull": {"song_ids": song_id}, "$set": {"updated_at": now}},
    )
    await db.folders.update_one(
        {"_id": ObjectId(playlist_id)},
        {"$pull": {"song_ids": song_id}, "$set": {"updated_at": now}},
    )

    updated_playlist = await db.playlists.find_one({"_id": ObjectId(playlist_id)}) or await db.folders.find_one({"_id": ObjectId(playlist_id)})
    cover_url = await _get_playlist_cover(db, updated_playlist.get("song_ids", []))

    return {
        "status": "success",
        "message": f"Đã gỡ bài hát khỏi playlist '{playlist.get('name')}'.",
        "data": serialize_playlist_summary(updated_playlist, cover_url),
    }


# === ROUTE DEFINITIONS FOR /api/playlists ===
@router.get("", summary="Lấy danh sách playlist của người dùng")
async def list_playlists(current_user: dict = Depends(get_current_user)):
    return await _handle_list_playlists(current_user)

@router.post("", status_code=status.HTTP_201_CREATED, summary="Tạo playlist mới")
async def create_playlist(req: PlaylistCreate, current_user: dict = Depends(get_current_user)):
    return await _handle_create_playlist(req, current_user)

@router.get("/{playlist_id}", summary="Xem chi tiết playlist")
async def get_playlist(playlist_id: str, current_user: dict = Depends(get_current_user)):
    return await _handle_get_playlist(playlist_id, current_user)

@router.put("/{playlist_id}", summary="Đổi tên playlist")
async def update_playlist(playlist_id: str, req: PlaylistUpdate, current_user: dict = Depends(get_current_user)):
    return await _handle_update_playlist(playlist_id, req, current_user)

@router.delete("/{playlist_id}", summary="Xóa playlist")
async def delete_playlist(playlist_id: str, current_user: dict = Depends(get_current_user)):
    return await _handle_delete_playlist(playlist_id, current_user)

@router.post("/{playlist_id}/songs", summary="Thêm bài hát vào playlist")
async def add_or_move_song_to_playlist(playlist_id: str, req: AddSongToPlaylistRequest, current_user: dict = Depends(get_current_user)):
    return await _handle_add_or_move_song(playlist_id, req, current_user)

@router.delete("/{playlist_id}/songs/{song_id}", summary="Gỡ bài hát khỏi playlist")
async def remove_song_from_playlist(playlist_id: str, song_id: str, current_user: dict = Depends(get_current_user)):
    return await _handle_remove_song(playlist_id, song_id, current_user)


# === ROUTE DEFINITIONS FOR /api/folders (Backward Compatibility) ===
@folders_router.get("", summary="Lấy danh sách thư mục (Tương thích)")
async def list_folders(current_user: dict = Depends(get_current_user)):
    return await _handle_list_playlists(current_user)

@folders_router.post("", status_code=status.HTTP_201_CREATED, summary="Tạo thư mục (Tương thích)")
async def create_folder(req: PlaylistCreate, current_user: dict = Depends(get_current_user)):
    return await _handle_create_playlist(req, current_user)

@folders_router.get("/{folder_id}", summary="Xem chi tiết thư mục (Tương thích)")
async def get_folder(folder_id: str, current_user: dict = Depends(get_current_user)):
    return await _handle_get_playlist(folder_id, current_user)

@folders_router.put("/{folder_id}", summary="Đổi tên thư mục (Tương thích)")
async def update_folder(folder_id: str, req: PlaylistUpdate, current_user: dict = Depends(get_current_user)):
    return await _handle_update_playlist(folder_id, req, current_user)

@folders_router.delete("/{folder_id}", summary="Xóa thư mục (Tương thích)")
async def delete_folder(folder_id: str, current_user: dict = Depends(get_current_user)):
    return await _handle_delete_playlist(folder_id, current_user)

@folders_router.post("/{folder_id}/songs", summary="Thêm bài hát vào thư mục (Tương thích)")
async def add_or_move_song_to_folder(folder_id: str, req: AddSongToPlaylistRequest, current_user: dict = Depends(get_current_user)):
    return await _handle_add_or_move_song(folder_id, req, current_user)

@folders_router.delete("/{folder_id}/songs/{song_id}", summary="Gỡ bài hát khỏi thư mục (Tương thích)")
async def remove_song_from_folder(folder_id: str, song_id: str, current_user: dict = Depends(get_current_user)):
    return await _handle_remove_song(folder_id, song_id, current_user)
