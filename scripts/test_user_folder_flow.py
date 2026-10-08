import asyncio
import os
import sys
import uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bson import ObjectId
from app.database import connect_to_mongo, get_database
from app.routes.auth import register, RegisterRequest, get_or_create_user_drive_folder
from app.routes.folders import list_folders
from app.services.drive_service import drive_service

sys.stdout.reconfigure(encoding='utf-8')

async def run_test():
    await connect_to_mongo()
    db = get_database()

    unique_suffix = uuid.uuid4().hex[:6]
    test_username = f"user_{unique_suffix}"
    test_fullname = f"Nguyen Van {unique_suffix.upper()}"
    test_password = "password123"

    print(f"\n--- BẮT ĐẦU KIỂM THỬ: ĐĂNG KÝ USER MỚI '{test_username}' (Họ tên: '{test_fullname}') ---")

    # 1. Gọi hàm register
    req = RegisterRequest(
        username=test_username,
        password=test_password,
        full_name=test_fullname,
        email=f"{test_username}@example.com",
    )
    reg_res = await register(req)
    print(f"Kết quả đăng ký: {reg_res}")

    assert reg_res["status"] == "success"
    user_id = reg_res["user_id"]
    drive_folder_id = reg_res.get("drive_folder_id")
    default_folder_id = reg_res.get("default_folder_id")

    assert user_id is not None
    assert default_folder_id is not None
    print(f"✓ Đã tạo User ID: {user_id}, Default Folder ID: {default_folder_id}")

    # 2. Kiểm tra bản ghi trong collection 'folders'
    folder_doc = await db.folders.find_one({"_id": ObjectId(default_folder_id)})
    assert folder_doc is not None, "Không tìm thấy bản ghi trong collection 'folders'!"
    print(f"✓ Tìm thấy folder trong collection 'folders': {folder_doc.get('name')}")
    assert folder_doc["name"] == test_fullname, f"Tên folder không khớp: {folder_doc['name']} != {test_fullname}"
    assert folder_doc["user_id"] == user_id, f"user_id không khớp: {folder_doc['user_id']} != {user_id}"
    assert folder_doc["drive_folder_id"] == drive_folder_id, f"drive_folder_id không khớp: {folder_doc['drive_folder_id']} != {drive_folder_id}"
    assert folder_doc["is_default"] is True
    assert folder_doc["song_ids"] == []

    # 3. Kiểm tra API list_folders
    user_doc = await db.users.find_one({"_id": ObjectId(user_id)})
    list_res = await list_folders(current_user=user_doc)
    print(f"✓ Kết quả list_folders: {list_res['total']} thư mục")
    assert list_res["total"] >= 1
    found = False
    for f in list_res["data"]:
        if f["id"] == default_folder_id:
            found = True
            assert f["name"] == test_fullname
            assert f["user_id"] == user_id
            assert f["is_default"] is True
            print(f"✓ Thư mục trong danh sách API: Name='{f['name']}', user_id='{f['user_id']}', is_default={f['is_default']}")
    assert found, "Thư mục không xuất hiện trong API list_folders!"

    # 4. Dọn dẹp tài nguyên test
    print("\n--- DỌN DẸP DỮ LIỆU TEST ---")
    await db.users.delete_one({"_id": ObjectId(user_id)})
    await db.folders.delete_one({"_id": ObjectId(default_folder_id)})
    if drive_folder_id:
        try:
            await drive_service.delete_file(drive_folder_id)
            print(f"✓ Đã xoá thư mục test trên Drive: {drive_folder_id}")
        except Exception:
            pass
    print("✓ Đã xoá dữ liệu test thành công.")
    print("\n====== TẤT CẢ CÁC BƯỚC KIỂM THỬ ĐÃ THÀNH CÔNG 100%! ======\n")

if __name__ == '__main__':
    asyncio.run(run_test())
