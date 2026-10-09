from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field

class SongBase(BaseModel):
    title: str = Field(..., description="Tên bài hát", example="See You Again")
    artist: Optional[str] = Field(default="Unknown Artist", description="Tên ca sĩ / nghệ sĩ", example="Wiz Khalifa ft. Charlie Puth")
    album: Optional[str] = Field(default="Single", description="Tên album", example="Furious 7")
    duration: Optional[int] = Field(default=0, description="Thời lượng tính bằng giây", example=230)
    genre: Optional[str] = Field(default="Pop", description="Thể loại nhạc", example="Pop")
    format: Optional[str] = Field(default="mp3", description="Định dạng âm thanh", example="mp3")
    file_size: Optional[int] = Field(default=0, description="Dung lượng file tính bằng bytes", example=2146796)
    drive_file_id: Optional[str] = Field(default=None, description="Mã định danh file nhạc trên Google Drive", example="1A2B3C4D5E6F...")
    cover_drive_file_id: Optional[str] = Field(default=None, description="Mã định danh ảnh bìa/cover trên Google Drive", example="1QZ4QiGTLxJc...")
    thumbnail_drive_file_id: Optional[str] = Field(default=None, description="Mã định danh ảnh thumbnail (tương thích ngược)")
    user_id: Optional[str] = Field(default=None, description="Mã định danh người dùng tải lên")
    user_username: Optional[str] = Field(default=None, description="Tên đăng nhập người dùng tải lên")

class SongCreate(SongBase):
    pass

class SongUpdate(BaseModel):
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    duration: Optional[int] = None
    genre: Optional[str] = None

class SongResponse(SongBase):
    id: str
    download_url: Optional[str] = Field(default=None, description="Đường dẫn phát trực tiếp hoặc tải về (sinh động từ drive_file_id)")
    stream_url: Optional[str] = Field(default=None, description="Đường dẫn phát nhạc trực tiếp (sinh động từ drive_file_id)")
    web_view_link: Optional[str] = Field(default=None, description="Đường dẫn xem trên giao diện Google Drive (sinh động từ drive_file_id)")
    cover_url: Optional[str] = Field(default=None, description="Đường dẫn ảnh bìa bài hát (sinh động từ thumbnail_drive_file_id)")
    created_at: datetime

    class Config:
        populate_by_name = True


# --- FOLDERS (Thư mục bộ sưu tập liên kết lưu trữ Drive) ---
class FolderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Tên thư mục", example="Nhạc Acoustic")

class FolderUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Tên thư mục mới", example="Nhạc Lofi")

class AddSongToFolderRequest(BaseModel):
    song_id: str = Field(..., description="Mã bài hát cần thêm vào thư mục")
    from_folder_id: Optional[str] = Field(default=None, description="Mã thư mục cũ nếu đây là thao tác di chuyển bài hát")

class FolderResponse(BaseModel):
    id: str
    name: str
    user_id: str
    user_username: Optional[str] = None
    drive_folder_id: Optional[str] = None
    is_default: bool = False
    song_ids: List[str] = Field(default_factory=list)
    song_count: int = 0
    cover_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

class FolderDetailResponse(BaseModel):
    id: str
    name: str
    user_id: str
    user_username: Optional[str] = None
    drive_folder_id: Optional[str] = None
    is_default: bool = False
    song_ids: List[str] = Field(default_factory=list)
    song_count: int = 0
    songs: List[dict] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# --- PLAYLISTS (Danh sách phát nhạc cá nhân độc lập) ---
class PlaylistCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Tên playlist", example="Nhạc EDM")
    description: Optional[str] = Field(default=None, max_length=300, description="Mô tả playlist")

class PlaylistUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100, description="Tên playlist mới")
    description: Optional[str] = Field(default=None, max_length=300, description="Mô tả playlist mới")

class AddSongToPlaylistRequest(BaseModel):
    song_id: str = Field(..., description="Mã bài hát cần thêm vào playlist")

class PlaylistResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    user_id: str
    user_username: Optional[str] = None
    song_ids: List[str] = Field(default_factory=list)
    song_count: int = 0
    cover_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

class PlaylistDetailResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    user_id: str
    user_username: Optional[str] = None
    song_ids: List[str] = Field(default_factory=list)
    song_count: int = 0
    songs: List[dict] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime




