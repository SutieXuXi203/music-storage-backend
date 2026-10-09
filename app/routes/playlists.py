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

router = APIRouter(prefix="/api/playlists", tags=["Quản lý Playlist (Danh sách phát)"])


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
        "description": doc.get("description"),
        "user_id": doc.get("user_id", ""),
        "user_username": doc.get("user_username", ""),
        "song_ids": song_ids,
        "song_count": len(song_ids),
        "cover_url": cover_url,
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at") or doc.get("created_at"),
    }


@router.get(
    "",
    summary="Lấy danh sách playlist",
    description="Trả về danh sách tất cả các playlist của người dùng hiện tại",
)
async def list_playlists(current_user: dict = Depends(get_current_user)):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=500, detail="Chưa kết nối cơ sở dữ liệu MongoDB.")

    user_id_str = str(current_user["_id"])
    cursor = db.playlists.find({"user_id": user_id_str}).sort([("created_at", -1)])
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


@router.post(
    "",
    summary="Tạo playlist mới",
    description="Tạo một danh sách phát nhạc cá nhân mới cho người dùng",
    status_code=status.HTTP_201_CREATED,
)
async def create_playlist(
    req: PlaylistCreate,
    current_user: dict = Depends(get_current_user),
):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=500, detail="Chưa kết nối cơ sở dữ liệu MongoDB.")

    user_id_str = str(current_user["_id"])
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Tên playlist không được để trống.")

    # Kiểm tra tên playlist của user đã tồn tại chưa
    existing = await db.playlists.find_one({"user_id": user_id_str, "name": name})
    if existing:
        raise HTTPException(status_code=400, detail=f"Playlist '{name}' đã tồn tại.")

    now = datetime.now(timezone.utc)
    playlist_doc = {
        "name": name,
        "description": req.description.strip() if req.description else None,
        "user_id": user_id_str,
        "user_username": current_user.get("username"),
        "song_ids": [],
        "created_at": now,
        "updated_at": now,
    }

    result = await db.playlists.insert_one(playlist_doc)
    playlist_doc["_id"] = result.inserted_id

    return {
        "status": "success",
        "message": f"Đã tạo playlist '{name}' thành công.",
        "data": serialize_playlist_summary(playlist_doc),
    }


@router.get(
    "/{playlist_id}",
    summary="Chi tiết playlist",
    description="Lấy thông tin playlist kèm toàn bộ danh sách bài hát bên trong",
)
async def get_playlist(
    playlist_id: str,
    current_user: dict = Depends(get_current_user),
):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=500, detail="Chưa kết nối cơ sở dữ liệu MongoDB.")

    if not ObjectId.is_valid(playlist_id):
        raise HTTPException(status_code=400, detail="Mã playlist không hợp lệ.")

    playlist = await db.playlists.find_one({"_id": ObjectId(playlist_id)})
    if not playlist:
        raise HTTPException(status_code=404, detail="Không tìm thấy playlist.")

    if str(playlist.get("user_id")) != str(current_user["_id"]):
        raise HTTPException(status_code=403, detail="Bạn không có quyền truy cập playlist này.")

    song_ids = playlist.get("song_ids", [])
    valid_obj_ids = [ObjectId(sid) for sid in song_ids if ObjectId.is_valid(sid)]

    songs_map = {}
    if valid_obj_ids:
        cursor = db.songs.find({"_id": {"$in": valid_obj_ids}})
        async for s_doc in cursor:
            songs_map[str(s_doc["_id"])] = serialize_song(s_doc)

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


@router.put(
    "/{playlist_id}",
    summary="Cập nhật playlist",
    description="Cập nhật tên và/hoặc mô tả của playlist",
)
async def update_playlist(
    playlist_id: str,
    req: PlaylistUpdate,
    current_user: dict = Depends(get_current_user),
):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=500, detail="Chưa kết nối cơ sở dữ liệu MongoDB.")

    if not ObjectId.is_valid(playlist_id):
        raise HTTPException(status_code=400, detail="Mã playlist không hợp lệ.")

    playlist = await db.playlists.find_one({"_id": ObjectId(playlist_id)})
    if not playlist:
        raise HTTPException(status_code=404, detail="Không tìm thấy playlist.")

    if str(playlist.get("user_id")) != str(current_user["_id"]):
        raise HTTPException(status_code=403, detail="Bạn không có quyền chỉnh sửa playlist này.")

    update_fields = {}
    if req.name is not None:
        new_name = req.name.strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="Tên playlist không được để trống.")
        update_fields["name"] = new_name

    if req.description is not None:
        update_fields["description"] = req.description.strip()

    if not update_fields:
        raise HTTPException(status_code=400, detail="Không có thông tin thay đổi.")

    now = datetime.now(timezone.utc)
    update_fields["updated_at"] = now

    await db.playlists.update_one(
        {"_id": ObjectId(playlist_id)},
        {"$set": update_fields},
    )

    playlist.update(update_fields)
    cover_url = await _get_playlist_cover(db, playlist.get("song_ids", []))

    return {
        "status": "success",
        "message": "Đã cập nhật playlist thành công.",
        "data": serialize_playlist_summary(playlist, cover_url),
    }


@router.delete(
    "/{playlist_id}",
    summary="Xóa playlist",
    description="Xóa playlist khỏi hệ thống (các bài hát bên trong không bị xóa)",
)
async def delete_playlist(
    playlist_id: str,
    current_user: dict = Depends(get_current_user),
):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=500, detail="Chưa kết nối cơ sở dữ liệu MongoDB.")

    if not ObjectId.is_valid(playlist_id):
        raise HTTPException(status_code=400, detail="Mã playlist không hợp lệ.")

    playlist = await db.playlists.find_one({"_id": ObjectId(playlist_id)})
    if not playlist:
        raise HTTPException(status_code=404, detail="Không tìm thấy playlist.")

    if str(playlist.get("user_id")) != str(current_user["_id"]):
        raise HTTPException(status_code=403, detail="Bạn không có quyền xóa playlist này.")

    await db.playlists.delete_one({"_id": ObjectId(playlist_id)})

    return {
        "status": "success",
        "message": f"Đã xóa playlist '{playlist.get('name')}' thành công.",
    }


@router.post(
    "/{playlist_id}/songs",
    summary="Thêm bài hát vào playlist",
    description="Thêm một bài hát vào danh sách phát",
)
async def add_song_to_playlist(
    playlist_id: str,
    req: AddSongToPlaylistRequest,
    current_user: dict = Depends(get_current_user),
):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=500, detail="Chưa kết nối cơ sở dữ liệu MongoDB.")

    if not ObjectId.is_valid(playlist_id):
        raise HTTPException(status_code=400, detail="Mã playlist không hợp lệ.")

    playlist = await db.playlists.find_one({"_id": ObjectId(playlist_id)})
    if not playlist:
        raise HTTPException(status_code=404, detail="Không tìm thấy playlist.")

    if str(playlist.get("user_id")) != str(current_user["_id"]):
        raise HTTPException(status_code=403, detail="Bạn không có quyền thao tác trên playlist này.")

    song_id = req.song_id.strip()
    if not ObjectId.is_valid(song_id):
        raise HTTPException(status_code=400, detail="Mã bài hát không hợp lệ.")

    song = await db.songs.find_one({"_id": ObjectId(song_id)})
    if not song:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài hát.")

    if song.get("user_id") and str(song.get("user_id")) != str(current_user["_id"]):
        raise HTTPException(status_code=403, detail="Bạn không có quyền thêm bài hát này.")

    now = datetime.now(timezone.utc)
    await db.playlists.update_one(
        {"_id": ObjectId(playlist_id)},
        {
            "$addToSet": {"song_ids": song_id},
            "$set": {"updated_at": now},
        },
    )

    updated_playlist = await db.playlists.find_one({"_id": ObjectId(playlist_id)})
    cover_url = await _get_playlist_cover(db, updated_playlist.get("song_ids", []))

    return {
        "status": "success",
        "message": f"Đã thêm bài hát '{song.get('title')}' vào playlist '{playlist.get('name')}'.",
        "data": serialize_playlist_summary(updated_playlist, cover_url),
    }


@router.delete(
    "/{playlist_id}/songs/{song_id}",
    summary="Xóa bài hát khỏi playlist",
    description="Gỡ một bài hát ra khỏi playlist (bài hát vẫn còn trong kho nhạc)",
)
async def remove_song_from_playlist(
    playlist_id: str,
    song_id: str,
    current_user: dict = Depends(get_current_user),
):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=500, detail="Chưa kết nối cơ sở dữ liệu MongoDB.")

    if not ObjectId.is_valid(playlist_id):
        raise HTTPException(status_code=400, detail="Mã playlist không hợp lệ.")

    playlist = await db.playlists.find_one({"_id": ObjectId(playlist_id)})
    if not playlist:
        raise HTTPException(status_code=404, detail="Không tìm thấy playlist.")

    if str(playlist.get("user_id")) != str(current_user["_id"]):
        raise HTTPException(status_code=403, detail="Bạn không có quyền thao tác trên playlist này.")

    now = datetime.now(timezone.utc)
    await db.playlists.update_one(
        {"_id": ObjectId(playlist_id)},
        {
            "$pull": {"song_ids": song_id},
            "$set": {"updated_at": now},
        },
    )

    updated_playlist = await db.playlists.find_one({"_id": ObjectId(playlist_id)})
    cover_url = await _get_playlist_cover(db, updated_playlist.get("song_ids", []))

    return {
        "status": "success",
        "message": f"Đã xóa bài hát khỏi playlist '{playlist.get('name')}'.",
        "data": serialize_playlist_summary(updated_playlist, cover_url),
    }
