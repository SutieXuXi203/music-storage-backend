from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class SongBase(BaseModel):
    title: str = Field(..., description="Tên bài hát", example="See You Again")
    artist: Optional[str] = Field(default="Unknown Artist", description="Tên ca sĩ / nghệ sĩ", example="Wiz Khalifa ft. Charlie Puth")
    album: Optional[str] = Field(default="Single", description="Tên album", example="Furious 7")
    duration: Optional[int] = Field(default=0, description="Thời lượng tính bằng giây", example=230)
    genre: Optional[str] = Field(default="Pop", description="Thể loại nhạc", example="Pop")
    drive_file_id: Optional[str] = Field(default=None, description="Mã định danh file trên Google Drive", example="1A2B3C4D5E6F...")
    download_url: Optional[str] = Field(default=None, description="Đường dẫn phát trực tiếp hoặc tải về")
    cover_url: Optional[str] = Field(default=None, description="Đường dẫn ảnh bìa bài hát")
    thumbnail_drive_file_id: Optional[str] = Field(default=None, description="Mã định danh ảnh thumbnail trên Google Drive")
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
    drive_file_id: Optional[str] = None
    download_url: Optional[str] = None
    cover_url: Optional[str] = None

class SongResponse(SongBase):
    id: str
    created_at: datetime

    class Config:
        populate_by_name = True
