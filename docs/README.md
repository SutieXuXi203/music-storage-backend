# 🎵 Music Storage Backend API

Hệ thống Backend API chuyên biệt cho việc lưu trữ, quản lý và phát trực tuyến (streaming) nhạc đa nền tảng (Flutter, React, Vue, Web/Mobile). Hệ thống kết hợp cơ sở dữ liệu **MongoDB** (lưu trữ metadata) và **Google Drive API** (lưu trữ file âm thanh và hình ảnh), hỗ trợ tải nhạc trực tiếp từ YouTube với chất lượng âm thanh cao.

---

## 📑 Mục lục
1. [Tính năng nổi bật](#-tính-năng-nổi-bật)
2. [Kiến trúc hệ thống](#-kiến-trúc-hệ-thống)
3. [Cấu trúc thư mục Google Drive](#-cấu-trúc-thư-mục-google-drive)
4. [Công nghệ sử dụng](#-công-nghệ-sử-dụng)
5. [Yêu cầu hệ thống](#-yêu-cầu-hệ-thống)
6. [Cài đặt & Khởi chạy](#-cài-đặt--khởi-chạy)
7. [Cấu hình biến môi trường (.env)](#-cấu-hình-biến-môi-trường-env)
8. [Tài liệu API (Endpoints)](#-tài-liệu-api-endpoints)
9. [Bảo mật & Lưu ý quan trọng](#-bảo-mật--lưu-ý-quan-trọng)

---

## 🌟 Tính năng nổi bật

- 🔐 **Xác thực người dùng (JWT Authentication)**:
  - Đăng ký, đăng nhập với mã hóa mật khẩu an toàn (`bcrypt`).
  - Hỗ trợ Access Token và Refresh Token thời hạn dài.
  - Tự động tạo thư mục riêng biệt cho từng người dùng trên Google Drive dựa trên Họ tên (`full_name`) ngay khi đăng ký.
- 📥 **Tải nhạc từ YouTube thông minh**:
  - Trích xuất âm thanh chất lượng cao chuẩn MP3 (192kbps) qua `yt-dlp` và `FFmpeg`.
  - Tự động tải về ảnh bìa (thumbnail) bài hát.
  - Tối ưu hóa lưu trữ: Không lưu video MP4 nặng, chỉ lưu file âm thanh nhẹ và ảnh thumbnail.
- ☁️ **Lưu trữ đám mây Google Drive**:
  - Tự động tổ chức file theo cấu trúc 2 cấp thư mục: `[User Folder] -> [Song Folder] -> (.mp3 + _thumb.jpg)`.
  - Tự động cấp quyền công khai (Public Read) và sinh đường dẫn phát trực tiếp (Direct Stream URL) chuẩn cho ứng dụng nghe nhạc.
- 🎼 **Quản lý kho bài hát (Song Management)**:
  - Hỗ trợ tìm kiếm bài hát theo tên, ca sĩ, album bằng Regular Expressions (không phân biệt hoa/thường).
  - Phân trang (Pagination) tối ưu hóa hiệu năng.
  - Upload file nhạc thủ công từ thiết bị lên Google Drive.
  - Xóa bài hát: Tự động dọn dẹp cả dữ liệu trong MongoDB lẫn các file trên Google Drive (có kiểm tra quyền sở hữu).

---

## 🏗 Kiến trúc hệ thống

```text
┌─────────────────┐      ┌─────────────────────────────┐      ┌──────────────────┐
│                 │      │      FastAPI Backend        │      │     MongoDB      │
│  Flutter Client │ ───> │  - JWT Auth (Bcrypt)        │ <──> │  - users         │
│  Web / Mobile   │ <─── │  - yt-dlp Audio Downloader  │      │  - songs         │
│                 │      │  - Drive Service Manager    │      └──────────────────┘
└─────────────────┘      └──────────────┬──────────────┘
                                        │
                                        ▼
                             ┌───────────────────┐
                             │   Google Drive    │
                             │ (Audio & Images)  │
                             └───────────────────┘
```

---

## 📂 Cấu trúc thư mục Google Drive

Khi người dùng đăng ký tài khoản và tải nhạc, hệ thống sẽ tự động cấu trúc trên Google Drive như sau:

```text
📁 Music Storage (Thư mục gốc của hệ thống trên Drive)
 └── 📁 Nguyễn Văn A (Thư mục người dùng - đặt theo full_name)
      ├── 📁 See You Again (Thư mục bài hát)
      │    ├── 🎵 See You Again.mp3 (File âm thanh MP3 192k)
      │    └── 🖼️ See You Again_thumb.jpg (Ảnh bìa bài hát)
      └── 📁 Attention
           ├── 🎵 Attention.mp3
           └── 🖼️ Attention_thumb.jpg
```

---

## 🛠 Công nghệ sử dụng

- **Ngôn ngữ**: Python 3.10+ (Đã kiểm thử trên Python 3.13)
- **Framework Web**: [FastAPI](https://fastapi.tiangolo.com/) (Async, hiệu năng cao)
- **ASGI Server**: [Uvicorn](https://www.uvicorn.org/)
- **Cơ sở dữ liệu**: [MongoDB](https://www.mongodb.com/) với Driver bất đồng bộ [Motor](https://motor.readthedocs.io/)
- **Xác thực & Mã hóa**: `bcrypt`, `python-jose` (JWT)
- **Tải & Xử lý đa phương tiện**: `yt-dlp`, `ffmpeg`
- **Cloud Storage SDK**: `google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2`

---

## 📋 Yêu cầu hệ thống

1. **Python**: Phiên bản >= 3.10.
2. **MongoDB**: Đang chạy cục bộ (`mongodb://localhost:27017`) hoặc MongoDB Atlas.
3. **FFmpeg**: Đã được cài đặt và thêm vào biến môi trường `PATH` của hệ thống (bắt buộc cho việc trích xuất audio của `yt-dlp`).
4. **Google Cloud OAuth 2.0 Credentials**: Tệp `client_secrets.json` tải về từ Google Cloud Console (bật Google Drive API).

---

## 🚀 Cài đặt & Khởi chạy

### 1. Di chuyển vào thư mục backend
```powershell
cd c:\Users\manhd\Desktop\music-app\backend
```

### 2. Tạo và kích hoạt môi trường ảo (Virtualenv)
```powershell
# Windows PowerShell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 3. Cài đặt các thư viện phụ thuộc
```powershell
pip install -r requirements.txt
```

### 4. Thiết lập file cấu hình môi trường
Tạo bản sao từ file mẫu `.env.example`:
```powershell
copy .env.example .env
```
Mở file `.env` và điền các thông số thích hợp (xem mục tiếp theo).

### 5. Cấp quyền Google Drive (Lần đầu tiên)
Đặt file `client_secrets.json` (tải từ Google Cloud Console) vào thư mục `backend/`.  
Sau đó chạy script để xác thực OAuth và sinh file `token.json`:
```powershell
python -c "from app.services.auth_drive import authenticate_google_drive; authenticate_google_drive()"
```
Trình duyệt sẽ tự động mở lên, bạn chỉ cần đăng nhập tài khoản Google và bấm **Cho phép (Allow)**.

### 6. Khởi chạy máy chủ API
```powershell
python run.py
```
Máy chủ sẽ lắng nghe tại:
- **API URL**: `http://localhost:8000`
- **Tài liệu Swagger UI tương tác**: `http://localhost:8000/docs`
- **Tài liệu Redoc**: `http://localhost:8000/redoc`

---

## ⚙️ Cấu hình biến môi trường (.env)

```env
# Cấu hình Server
HOST=0.0.0.0
PORT=8000
DEBUG=True

# Cơ sở dữ liệu MongoDB
MONGODB_URL=mongodb://localhost:27017
DATABASE_NAME=music_app_db

# Google Drive API
# (ID thư mục gốc trên Drive nếu muốn chỉ định, để trống sẽ tự tìm/tạo 'Music Storage')
GOOGLE_DRIVE_FOLDER_ID=

# Bảo mật JWT
# Sinh chuỗi bí mật bằng lệnh: python -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET_KEY=your_very_secret_jwt_key_here
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=30
```

---

## 📡 Tài liệu API (Endpoints)

### 1. Xác thực tài khoản (`/api/auth`)
| Phương thức | Đường dẫn | Mô tả | Yêu cầu xác thực |
|---|---|---|:---:|
| `POST` | `/api/auth/register` | Đăng ký tài khoản (tự động tạo folder riêng trên Drive) | ❌ |
| `POST` | `/api/auth/login` | Đăng nhập lấy Bearer token (`access_token`, `refresh_token`) | ❌ |
| `POST` | `/api/auth/refresh` | Làm mới Access Token đã hết hạn | ❌ |
| `GET` | `/api/auth/me` | Lấy thông tin tài khoản hiện tại | ✅ |

### 2. Tải nhạc YouTube (`/api`)
| Phương thức | Đường dẫn | Mô tả | Yêu cầu xác thực |
|---|---|---|:---:|
| `POST` | `/api/dowload-music-from-yt` | Tải MP3/MP4 từ link YouTube, tùy chọn lưu lên Drive & MongoDB | ✅ |
| `GET` | `/api/dowload-music-from-yt` | Tải nhanh từ YouTube qua Query Params (hỗ trợ thử trên trình duyệt) | ✅ |
| `GET` | `/api/downloads/{filename}` | Tải lại file từ thư mục tạm trên server | ❌ |

**Ví dụ Body cho POST `/api/dowload-music-from-yt`:**
```json
{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "format": "mp3",
  "return_file": false,
  "save_to_drive": true
}
```

### 3. Quản lý bài hát (`/api/songs`)
| Phương thức | Đường dẫn | Mô tả | Yêu cầu xác thực |
|---|---|---|:---:|
| `GET` | `/api/songs` | Lấy danh sách bài hát (hỗ trợ `search`, `user_id`, `skip`, `limit`) | ❌ |
| `GET` | `/api/songs/{song_id}` | Xem chi tiết bài hát theo ID | ❌ |
| `POST` | `/api/songs/upload` | Upload trực tiếp file nhạc từ máy lên Google Drive & MongoDB | ✅ |
| `DELETE` | `/api/songs/{song_id}` | Xóa bài hát khỏi DB và Google Drive (chỉ tác giả mới xóa được) | ✅ |

---

## 🔒 Bảo mật & Lưu ý quan trọng

1. **Tuyệt đối không commit các file nhạy cảm lên Git**:
   - `.env`
   - `client_secrets.json`
   - `token.json`
   - `service_account.json`
   - Thư mục môi trường ảo `venv/`
2. **Cập nhật yt-dlp thường xuyên**: YouTube thường xuyên thay đổi cơ chế trích xuất, hãy nâng cấp thư viện khi gặp lỗi tải:
   ```powershell
   pip install --upgrade yt-dlp
   ```
3. **CORS Middleware**: Hệ thống đã bật sẵn `CORSMiddleware` với `allow_origins=["*"]`, thuận tiện kết nối tới ứng dụng Flutter / Web trong môi trường phát triển.
