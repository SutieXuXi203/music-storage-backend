import os
import asyncio
from typing import Optional, Dict, Any
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from app.config import settings

SCOPES = ["https://www.googleapis.com/auth/drive"]

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TOKEN_FILE = os.path.join(BACKEND_DIR, "token.json")
CLIENT_SECRETS_FILE = os.path.join(BACKEND_DIR, "client_secrets.json")


class DriveService:
    def __init__(self):
        self._service = None

    def _get_service(self):
        import json

        # 1. Hỗ trợ đọc token OAuth trực tiếp từ biến môi trường (tiện lợi khi deploy Cloud)
        token_env = os.getenv("GOOGLE_TOKEN_JSON")
        if token_env:
            try:
                info = json.loads(token_env)
                creds = Credentials.from_authorized_user_info(info, SCOPES)
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                if creds and creds.valid:
                    return build("drive", "v3", credentials=creds, cache_discovery=False)
            except Exception as e:
                print(f"[DriveService] Lỗi khi nạp GOOGLE_TOKEN_JSON: {e}")

        # 2. Ưu tiên file token.json (OAuth 2.0 hoặc Render Secret Files)
        if os.path.exists(TOKEN_FILE):
            try:
                creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    try:
                        with open(TOKEN_FILE, "w", encoding="utf-8") as token_f:
                            token_f.write(creds.to_json())
                    except Exception:
                        pass
                if creds and creds.valid:
                    return build("drive", "v3", credentials=creds, cache_discovery=False)
            except Exception as e:
                print(f"[DriveService] Lỗi khi nạp token.json: {e}")

        # 3. Hỗ trợ đọc Service Account trực tiếp từ biến môi trường
        sa_env = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        if sa_env:
            try:
                info = json.loads(sa_env)
                credentials = service_account.Credentials.from_service_account_info(
                    info, scopes=SCOPES
                )
                return build("drive", "v3", credentials=credentials, cache_discovery=False)
            except Exception as e:
                print(f"[DriveService] Lỗi khi nạp GOOGLE_SERVICE_ACCOUNT_JSON: {e}")

        # 4. Dự phòng dùng file Service Account vật lý
        key_path = settings.GOOGLE_SERVICE_ACCOUNT_FILE
        if not os.path.isabs(key_path):
            key_path = os.path.join(BACKEND_DIR, key_path)

        if os.path.exists(key_path):
            credentials = service_account.Credentials.from_service_account_file(
                key_path, scopes=SCOPES
            )
            return build("drive", "v3", credentials=credentials, cache_discovery=False)

        raise FileNotFoundError(
            "Không tìm thấy cấu hình Google Drive! Cần có file 'token.json' (OAuth) hoặc 'service_account.json'."
        )

    def get_or_create_folder_sync(
        self,
        folder_name: str,
        parent_id: Optional[str] = None,
        make_public: bool = True,
    ) -> str:
        """Tìm kiếm hoặc tạo mới một thư mục con trên Google Drive ứng với tên chỉ định"""
        service = self._get_service()
        parent = parent_id or settings.GOOGLE_DRIVE_FOLDER_ID

        # Escape ký tự nháy đơn để tránh lỗi query
        safe_name = folder_name.replace("'", "\\'")
        query = (
            f"mimeType = 'application/vnd.google-apps.folder' "
            f"and name = '{safe_name}' "
            f"and trashed = false"
        )
        if parent:
            query += f" and '{parent}' in parents"

        results = (
            service.files()
            .list(
                q=query,
                spaces="drive",
                fields="files(id, name)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        files = results.get("files", [])
        if files:
            return files[0]["id"]

        # Nếu chưa có thì tạo mới thư mục con
        folder_metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent:
            folder_metadata["parents"] = [parent]

        folder = (
            service.files()
            .create(
                body=folder_metadata,
                fields="id, name",
                supportsAllDrives=True,
            )
            .execute()
        )
        folder_id = folder.get("id")

        # Cấp quyền chia sẻ công khai cho thư mục nếu cần
        if make_public and folder_id:
            try:
                permission = {"type": "anyone", "role": "reader"}
                service.permissions().create(
                    fileId=folder_id,
                    body=permission,
                    supportsAllDrives=True,
                ).execute()
            except Exception as e:
                print(f"[DriveService] Cảnh báo cấp quyền public cho folder {folder_id}: {e}")

        return folder_id

    async def get_or_create_folder(
        self,
        folder_name: str,
        parent_id: Optional[str] = None,
        make_public: bool = True,
    ) -> str:
        """Tìm hoặc tạo thư mục con bất đồng bộ"""
        return await asyncio.to_thread(
            self.get_or_create_folder_sync,
            folder_name,
            parent_id,
            make_public,
        )

    def upload_file_sync(
        self,
        local_file_path: str,
        filename: str,
        mime_type: str = "audio/mpeg",
        folder_id: Optional[str] = None,
        subfolder_name: Optional[str] = None,
        make_public: bool = True,
    ) -> Dict[str, Any]:
        """Tải file lên Google Drive đồng bộ, hỗ trợ tự động tạo thư mục con theo subfolder_name"""
        if not os.path.exists(local_file_path):
            raise FileNotFoundError(f"File cục bộ không tồn tại: {local_file_path}")

        target_folder = folder_id or settings.GOOGLE_DRIVE_FOLDER_ID
        created_subfolder_id = None

        # Nếu có yêu cầu tạo thư mục con theo tên bài hát/title
        if subfolder_name:
            target_folder = self.get_or_create_folder_sync(
                folder_name=subfolder_name,
                parent_id=target_folder,
                make_public=make_public,
            )
            created_subfolder_id = target_folder

        service = self._get_service()

        file_metadata = {
            "name": filename,
        }
        if target_folder:
            file_metadata["parents"] = [target_folder]

        media = MediaFileUpload(local_file_path, mimetype=mime_type, resumable=True)

        uploaded_file = (
            service.files()
            .create(
                body=file_metadata,
                media_body=media,
                fields="id, name, webViewLink, webContentLink, size",
                supportsAllDrives=True,
            )
            .execute()
        )

        file_id = uploaded_file.get("id")

        # Cấp quyền Anyone with link can view (để Flutter app có thể phát nhạc trực tiếp)
        if make_public and file_id:
            try:
                permission = {
                    "type": "anyone",
                    "role": "reader",
                }
                service.permissions().create(
                    fileId=file_id,
                    body=permission,
                    supportsAllDrives=True,
                ).execute()
            except Exception as perm_err:
                print(f"[DriveService] Cảnh báo cấp quyền public cho {file_id}: {perm_err}")

        direct_stream_url = f"https://drive.google.com/uc?export=download&id={file_id}"

        return {
            "file_id": file_id,
            "filename": uploaded_file.get("name"),
            "size": uploaded_file.get("size"),
            "subfolder_id": created_subfolder_id,
            "subfolder_name": subfolder_name,
            "web_view_link": uploaded_file.get("webViewLink"),
            "web_content_link": uploaded_file.get("webContentLink"),
            "direct_stream_url": direct_stream_url,
        }

    async def upload_file(
        self,
        local_file_path: str,
        filename: str,
        mime_type: str = "audio/mpeg",
        folder_id: Optional[str] = None,
        subfolder_name: Optional[str] = None,
        make_public: bool = True,
    ) -> Dict[str, Any]:
        """Tải file lên Google Drive bất đồng bộ (chạy trong worker thread)"""
        return await asyncio.to_thread(
            self.upload_file_sync,
            local_file_path,
            filename,
            mime_type,
            folder_id,
            subfolder_name,
            make_public,
        )

    def delete_file_sync(self, file_id: str) -> bool:
        """Xoá file hoặc thư mục trên Google Drive"""
        try:
            service = self._get_service()
            service.files().delete(fileId=file_id, supportsAllDrives=True).execute()
            return True
        except Exception as e:
            print(f"[DriveService] Lỗi xoá file {file_id}: {e}")
            return False

    async def delete_file(self, file_id: str) -> bool:
        """Xoá file hoặc thư mục trên Google Drive bất đồng bộ"""
        return await asyncio.to_thread(self.delete_file_sync, file_id)

    @staticmethod
    def get_direct_stream_url(file_id: Optional[str]) -> Optional[str]:
        """Tạo đường dẫn phát nhạc hoặc tải trực tiếp từ mã file Google Drive"""
        if not file_id:
            return None
        return f"https://drive.google.com/uc?export=download&id={file_id}"

    @staticmethod
    def get_web_view_link(file_id: Optional[str]) -> Optional[str]:
        """Tạo đường dẫn xem file trên giao diện Web Google Drive từ mã file"""
        if not file_id:
            return None
        return f"https://drive.google.com/file/d/{file_id}/view?usp=drivesdk"


drive_service = DriveService()

