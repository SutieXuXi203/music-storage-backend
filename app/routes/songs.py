import os
import shutil
import tempfile
from datetime import datetime, timezone
from typing import List, Optional
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import StreamingResponse, FileResponse, Response, RedirectResponse
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

    # Sinh đường dẫn ảnh bìa/cover từ cover_drive_file_id hoặc thumbnail_drive_file_id
    cover_id = song_copy.get("cover_drive_file_id") or song_copy.get("thumbnail_drive_file_id")
    if cover_id:
        song_copy["cover_drive_file_id"] = cover_id
        song_copy["thumbnail_drive_file_id"] = cover_id
        # Sử dụng link trực tiếp chất lượng cao lh3 hỗ trợ CORS và display inline
        song_copy["cover_url"] = f"https://lh3.googleusercontent.com/d/{cover_id}"
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


@router.get(
    "/{song_id}/stream",
    summary="Phát nhạc trực tiếp (Audio Stream Proxy)",
    description="Stream dữ liệu âm thanh trực tiếp từ Google Drive với hỗ trợ CORS và Range header cho Web & Mobile",
)
async def stream_song(song_id: str):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=500, detail="Chưa kết nối cơ sở dữ liệu.")

    try:
        obj_id = ObjectId(song_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Song ID không hợp lệ.")

    song = await db.songs.find_one({"_id": obj_id})
    if not song:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài hát.")

    drive_file_id = song.get("drive_file_id")
    if not drive_file_id:
        raise HTTPException(status_code=404, detail="Bài hát chưa có file trên Google Drive.")

    from app.routes.youtube import DOWNLOADS_DIR
    local_cache = os.path.join(DOWNLOADS_DIR, f"{drive_file_id}.mp3")
    if os.path.exists(local_cache) and os.path.getsize(local_cache) > 0:
        def iter_local():
            with open(local_cache, "rb") as f:
                while chunk := f.read(65536):
                    yield chunk

        return StreamingResponse(
            iter_local(),
            media_type="audio/mpeg",
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(os.path.getsize(local_cache)),
            },
        )

    try:
        import requests
        creds = drive_service._get_service()._http.credentials
        if creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request as GRequest
            creds.refresh(GRequest())

        url = f"https://www.googleapis.com/drive/v3/files/{drive_file_id}?alt=media"
        drive_resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {creds.token}"},
            stream=True,
            timeout=30,
        )

        if drive_resp.status_code != 200:
            raise HTTPException(status_code=drive_resp.status_code, detail="Không thể stream từ Google Drive.")

        def stream_generator():
            try:
                with open(local_cache, "wb") as f_out:
                    for chunk in drive_resp.iter_content(chunk_size=65536):
                        if chunk:
                            f_out.write(chunk)
                            yield chunk
            except Exception:
                pass

        content_length = drive_resp.headers.get("Content-Length")
        headers = {
            "Accept-Ranges": "bytes",
        }
        if content_length:
            headers["Content-Length"] = content_length

        return StreamingResponse(
            stream_generator(),
            media_type="audio/mpeg",
            headers=headers,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi khi phát nhạc: {str(e)}")



@router.get(
    "/{song_id}/cover",
    summary="Lấy ảnh bìa/cover bài hát",
    description="Stream trực tiếp ảnh cover từ Google Drive hoặc local cache, hỗ trợ CORS đầy đủ trên Web",
)
async def get_song_cover(song_id: str):
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

    cover_file_id = song.get("cover_drive_file_id") or song.get("thumbnail_drive_file_id")
    if not cover_file_id:
        raise HTTPException(status_code=404, detail="Bài hát không có ảnh bìa/cover.")

    from app.routes.youtube import DOWNLOADS_DIR
    local_cache = os.path.join(DOWNLOADS_DIR, f"{cover_file_id}_cover.jpg")
    if os.path.exists(local_cache) and os.path.getsize(local_cache) > 0:
        return FileResponse(
            local_cache,
            media_type="image/jpeg",
            headers={
                "Cache-Control": "public, max-age=86400",
                "Access-Control-Allow-Origin": "*",
            },
        )

    # Nếu chưa có trong cache, tải từ Google Drive lh3 endpoint và lưu vào disk
    try:
        import requests
        resp = requests.get(f"https://lh3.googleusercontent.com/d/{cover_file_id}", timeout=15)
        if resp.status_code == 200:
            with open(local_cache, "wb") as f_out:
                f_out.write(resp.content)
            return Response(
                content=resp.content,
                media_type="image/jpeg",
                headers={
                    "Cache-Control": "public, max-age=86400",
                    "Access-Control-Allow-Origin": "*",
                },
            )
    except Exception as e:
        print(f"[Cover] Lỗi tải cache cover: {e}")

    return RedirectResponse(f"https://lh3.googleusercontent.com/d/{cover_file_id}")



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
