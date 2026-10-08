import os
import re
import asyncio
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
import yt_dlp

from app.config import settings
from app.database import get_database
from app.routes.auth import get_current_user
from app.services.drive_service import drive_service

router = APIRouter(prefix="/api", tags=["Tải nhạc YouTube"])

DOWNLOADS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "downloads"))
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


class DownloadFormat(str, Enum):
    MP3 = "mp3"
    MP4 = "mp4"


class DownloadRequest(BaseModel):
    url: str = Field(
        ...,
        description="Đường dẫn YouTube cần tải (URL)",
        example="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    )
    format: DownloadFormat = Field(
        default=DownloadFormat.MP3,
        description="Định dạng muốn tải: 'mp3' (âm thanh) hoặc 'mp4' (video)",
        example=DownloadFormat.MP3,
    )
    return_file: bool = Field(
        default=True,
        description="True: Trả về trực tiếp file tải về thiết bị; False: Trả về thông tin JSON và link tải",
    )
    save_to_drive: bool = Field(
        default=False,
        description="True: Tự động tải file lên Google Drive và lưu vào MongoDB",
    )


def sanitize_filename(name: str) -> str:
    """Loại bỏ các ký tự không hợp lệ trên Windows file system"""
    sanitized = re.sub(r'[\\/*?:"<>|]', "", name)
    return sanitized.strip()[:100]


def process_youtube_download(url: str, format_type: str) -> dict:
    """Tải và convert nhạc mp3 hoặc video mp4 từ YouTube đồng bộ"""
    base_ydl_opts = {
        "outtmpl": os.path.join(DOWNLOADS_DIR, "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "js_runtimes": {"deno": {}, "node": {}},
        "remote_components": {"ejs:github": {}},
    }


    cookie_file = os.path.join(DOWNLOADS_DIR, "cookies.txt")
    raw_cookies = os.getenv("YOUTUBE_COOKIES")
    has_cookies = False
    if raw_cookies:
        try:
            cleaned_cookies = raw_cookies.replace("\ufeff", "").strip()
            if not cleaned_cookies.startswith("# Netscape"):
                cleaned_cookies = "# Netscape HTTP Cookie File\n" + cleaned_cookies
            with open(cookie_file, "w", encoding="utf-8", newline="\n") as f:
                f.write(cleaned_cookies + "\n")
            base_ydl_opts["cookiefile"] = cookie_file
            has_cookies = True
        except Exception as e:
            print(f"[YouTube] Lỗi ghi cookie: {e}")
    elif os.path.exists(cookie_file):
        try:
            with open(cookie_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read().replace("\ufeff", "").strip()
            if not content.startswith("# Netscape"):
                content = "# Netscape HTTP Cookie File\n" + content
            with open(cookie_file, "w", encoding="utf-8", newline="\n") as f:
                f.write(content + "\n")
        except Exception:
            pass
        base_ydl_opts["cookiefile"] = cookie_file
        has_cookies = True
    elif os.path.exists(os.path.join(DOWNLOADS_DIR, "www.youtube.com_cookies.txt")):
        www_cookie = os.path.join(DOWNLOADS_DIR, "www.youtube.com_cookies.txt")
        try:
            with open(www_cookie, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read().replace("\ufeff", "").strip()
            if not content.startswith("# Netscape"):
                content = "# Netscape HTTP Cookie File\n" + content
            with open(www_cookie, "w", encoding="utf-8", newline="\n") as f:
                f.write(content + "\n")
        except Exception:
            pass
        base_ydl_opts["cookiefile"] = www_cookie
        has_cookies = True

    if format_type.lower() == "mp3":
        ydl_opts = {
            **base_ydl_opts,
            "format": "bestaudio/best",
            "writethumbnail": True,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                },
                {
                    "key": "FFmpegThumbnailsConvertor",
                    "format": "jpg",
                },
                {
                    "key": "EmbedThumbnail",
                },
                {
                    "key": "FFmpegMetadata",
                },
            ],
        }
        target_ext = "mp3"
        media_type = "audio/mpeg"
    else:
        ydl_opts = {
            **base_ydl_opts,
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "merge_output_format": "mp4",
        }
        target_ext = "mp4"
        media_type = "video/mp4"

    # Xây dựng các chiến lược tải linh hoạt:
    strategies = []

    if has_cookies:
        # Chiến lược 1: Ưu tiên dùng phiên trình duyệt thật (cookies + web client + JS challenge solver)
        strategies.append(dict(ydl_opts))
        # Chiến lược 2: Web creator / mweb với cookies
        strategies.append({
            **ydl_opts,
            "extractor_args": {
                "youtube": {
                    "player_client": ["web_creator", "mweb"],
                }
            },
        })

    # Chiến lược dự phòng (không dùng cookies): Client di động cho đường truyền trực tiếp
    no_cookie_opts = {k: v for k, v in ydl_opts.items() if k != "cookiefile"}
    strategies.append({
        **no_cookie_opts,
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "ios", "mweb"],
            }
        },
    })
    strategies.append({
        **no_cookie_opts,
        "extractor_args": {
            "youtube": {
                "player_client": ["ios", "android"],
            }
        },
    })

    last_error = None
    info = None

    for idx, strat in enumerate(strategies):
        try:
            with yt_dlp.YoutubeDL(strat) as ydl:
                info = ydl.extract_info(url, download=True)
                if info:
                    break
        except Exception as e:
            last_error = e
            err_str = str(e)
            print(f"[YouTube] Chiến lược {idx + 1} không thành công: {err_str[:120]}")
            # Nếu không phải lỗi liên quan bot hay format, dừng sớm
            if "bot" not in err_str.lower() and "sign in" not in err_str.lower() and "cookie" not in err_str.lower():
                break

    if not info:
        raise HTTPException(
            status_code=400,
            detail=f"Lỗi khi xử lý link YouTube: {str(last_error)}",
        )

    try:
        video_id = info.get("id")
        title = info.get("title", "downloaded_track")
        artist = info.get("uploader", "Unknown Artist")
        duration = info.get("duration", 0)
        thumbnail = info.get("thumbnail")

        # Đường dẫn file đã xử lý
        file_path = os.path.join(DOWNLOADS_DIR, f"{video_id}.{target_ext}")
        if not os.path.exists(file_path):
            # Fallback tìm kiếm file trùng video_id và target_ext
            for fname in os.listdir(DOWNLOADS_DIR):
                if fname.startswith(video_id) and fname.endswith(f".{target_ext}"):
                    file_path = os.path.join(DOWNLOADS_DIR, fname)
                    break

        if not os.path.exists(file_path):
            raise RuntimeError(f"Không tìm thấy file kết quả sau khi tải: {file_path}")

        safe_title = sanitize_filename(title) or "music"
        download_filename = f"{safe_title}.{target_ext}"
        file_size = os.path.getsize(file_path)

        return {
            "id": video_id,
            "title": title,
            "artist": artist,
            "duration": duration,
            "thumbnail": thumbnail,
            "format": target_ext,
            "file_path": file_path,
            "download_filename": download_filename,
            "file_size": file_size,
            "media_type": media_type,
        }
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Lỗi khi xử lý link YouTube: {str(e)}",
        )


def download_thumbnail_file(thumbnail_url: Optional[str], video_id: str, title: str) -> Optional[dict]:
    """Tải file ảnh thumbnail từ YouTube về máy để chuẩn bị upload lên Drive"""
    if not thumbnail_url:
        return None
    try:
        ext = "jpg"
        if ".webp" in thumbnail_url.lower():
            ext = "webp"
        elif ".png" in thumbnail_url.lower():
            ext = "png"

        thumb_filename = f"{video_id}_thumb.{ext}"
        thumb_path = os.path.join(DOWNLOADS_DIR, thumb_filename)

        import urllib.request
        req = urllib.request.Request(
            thumbnail_url,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp, open(thumb_path, "wb") as out_file:
            out_file.write(resp.read())

        if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
            safe_title = sanitize_filename(title) or "cover"
            mime_type = "image/jpeg" if ext == "jpg" else f"image/{ext}"
            return {
                "file_path": thumb_path,
                "filename": f"{safe_title}_cover.{ext}",
                "mime_type": mime_type,
            }
    except Exception as e:
        print(f"[YouTube Route] Lỗi tải thumbnail: {e}")
    return None


async def handle_download_request(
    url: str,
    format_type: str,
    return_file: bool,
    request: Request,
    save_to_drive: bool = False,
    current_user: Optional[dict] = None,
):
    """Xử lý tải bất đồng bộ (chạy yt-dlp trong worker thread)"""
    # Chạy process_youtube_download trong thread riêng để không block FastAPI event loop
    result = await asyncio.to_thread(process_youtube_download, url, format_type)

    drive_data = None
    song_id = None
    if save_to_drive:
        try:
            # 1. Xác định thư mục cha của người dùng trên Google Drive
            user_parent_id = settings.GOOGLE_DRIVE_FOLDER_ID
            if current_user:
                from app.routes.auth import get_or_create_user_drive_folder
                user_parent_id = await get_or_create_user_drive_folder(current_user)

            # 2. Tạo tên thư mục con từ title YouTube (đã sanitize)
            song_subfolder = sanitize_filename(result["title"]) or "Unknown"

            # 3. Tạo thư mục con cho bài hát NẰM BÊN TRONG thư mục cha của người dùng
            subfolder_id = await drive_service.get_or_create_folder(
                folder_name=song_subfolder,
                parent_id=user_parent_id,
                make_public=False,
            )

            # Tải ảnh thumbnail về máy trong thread riêng để upload cùng bài hát lên Drive
            thumb_info = await asyncio.to_thread(
                download_thumbnail_file, result.get("thumbnail"), result["id"], result["title"]
            )

            # Upload cả file nhạc và ảnh thumbnail vào đúng một thư mục con subfolder_id
            tasks = [
                drive_service.upload_file(
                    local_file_path=result["file_path"],
                    filename=result["download_filename"],
                    mime_type=result["media_type"],
                    folder_id=subfolder_id,
                )
            ]
            if thumb_info:
                tasks.append(
                    drive_service.upload_file(
                        local_file_path=thumb_info["file_path"],
                        filename=thumb_info["filename"],
                        mime_type=thumb_info["mime_type"],
                        folder_id=subfolder_id,
                    )
                )

            upload_results = await asyncio.gather(*tasks, return_exceptions=True)
            drive_res = upload_results[0] if not isinstance(upload_results[0], Exception) else {}
            drive_thumb_res = (
                upload_results[1]
                if len(upload_results) > 1 and not isinstance(upload_results[1], Exception)
                else None
            )
            drive_data = drive_res
            drive_data["subfolder_name"] = song_subfolder
            drive_data["subfolder_id"] = subfolder_id
            if drive_thumb_res:
                cover_id = drive_thumb_res.get("file_id")
                drive_data["cover_file_id"] = cover_id
                drive_data["thumbnail_file_id"] = cover_id
                drive_data["cover_url"] = f"https://lh3.googleusercontent.com/d/{cover_id}"
                drive_data["thumbnail_web_view_link"] = drive_thumb_res.get("web_view_link")
                drive_data["thumbnail_direct_url"] = drive_thumb_res.get("direct_stream_url")

            # Lưu vào MongoDB (Chỉ lưu Metadata & ID, không lưu các link Drive cứng)
            db = get_database()
            if db is not None:
                cover_id = drive_thumb_res.get("file_id") if drive_thumb_res else None
                song_doc = {
                    "title": result["title"],
                    "artist": result["artist"],
                    "album": "YouTube",
                    "duration": result["duration"],
                    "genre": "YouTube",
                    "drive_file_id": drive_res.get("file_id"),
                    "cover_drive_file_id": cover_id,
                    "thumbnail_drive_file_id": cover_id,
                    "format": result["format"],
                    "file_size": result["file_size"],
                    "user_id": str(current_user["_id"]) if current_user else None,
                    "user_username": current_user.get("username") if current_user else None,
                    "created_at": datetime.now(timezone.utc),
                }
                res_db = await db.songs.insert_one(song_doc)
                song_id = str(res_db.inserted_id)
                if current_user:
                    await db.folders.update_one(
                        {"user_id": str(current_user["_id"]), "is_default": True},
                        {
                            "$addToSet": {"song_ids": song_id},
                            "$set": {"updated_at": datetime.now(timezone.utc)},
                        },
                    )
        except Exception as drive_err:
            print(f"[YouTube Route] Lỗi upload Drive: {drive_err}")
            drive_data = {"error": str(drive_err)}

    if return_file:
        return FileResponse(
            path=result["file_path"],
            filename=result["download_filename"],
            media_type=result["media_type"],
            headers={"Content-Disposition": f'attachment; filename="{result["download_filename"]}"'},
        )

    base_url = str(request.base_url).rstrip("/")
    file_serve_url = f"{base_url}/api/downloads/{os.path.basename(result['file_path'])}"

    resp_data = {
        "status": "success",
        "message": f"Tải thành công định dạng {result['format'].upper()}",
        "id": result["id"],
        "title": result["title"],
        "artist": result["artist"],
        "duration": result["duration"],
        "thumbnail": result["thumbnail"],
        "format": result["format"],
        "file_size": result["file_size"],
        "download_filename": result["download_filename"],
        "download_url": file_serve_url,
    }

    if save_to_drive and drive_data:
        resp_data["saved_to_drive"] = True
        resp_data["song_id"] = song_id
        resp_data["drive_file_id"] = drive_data.get("file_id")
        resp_data["direct_stream_url"] = drive_data.get("direct_stream_url")
        resp_data["drive_web_view_link"] = drive_data.get("web_view_link")
        resp_data["drive_subfolder_name"] = drive_data.get("subfolder_name")
        # Thông tin ảnh thumbnail đã upload lên Google Drive
        if drive_data.get("thumbnail_file_id"):
            resp_data["thumbnail_file_id"] = drive_data.get("thumbnail_file_id")
            resp_data["thumbnail_web_view_link"] = drive_data.get("thumbnail_web_view_link")
            resp_data["thumbnail_direct_url"] = drive_data.get("thumbnail_direct_url")

    return resp_data



# Endpoint chính theo đúng yêu cầu: dowload-music-from-yt
@router.post(
    "/dowload-music-from-yt",
    summary="Tải nhạc hoặc video từ YouTube (POST)",
    description="Gửi đường dẫn YouTube và chọn định dạng ('mp3' hoặc 'mp4'). Tùy chọn lưu lên Google Drive và MongoDB (Yêu cầu đăng nhập).",
)
async def download_music_from_yt_post(
    req: DownloadRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    return await handle_download_request(
        req.url, req.format.value, req.return_file, request, save_to_drive=req.save_to_drive, current_user=current_user
    )


# Endpoint phụ GET để người dùng có thể test nhanh trực tiếp trên trình duyệt
@router.get(
    "/dowload-music-from-yt",
    summary="Tải nhanh từ YouTube qua trình duyệt (GET)",
    description="Tải nhanh trên trình duyệt bằng tham số: ?url=...&format=mp3 (Yêu cầu đăng nhập).",
)
async def download_music_from_yt_get(
    request: Request,
    url: str = Query(..., description="Đường dẫn YouTube", examples=["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]),
    format: DownloadFormat = Query(DownloadFormat.MP3, description="Định dạng: mp3 hoặc mp4"),
    return_file: bool = Query(True, description="True để tải file về máy, False để lấy JSON thông tin"),
    save_to_drive: bool = Query(False, description="True: Lưu lên Google Drive và MongoDB"),
    current_user: dict = Depends(get_current_user),
):
    return await handle_download_request(
        url, format.value, return_file, request, save_to_drive=save_to_drive, current_user=current_user
    )


# Alias cho đúng chính tả tiếng Anh (phòng khi gõ 'download')
@router.post("/download-music-from-yt", include_in_schema=False)
async def download_music_alias_post(
    req: DownloadRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    return await handle_download_request(
        req.url, req.format.value, req.return_file, request, save_to_drive=req.save_to_drive, current_user=current_user
    )


@router.get("/download-music-from-yt", include_in_schema=False)
async def download_music_alias_get(
    request: Request,
    url: str = Query(...),
    format: DownloadFormat = Query(DownloadFormat.MP3),
    return_file: bool = Query(True),
    save_to_drive: bool = Query(False),
    current_user: dict = Depends(get_current_user),
):
    return await handle_download_request(
        url, format.value, return_file, request, save_to_drive=save_to_drive, current_user=current_user
    )


# Endpoint tải file đã lưu trong server
@router.get(
    "/downloads/{filename}",
    summary="Tải lại file đã lưu trong máy chủ",
    description="Tải lại file nhạc/video đã lưu trong thư mục downloads tạm của máy chủ.",
)
async def get_downloaded_file(filename: str):
    file_path = os.path.join(DOWNLOADS_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File không tồn tại trên hệ thống.")

    media_type = "audio/mpeg" if filename.endswith(".mp3") else "video/mp4"
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=media_type,
    )
