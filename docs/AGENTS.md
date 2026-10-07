# 🤖 AGENTS.md - Quy chuẩn & Cẩm nang dành cho AI Agents và Developers

Tài liệu này là **Quy chuẩn Vận hành (Operating Manual)** bắt buộc dành cho bất kỳ AI Coding Agent nào (Antigravity, Claude, ChatGPT, Cursor, Copilot...) hoặc Lập trình viên mới khi tiếp cận, sửa đổi, kiểm thử hoặc mở rộng mã nguồn của dự án **Music Storage Backend**.

---

## 🧭 1. Triết lý Phát triển & Nguyên tắc Bất biến

1. **Bảo mật là tiên quyết**:
   - Tuyệt đối **KHÔNG BAO GIỜ** commit, in ra log công khai hoặc gửi ra ngoài các thông tin nhạy cảm: `.env`, `token.json`, `client_secrets.json`, `service_account.json`.
   - Bất kỳ file chứa credential nào mới tạo ra phải được khai báo ngay lập tức vào `.gitignore`.
2. **Bất đồng bộ hóa (Async-First)**:
   - FastAPI chạy trên nền tảng async event loop. Tất cả các endpoint, thao tác cơ sở dữ liệu MongoDB (Motor) phải dùng `async` / `await`.
   - Các tác vụ I/O blocking hoặc tính toán nặng (như `yt-dlp` download, FFmpeg processing, xử lý file cục bộ) **BẮT BUỘC** phải được bọc trong `asyncio.to_thread()` để không làm treo máy chủ.
3. **Thư mục làm việc Git**:
   - Gốc của Git repository hiện tại nằm tại: `c:\Users\manhd\Desktop\music-app\backend`.
   - Khi chạy bất kỳ lệnh `git` nào, thư mục làm việc (Cwd) bắt buộc phải là `backend/`.
4. **Không làm vỡ luồng người dùng (Non-Breaking Changes)**:
   - Cấu trúc thư mục Google Drive đã chuẩn hóa là 2 cấp: `Thư mục User (theo full_name)` -> `Thư mục Bài hát` -> `(.mp3 + _thumb.jpg)`. Không tự ý thay đổi cấu trúc này nếu không có yêu cầu từ người dùng.

---

## 🗂 2. Cấu trúc Dự án & Trách nhiệm Từng Module

```text
backend/
├── app/
│   ├── routes/
│   │   ├── auth.py          # Xử lý JWT, đăng ký, đăng nhập, cấp thư mục Drive cho user
│   │   ├── songs.py         # CRUD bài hát, upload trực tiếp, xóa bài kèm xóa file trên Drive
│   │   └── youtube.py       # Tải YouTube (yt-dlp + FFmpeg), thumbnail, upload Drive 2 cấp
│   ├── services/
│   │   ├── __init__.py
│   │   ├── auth_drive.py    # Quản lý OAuth 2.0 flow, token.json, refresh credentials
│   │   └── drive_service.py # Google Drive v3 wrapper: tạo folder, upload, xóa, cấp public
│   ├── config.py            # Quản lý cấu hình & biến môi trường (Settings)
│   ├── database.py          # Quản lý kết nối Async MongoDB (Motor)
│   ├── main.py              # Điểm khởi động FastAPI app, CORS, lifespan, đăng ký router
│   └── models.py            # Pydantic models (SongBase, SongCreate, SongResponse...)
├── docs/                    # Thư mục tài liệu dự án
│   ├── AGENTS.md            # Tài liệu dành cho AI Agent & Devs
│   ├── PROJECT.md           # Đặc tả kiến trúc dự án
│   └── README.md            # Hướng dẫn sử dụng & API docs
├── downloads/               # Thư mục tạm thời lưu file media khi đang xử lý (bị ignore)
├── .env.example             # File mẫu biến môi trường
├── .gitignore               # Bộ lọc bảo mật Git
├── requirements.txt         # Danh sách thư viện Python
└── run.py                   # Script khởi chạy máy chủ Uvicorn
```

---

## ⚠️ 3. Những Cạm bẫy Thường gặp (Gotchas & Pitfalls)

### 🔴 Cạm bẫy 1: Lỗi Thư viện `passlib` với `bcrypt >= 4.1.0`
- **Vấn đề**: Thư viện `passlib.context.CryptContext` phiên bản `1.7.4` có lỗi cố hữu khi làm việc với `bcrypt >= 4.1.0` (ném lỗi `ValueError: password cannot be longer than 72 bytes` hoặc lỗi `AttributeError: module 'bcrypt' has no attribute '__about__'`).
- **Quy chuẩn bắt buộc**: Sử dụng trực tiếp module `bcrypt` của Python:
  ```python
  import bcrypt

  # Băm mật khẩu:
  salt = bcrypt.gensalt(rounds=12)
  password_hash = bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

  # Kiểm tra mật khẩu:
  is_valid = bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
  ```

### 🔴 Cạm bẫy 2: Tên File & Thư mục Chứa Ký tự Cấm trên Windows
- **Vấn đề**: Tiêu đề bài hát trên YouTube thường chứa các ký tự như `|`, `:`, `"`, `?`, `/`, `\`. Trên hệ điều hành Windows, việc tạo file hoặc thư mục chứa các ký tự này sẽ ném lỗi `OSError: [Errno 22] Invalid argument`.
- **Quy chuẩn bắt buộc**: Luôn gọi hàm `sanitize_filename()` trước khi lưu file tạm hoặc tạo tên folder:
  ```python
  import re
  def sanitize_filename(name: str) -> str:
      sanitized = re.sub(r'[\\/*?:"<>|]', "", name)
      return sanitized.strip()[:100]
  ```

### 🔴 Cạm bẫy 3: Google Drive Token Hết hạn (OAuth Token Refresh)
- **Vấn đề**: Google Access Token thường hết hạn sau 1 giờ. Nếu gọi API trực tiếp mà không kiểm tra hạn sẽ bị `401 Unauthorized`.
- **Quy chuẩn**: Trong `app/services/drive_service.py` và `auth_drive.py`, luôn sử dụng đối tượng `Credentials` với cơ chế:
  ```python
  if creds and creds.expired and creds.refresh_token:
      creds.refresh(Request())
  ```
  File `token.json` sẽ tự động được làm mới và lưu lại trên đĩa.

### 🔴 Cạm bẫy 4: YouTube Bot Detection của `yt-dlp`
- **Vấn đề**: YouTube liên tục siết chặt bot detection, yêu cầu xác minh bot hoặc chặn IP server (`Sign in to confirm you're not a bot`).
- **Quy chuẩn bắt buộc**:
  - Luôn khai báo `js_runtimes: {"deno": {}, "node": {}}` và `remote_components: {"ejs:github": {}}`.
  - Hỗ trợ nạp cookie Netscape từ file `backend/downloads/cookies.txt` hoặc biến môi trường `YOUTUBE_COOKIES`.
  - **Lưu ý định dạng**: File cookies xuất từ extension thường bị dính ký tự UTF-8 BOM (`\ufeff`) khiến `yt-dlp` không nhận diện được. Bắt buộc phải xử lý `.replace("\ufeff", "")` và đảm bảo dòng đầu luôn là `# Netscape HTTP Cookie File`.

### 🔴 Cạm bẫy 5: MongoDB Atlas SSL/TLS Handshake trên Windows & Linux
- **Vấn đề**: Khi kết nối chuỗi `mongodb+srv://` tới MongoDB Atlas, môi trường Windows có thể gặp lỗi `[SSL: TLSV1_ALERT_INTERNAL_ERROR] tlsv1 alert internal error` do thiếu chứng chỉ CA gốc của hệ điều hành.
- **Quy chuẩn bắt buộc**:
  - Luôn import `certifi` và truyền tham số `tlsCAFile=certifi.where()` vào `AsyncIOMotorClient`:
    ```python
    import certifi
    client = AsyncIOMotorClient(settings.MONGODB_URL, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=5000)
    ```
  - Khi gặp lỗi handshake hoặc timeout, nhắc nhở người dùng kiểm tra mục **Network Access** trên MongoDB Atlas console và thêm dải IP `0.0.0.0/0` (Allow Access from Anywhere).

### 🔴 Cạm bẫy 6: CORS & HTTP Byte-Range Header cho Web & Mobile Audio Player
- **Vấn đề**: Google Drive direct download URL đôi khi không hỗ trợ đầy đủ `Accept-Ranges: bytes` hoặc bị chặn CORS trên trình duyệt Web, khiến các package nghe nhạc (như `just_audio` trên Flutter Web) không thể tua nhạc (seek) hoặc không load được ảnh cover.
- **Quy chuẩn bắt buộc**:
  - Đối với ảnh bìa: Luôn sinh link `https://lh3.googleusercontent.com/d/{cover_id}` hoặc qua endpoint `GET /api/songs/{id}/cover` (được gắn header `Access-Control-Allow-Origin: *` và cache 24h).
  - Đối với âm thanh: Endpoint proxy `GET /api/songs/{id}/stream` thực hiện stream từng chunk và khai báo header `Accept-Ranges: bytes` cùng `Content-Length` chính xác để client có thể tua mượt mà tới từng giây của bài hát.

---

## 🛠 4. Quy trình Kiểm thử & Xác minh Thay đổi (Verification Workflow)

Mỗi khi thêm một tính năng hoặc sửa một lỗi, Agent cần thực hiện các bước sau để đảm bảo không phát sinh lỗi tiềm ẩn:

### Bước 1: Kiểm tra cú pháp (Syntax Validation)
Chạy script kiểm tra compile toàn bộ code Python mà không cần chạy server:
```powershell
python -m compileall app/
```
Nếu có lỗi thụt lề (IndentationError) hoặc lỗi cú pháp (SyntaxError), lệnh sẽ báo lỗi ngay lập tức.

### Bước 2: Kiểm tra kết nối MongoDB & Khởi động Server
Kiểm tra xem file `run.py` có import lỗi package nào không:
```powershell
python -c "from app.main import app; print('App imported successfully!')"
```

### Bước 3: Xác minh Git Status
Trước khi kết thúc phiên làm việc:
```powershell
git status
```
Đảm bảo không có file lạ (`.env`, `token.json`, `*.pyc`, `downloads/*`) nằm trong danh sách `Untracked files`.

---

## 📝 5. Quy tắc Đặt tên & Viết Mã (Coding Conventions)

1. **Ngôn ngữ**: 
   - Tên biến, hàm, class: Sử dụng tiếng Anh chuẩn (vd: `get_current_user`, `drive_service`, `SongResponse`).
   - Docstrings, thông báo lỗi người dùng (HTTPException detail), mô tả Swagger: Sử dụng **Tiếng Việt** rõ ràng, thân thiện.
2. **Schema & Model**:
   - Sử dụng Pydantic V2 syntax (`@field_validator` thay vì `@validator`, `@model_validator` thay vì `@root_validator`).
3. **Database Operations**:
   - Luôn kiểm tra `db = get_database()` khác `None` trước khi thực hiện truy vấn.
   - Khi trả về dữ liệu MongoDB ra ngoài API, luôn chuyển đổi trường `_id` (ObjectId) thành chuỗi `id` thông qua hàm `serialize_song()`.
