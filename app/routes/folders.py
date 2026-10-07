from datetime import datetime, timezone
from typing import List, Optional
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.database import get_database
from app.models import (
    AddSongToFolderRequest,
    FolderCreate,
    FolderUpdate,
)
from app.routes.auth import get_current_user
from app.routes.songs import serialize_song

router = APIRouter(prefix="/api/folders", tags=["Quản lý thư mục nhạc"])


async def _get_folder_cover(db, song_ids: List[str]) -> Optional[str]:
    """Lấy cover_url của bài hát đầu tiên trong thư mục nếu có"""
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


def serialize_folder_summary(doc: dict, cover_url: Optional[str] = None) -> dict:
    song_ids = doc.get("song_ids", [])
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name", ""),
        "user_id": doc.get("user_id", ""),
        "song_ids": song_ids,
        "song_count": len(song_ids),
        "cover_url": cover_url,
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at") or doc.get("created_at"),
    }


@router.get(
    "",
    summary="Lấy danh sách thư mục của người dùng",
    description="Trả về toàn bộ các thư mục bài hát được tạo bởi người dùng hiện tại",
)
async def list_folders(current_user: dict = Depends(get_current_user)):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=500, detail="Chưa kết nối cơ sở dữ liệu MongoDB.")

    user_id_str = str(current_user["_id"])
    cursor = db.folders.find({"user_id": user_id_str}).sort("created_at", -1)
    folders = []

    async for doc in cursor:
        song_ids = doc.get("song_ids", [])
        cover_url = await _get_folder_cover(db, song_ids)
        folders.append(serialize_folder_summary(doc, cover_url))

    return {
        "status": "success",
        "total": len(folders),
        "data": folders,
    }


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Tạo thư mục mới",
    description="Tạo một thư mục mới để phân loại và quản lý bài hát",
)
async def create_folder(
    req: FolderCreate,
    current_user: dict = Depends(get_current_user),
):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=500, detail="Chưa kết nối cơ sở dữ liệu MongoDB.")

    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Tên thư mục không được để trống.")

    user_id_str = str(current_user["_id"])
    now = datetime.now(timezone.utc)

    folder_doc = {
        "name": name,
        "user_id": user_id_str,
        "user_username": current_user.get("username"),
        "song_ids": [],
        "created_at": now,
        "updated_at": now,
    }

    result = await db.folders.insert_one(folder_doc)
    folder_doc["_id"] = result.inserted_id

    return {
        "status": "success",
        "message": f"Đã tạo thư mục '{name}' thành công.",
        "data": serialize_folder_summary(folder_doc),
    }


@router.get(
    "/{folder_id}",
    summary="Xem chi tiết thư mục",
    description="Lấy thông tin thư mục và danh sách đầy đủ các bài hát trong thư mục đó",
)
async def get_folder(
    folder_id: str,
    current_user: dict = Depends(get_current_user),
):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=500, detail="Chưa kết nối cơ sở dữ liệu MongoDB.")

    if not ObjectId.is_valid(folder_id):
        raise HTTPException(status_code=400, detail="Mã thư mục không hợp lệ.")

    folder = await db.folders.find_one({"_id": ObjectId(folder_id)})
    if not folder:
        raise HTTPException(status_code=404, detail="Không tìm thấy thư mục.")

    if str(folder.get("user_id")) != str(current_user["_id"]):
        raise HTTPException(status_code=403, detail="Bạn không có quyền truy cập thư mục này.")

    song_ids = folder.get("song_ids", [])
    valid_obj_ids = [ObjectId(sid) for sid in song_ids if ObjectId.is_valid(sid)]

    # Lấy danh sách các bài hát trong MongoDB
    songs_map = {}
    if valid_obj_ids:
        cursor = db.songs.find({"_id": {"$in": valid_obj_ids}})
        async for s_doc in cursor:
            s_dict = serialize_song(s_doc)
            songs_map[s_dict["id"]] = s_dict

    # Giữ nguyên thứ tự theo song_ids
    ordered_songs = []
    for sid in song_ids:
        if sid in songs_map:
            ordered_songs.append(songs_map[sid])

    cover_url = ordered_songs[0].get("cover_url") if ordered_songs else None

    summary = serialize_folder_summary(folder, cover_url)
    summary["songs"] = ordered_songs

    return {
        "status": "success",
        "data": summary,
    }


@router.put(
    "/{folder_id}",
    summary="Đổi tên thư mục",
    description="Cập nhật tên mới cho thư mục",
)
async def update_folder(
    folder_id: str,
    req: FolderUpdate,
    current_user: dict = Depends(get_current_user),
):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=500, detail="Chưa kết nối cơ sở dữ liệu MongoDB.")

    if not ObjectId.is_valid(folder_id):
        raise HTTPException(status_code=400, detail="Mã thư mục không hợp lệ.")

    folder = await db.folders.find_one({"_id": ObjectId(folder_id)})
    if not folder:
        raise HTTPException(status_code=404, detail="Không tìm thấy thư mục.")

    if str(folder.get("user_id")) != str(current_user["_id"]):
        raise HTTPException(status_code=403, detail="Bạn không có quyền chỉnh sửa thư mục này.")

    new_name = req.name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="Tên thư mục không được để trống.")

    now = datetime.now(timezone.utc)
    await db.folders.update_one(
        {"_id": ObjectId(folder_id)},
        {"$set": {"name": new_name, "updated_at": now}},
    )

    folder["name"] = new_name
    folder["updated_at"] = now
    cover_url = await _get_folder_cover(db, folder.get("song_ids", []))

    return {
        "status": "success",
        "message": f"Đã đổi tên thư mục thành '{new_name}'.",
        "data": serialize_folder_summary(folder, cover_url),
    }


@router.delete(
    "/{folder_id}",
    summary="Xóa thư mục",
    description="Xóa thư mục khỏi hệ thống (các bài hát bên trong vẫn được giữ an toàn trong kho nhạc)",
)
async def delete_folder(
    folder_id: str,
    current_user: dict = Depends(get_current_user),
):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=500, detail="Chưa kết nối cơ sở dữ liệu MongoDB.")

    if not ObjectId.is_valid(folder_id):
        raise HTTPException(status_code=400, detail="Mã thư mục không hợp lệ.")

    folder = await db.folders.find_one({"_id": ObjectId(folder_id)})
    if not folder:
        raise HTTPException(status_code=404, detail="Không tìm thấy thư mục.")

    if str(folder.get("user_id")) != str(current_user["_id"]):
        raise HTTPException(status_code=403, detail="Bạn không có quyền xóa thư mục này.")

    await db.folders.delete_one({"_id": ObjectId(folder_id)})

    return {
        "status": "success",
        "message": f"Đã xóa thư mục '{folder.get('name')}' thành công.",
    }


@router.post(
    "/{folder_id}/songs",
    summary="Thêm hoặc chuyển bài hát vào thư mục",
    description="Thêm bài hát vào thư mục đích. Nếu truyền from_folder_id, bài hát sẽ tự động được gỡ khỏi thư mục cũ.",
)
async def add_or_move_song_to_folder(
    folder_id: str,
    req: AddSongToFolderRequest,
    current_user: dict = Depends(get_current_user),
):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=500, detail="Chưa kết nối cơ sở dữ liệu MongoDB.")

    if not ObjectId.is_valid(folder_id):
        raise HTTPException(status_code=400, detail="Mã thư mục đích không hợp lệ.")

    folder = await db.folders.find_one({"_id": ObjectId(folder_id)})
    if not folder:
        raise HTTPException(status_code=404, detail="Không tìm thấy thư mục đích.")

    if str(folder.get("user_id")) != str(current_user["_id"]):
        raise HTTPException(status_code=403, detail="Bạn không có quyền thao tác trên thư mục này.")

    song_id = req.song_id.strip()
    if not ObjectId.is_valid(song_id):
        raise HTTPException(status_code=400, detail="Mã bài hát không hợp lệ.")

    song = await db.songs.find_one({"_id": ObjectId(song_id)})
    if not song:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài hát.")

    now = datetime.now(timezone.utc)

    # 1. Nếu có from_folder_id, gỡ bài hát khỏi thư mục cũ
    if req.from_folder_id and req.from_folder_id != folder_id:
        if ObjectId.is_valid(req.from_folder_id):
            await db.folders.update_one(
                {"_id": ObjectId(req.from_folder_id), "user_id": str(current_user["_id"])},
                {
                    "$pull": {"song_ids": song_id},
                    "$set": {"updated_at": now},
                },
            )

    # 2. Thêm vào thư mục đích (tránh trùng lặp)
    await db.folders.update_one(
        {"_id": ObjectId(folder_id)},
        {
            "$addToSet": {"song_ids": song_id},
            "$set": {"updated_at": now},
        },
    )

    updated_folder = await db.folders.find_one({"_id": ObjectId(folder_id)})
    cover_url = await _get_folder_cover(db, updated_folder.get("song_ids", []))

    return {
        "status": "success",
        "message": f"Đã chuyển bài hát '{song.get('title')}' vào thư mục '{folder.get('name')}'.",
        "data": serialize_folder_summary(updated_folder, cover_url),
    }


@router.delete(
    "/{folder_id}/songs/{song_id}",
    summary="Loại bỏ bài hát khỏi thư mục",
    description="Gỡ bài hát ra khỏi thư mục được chỉ định (bài hát vẫn còn trong kho nhạc chính)",
)
async def remove_song_from_folder(
    folder_id: str,
    song_id: str,
    current_user: dict = Depends(get_current_user),
):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=500, detail="Chưa kết nối cơ sở dữ liệu MongoDB.")

    if not ObjectId.is_valid(folder_id):
        raise HTTPException(status_code=400, detail="Mã thư mục không hợp lệ.")

    folder = await db.folders.find_one({"_id": ObjectId(folder_id)})
    if not folder:
        raise HTTPException(status_code=404, detail="Không tìm thấy thư mục.")

    if str(folder.get("user_id")) != str(current_user["_id"]):
        raise HTTPException(status_code=403, detail="Bạn không có quyền thao tác trên thư mục này.")

    now = datetime.now(timezone.utc)
    await db.folders.update_one(
        {"_id": ObjectId(folder_id)},
        {
            "$pull": {"song_ids": song_id},
            "$set": {"updated_at": now},
        },
    )

    updated_folder = await db.folders.find_one({"_id": ObjectId(folder_id)})
    cover_url = await _get_folder_cover(db, updated_folder.get("song_ids", []))

    return {
        "status": "success",
        "message": f"Đã loại bỏ bài hát khỏi thư mục '{folder.get('name')}'.",
        "data": serialize_folder_summary(updated_folder, cover_url),
    }
