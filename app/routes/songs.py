import os
import shutil
import tempfile
from datetime import datetime, timezone
from typing import List, Optional
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from app.database import get_database
from app.models import SongCreate, SongUpdate
from app.routes.auth import get_current_user
from app.services.drive_service import drive_service

router = APIRouter(prefix="/api/songs", tags=["Quản lý bài hát"])


def serialize_song(song: dict) -> dict:
    """Chuyển đổi MongoDB document thành dict với id dạng chuỗi và sinh các đường link động từ Drive ID"""
    if not song:
        return {}
    song_copy = dict(song)
    if "_id" in song_copy:
        song_copy["id"] = str(song_copy["_id"])
        del song_copy["_id"]

    drive_file_id = song_copy.get("drive_file_id")
    thumb_id = song_copy.get("thumbnail_drive_file_id")

    # Sinh đường dẫn stream và xem file trên Drive từ drive_file_id
    if drive_file_id:
        stream_url = drive_service.get_direct_stream_url(drive_file_id)
        song_copy["download_url"] = stream_url
        song_copy["stream_url"] = stream_url
        song_copy["web_view_link"] = drive_service.get_web_view_link(drive_file_id)
    else:
        song_copy.setdefault("download_url", None)
        song_copy.setdefault("stream_url", None)
        song_copy.setdefault("web_view_link", None)

    # Sinh đường dẫn ảnh bìa từ thumbnail_drive_file_id
    if thumb_id:
        song_copy["cover_url"] = drive_service.get_direct_stream_url(thumb_id)
    elif "cover_url" not in song_copy:
        song_copy["cover_url"] = None

    return song_copy



@router.get(
    "",
    summary="Lấy danh sách bài hát",
    description="Lấy danh sách bài hát có hỗ trợ tìm kiếm theo tiêu đề/nghệ sĩ/album, lọc theo người tải và phân trang",
    response_description="Danh sách bài hát",
)
async def list_songs(
    limit: int = Query(50, ge=1, le=100, description="Số lượng bài hát tối đa trên mỗi trang"),
    skip: int = Query(0, ge=0, description="Bỏ qua N bài hát (phân trang)"),
    search: Optional[str] = Query(None, description="Tìm kiếm theo tiêu đề, ca sĩ hoặc album"),
    user_id: Optional[str] = Query(None, description="Lọc danh sách bài hát theo ID người tải lên"),
):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=500, detail="Chưa kết nối cơ sở dữ liệu MongoDB.")

    query = {}
    if search:
        query["$or"] = [
            {"title": {"$regex": search, "$options": "i"}},
            {"artist": {"$regex": search, "$options": "i"}},
            {"album": {"$regex": search, "$options": "i"}},
        ]
    if user_id:
        query["user_id"] = user_id

    cursor = db.songs.find(query).sort("created_at", -1).skip(skip).limit(limit)
    songs = []
    async for doc in cursor:
        songs.append(serialize_song(doc))

    total = await db.songs.count_documents(query)

    return {
        "status": "success",
        "total": total,
        "count": len(songs),
        "data": songs,
    }


@router.get(
    "/{song_id}",
    summary="Xem chi tiết bài hát",
    description="Lấy thông tin chi tiết một bài hát bằng mã định danh (ID)",
)
async def get_song(song_id: str):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=500, detail="Chưa kết nối cơ sở dữ liệu MongoDB.")

    try:
        obj_id = ObjectId(song_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Song ID không hợp lệ.")

    song = await db.songs.find_one({"_id": obj_id})
    if not song:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài hát.")

    return {
        "status": "success",
        "data": serialize_song(song),
    }


@router.delete(
    "/{song_id}",
    summary="Xoá bài hát",
    description="Xoá bài hát khỏi Google Drive và MongoDB (Chỉ người tải lên bài hát mới có quyền xoá)",
)
async def delete_song(
    song_id: str,
    current_user: dict = Depends(get_current_user),
):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=500, detail="Chưa kết nối cơ sở dữ liệu MongoDB.")

    try:
        obj_id = ObjectId(song_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Song ID không hợp lệ.")

    song = await db.songs.find_one({"_id": obj_id})
    if not song:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài hát.")

    # Kiểm tra quyền: nếu bài hát đã gắn user_id thì chỉ đúng người tải lên mới được xoá
    song_owner_id = song.get("user_id")
    if song_owner_id and str(song_owner_id) != str(current_user["_id"]):
        raise HTTPException(
            status_code=403,
            detail="Bạn không có quyền xoá bài hát của người khác.",
        )

    # 1. Xoá file nhạc và thumbnail trên Google Drive nếu có
    drive_file_id = song.get("drive_file_id")
    deleted_from_drive = False
    if drive_file_id:
        deleted_from_drive = await drive_service.delete_file(drive_file_id)
    thumb_drive_id = song.get("thumbnail_drive_file_id")
    if thumb_drive_id:
        await drive_service.delete_file(thumb_drive_id)

    # 2. Xoá trong MongoDB
    await db.songs.delete_one({"_id": obj_id})

    return {
        "status": "success",
        "message": f"Đã xoá bài hát '{song.get('title')}' thành công.",
        "deleted_from_drive": deleted_from_drive,
    }


@router.post(
    "/upload",
    summary="Tải lên file nhạc trực tiếp",
    description="Tải file âm thanh từ thiết bị lên Google Drive & lưu vào MongoDB (Yêu cầu đăng nhập)",
)
async def upload_song_file(
    file: UploadFile = File(..., description="File âm thanh (mp3, m4a, wav, flac, ...)"),
    title: Optional[str] = Form(None, description="Tên bài hát (mặc định lấy theo tên file)"),
    artist: Optional[str] = Form("Unknown Artist", description="Tên ca sĩ / nghệ sĩ"),
    album: Optional[str] = Form("Single", description="Tên album"),
    genre: Optional[str] = Form("Pop", description="Thể loại nhạc"),
    cover_url: Optional[str] = Form(None, description="Đường dẫn ảnh bìa bài hát"),
    current_user: dict = Depends(get_current_user),
):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=500, detail="Chưa kết nối cơ sở dữ liệu MongoDB.")

    # Lưu file tạm thời để upload
    suffix = os.path.splitext(file.filename)[1] or ".mp3"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        song_title = title or os.path.splitext(file.filename)[0]
        mime_type = file.content_type or "audio/mpeg"

        # 1. Xác định thư mục cha của người dùng trên Drive
        from app.routes.auth import get_or_create_user_drive_folder
        user_parent_id = await get_or_create_user_drive_folder(current_user)

        # 2. Tạo thư mục con mang tên bài hát bên trong thư mục cha của người dùng
        from app.routes.youtube import sanitize_filename
        song_subfolder = sanitize_filename(song_title) or "Unknown"
        subfolder_id = await drive_service.get_or_create_folder(
            folder_name=song_subfolder,
            parent_id=user_parent_id,
            make_public=True,
        )

        # 3. Upload lên Google Drive vào đúng subfolder_id
        drive_res = await drive_service.upload_file(
            local_file_path=tmp_path,
            filename=file.filename,
            mime_type=mime_type,
            folder_id=subfolder_id,
        )

        # 2. Lưu vào MongoDB (Chỉ lưu Metadata & ID, không lưu link Drive cứng)
        file_stat = os.stat(tmp_path)
        song_doc = {
            "title": song_title,
            "artist": artist,
            "album": album,
            "genre": genre,
            "duration": 0,
            "format": suffix.lstrip(".").lower() or "mp3",
            "file_size": file_stat.st_size,
            "drive_file_id": drive_res["file_id"],
            "thumbnail_drive_file_id": None,
            "user_id": str(current_user["_id"]),
            "user_username": current_user.get("username"),
            "created_at": datetime.now(timezone.utc),
        }

        result = await db.songs.insert_one(song_doc)
        song_doc["_id"] = result.inserted_id

        return {
            "status": "success",
            "message": "Đã tải file lên Google Drive và lưu vào cơ sở dữ liệu thành công.",
            "data": serialize_song(song_doc),
        }
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
