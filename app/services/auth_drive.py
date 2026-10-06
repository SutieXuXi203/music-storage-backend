import os
import sys
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Full Drive access to upload and create sharing links
SCOPES = ["https://www.googleapis.com/auth/drive"]

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CLIENT_SECRETS_FILE = os.path.join(BACKEND_DIR, "client_secrets.json")
TOKEN_FILE = os.path.join(BACKEND_DIR, "token.json")


def authenticate_google_drive():
    """Chạy flow đăng nhập Google OAuth 2.0 một lần duy nhất để tạo token.json"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if not os.path.exists(CLIENT_SECRETS_FILE):
        print(f"❌ Không tìm thấy file: {CLIENT_SECRETS_FILE}")
        print("👉 Vui lòng tải file OAuth Client JSON từ Google Cloud Console và đổi tên thành 'client_secrets.json' đặt tại thư mục backend/")
        return None

    creds = None
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception:
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("🔄 Đang làm mới token bằng Refresh Token...")
            creds.refresh(Request())
        else:
            print("🚀 Đang mở trình duyệt để bạn đăng nhập Google và cấp quyền...")
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        # Lưu lại token vào token.json
        with open(TOKEN_FILE, "w", encoding="utf-8") as token:
            token.write(creds.to_json())
        print(f"✅ Đăng nhập thành công! Token đã được lưu tại: {TOKEN_FILE}")
    else:
        print(f"✅ Token đã hợp lệ tại: {TOKEN_FILE}")

    return creds


if __name__ == "__main__":
    authenticate_google_drive()
