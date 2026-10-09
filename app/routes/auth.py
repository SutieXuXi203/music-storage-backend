from datetime import datetime, timedelta, timezone
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
import bcrypt
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.config import settings
from app.database import get_database
from bson import ObjectId

router = APIRouter(prefix="/api/auth", tags=["Xác thực tài khoản"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# Regex validation patterns
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]+$")
PASSWORD_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*[0-9]).{6,}$")
EMAIL_RE = re.compile(r"^[\w\.\+\-]+@[a-zA-Z0-9_\.\-]+$")


class RegisterRequest(BaseModel):
    username: str = Field(
        ...,
        min_length=3,
        max_length=50,
        description="Tên đăng nhập (chỉ gồm chữ cái, chữ số và dấu gạch dưới)",
        example="nguyenvana",
    )
    email: Optional[str] = Field(
        default=None,
        description="Địa chỉ email hợp lệ hoặc bỏ trống",
        example="user@example.com",
    )
    password: str = Field(
        ...,
        min_length=6,
        max_length=128,
        description="Mật khẩu (tối thiểu 6 ký tự, gồm cả chữ cái và chữ số)",
        example="Matkhau123",
    )
    full_name: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Họ và tên đầy đủ",
        example="Nguyễn Văn A",
    )

    @field_validator("username")
    @classmethod
    def username_alphanumeric(cls, v: str) -> str:
        v = v.strip()
        if not USERNAME_RE.match(v):
            raise ValueError("Tên đăng nhập chỉ được chứa chữ cái (a-z, A-Z), chữ số (0-9) và dấu gạch dưới (_)")
        return v.lower()

    @field_validator("email")
    @classmethod
    def email_format_validator(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip().lower()
            if not v:
                return None
            if not EMAIL_RE.match(v):
                raise ValueError("Địa chỉ email không đúng định dạng")
        return v

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not PASSWORD_RE.match(v):
            raise ValueError("Mật khẩu phải có ít nhất 6 ký tự, bao gồm cả chữ cái và chữ số")
        return v

    @field_validator("full_name")
    @classmethod
    def full_name_strip(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if len(v) == 0:
                return None
        return v


class LoginResponse(BaseModel):
    access_token: str = Field(description="Mã truy cập (Access Token)")
    refresh_token: str = Field(description="Mã làm mới (Refresh Token)")
    token_type: str = Field(default="bearer", description="Loại mã xác thực")
    expires_in: int = Field(description="Thời hạn hiệu lực tính bằng giây")


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., description="Mã làm mới (Refresh Token)")


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, description="Mật khẩu hiện tại", example="Matkhaucu123")
    new_password: str = Field(
        ...,
        min_length=6,
        max_length=128,
        description="Mật khẩu mới (tối thiểu 6 ký tự, gồm cả chữ và số)",
        example="Matkhaumoi456",
    )

    @field_validator("new_password")
    @classmethod
    def new_password_strength(cls, v: str) -> str:
        if not PASSWORD_RE.match(v):
            raise ValueError("Mật khẩu mới phải có ít nhất 6 ký tự, bao gồm cả chữ cái và chữ số")
        return v

    @model_validator(mode="after")
    def passwords_differ(self) -> "ChangePasswordRequest":
        if self.old_password == self.new_password:
            raise ValueError("Mật khẩu mới phải khác mật khẩu cũ")
        return self


class UpdateProfileRequest(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=100, description="Họ và tên mới", example="Nguyễn Văn B")
    email: Optional[EmailStr] = Field(default=None, description="Địa chỉ email mới", example="moi@example.com")

    @field_validator("full_name")
    @classmethod
    def full_name_strip(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if len(v) == 0:
                return None
        return v

    @model_validator(mode="after")
    def at_least_one_field(self) -> "UpdateProfileRequest":
        if self.full_name is None and self.email is None:
            raise ValueError("Phải cung cấp ít nhất một trường để cập nhật (họ tên hoặc email)")
        return self


class UserProfile(BaseModel):
    id: str = Field(description="Mã định danh người dùng")
    username: str = Field(description="Tên đăng nhập")
    email: str = Field(description="Địa chỉ email")
    full_name: Optional[str] = Field(default=None, description="Họ và tên")
    drive_folder_id: Optional[str] = Field(default=None, description="Mã thư mục cha trên Google Drive")
    drive_folder_name: Optional[str] = Field(default=None, description="Tên thư mục cha trên Google Drive")
    created_at: datetime = Field(description="Thời điểm tạo tài khoản")
    is_active: bool = Field(description="Trạng thái kích hoạt")


def hash_password(plain: str) -> str:
    pwd_bytes = plain.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        pwd_bytes = plain.encode("utf-8")[:72]
        hashed_bytes = hashed.encode("utf-8")
        return bcrypt.checkpw(pwd_bytes, hashed_bytes)
    except Exception:
        return False


def _make_token(data: dict, expires_delta: timedelta, token_type: str = "access") -> str:
    payload = data.copy()
    payload.update({
        "type": token_type,
        "exp": datetime.now(timezone.utc) + expires_delta,
        "iat": datetime.now(timezone.utc),
    })
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: str, username: str) -> str:
    return _make_token(
        {"sub": user_id, "username": username},
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "access",
    )


def create_refresh_token(user_id: str) -> str:
    return _make_token(
        {"sub": user_id},
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        "refresh",
    )


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Mã xác thực không hợp lệ hoặc đã hết hạn",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise credentials_exception
        user_id: str = payload.get("sub")
        if not user_id:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    db = get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Cơ sở dữ liệu không khả dụng")

    from bson import ObjectId
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise credentials_exception
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Tài khoản đã bị vô hiệu hóa")
    return user


async def get_or_create_user_drive_folder(user: dict) -> str:
    """Lấy hoặc tự động tạo thư mục cha trên Google Drive theo full_name cho người dùng và đồng bộ vào collection folders"""
    user_id_str = str(user["_id"])
    folder_id = user.get("drive_folder_id")
    folder_name = (user.get("full_name") or user.get("username") or "User").strip()
    from app.services.drive_service import drive_service

    if not folder_id:
        folder_id = await drive_service.get_or_create_folder(
            folder_name=folder_name,
            parent_id=settings.GOOGLE_DRIVE_FOLDER_ID,
            make_public=False,
            user_id=user_id_str,
        )
        db = get_database()
        if db is not None:
            await db.users.update_one(
                {"_id": user["_id"]},
                {"$set": {"drive_folder_id": folder_id, "drive_folder_name": folder_name}},
            )
            user["drive_folder_id"] = folder_id
            user["drive_folder_name"] = folder_name

    return folder_id


@router.post(
    "/register",
    summary="Đăng ký tài khoản mới",
    description="Đăng ký tài khoản người dùng mới, tự động tạo thư mục trên Google Drive và bản ghi thư mục trong collection folders",
    status_code=status.HTTP_201_CREATED,
)
async def register(req: RegisterRequest):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Cơ sở dữ liệu không khả dụng")

    user_email = req.email or f"{req.username}@drive.local"

    existing_filter = [{"username": req.username}]
    if req.email and not req.email.endswith("@drive.local"):
        existing_filter.append({"email": req.email})

    existing = await db.users.find_one({"$or": existing_filter})
    if existing:
        field = "Tên đăng nhập" if existing.get("username") == req.username else "Email"
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"{field} đã được sử dụng")

    # Tạo ObjectId cho user trước để có ID gán vào Drive folder và collection folders
    user_id_obj = ObjectId()
    user_id_str = str(user_id_obj)

    # Tạo thư mục cha trên Google Drive theo full_name của người dùng (fallback: username)
    user_folder_name = (req.full_name or req.username).strip()
    drive_folder_id = None
    try:
        from app.services.drive_service import drive_service
        drive_folder_id = await drive_service.get_or_create_folder(
            folder_name=user_folder_name,
            parent_id=settings.GOOGLE_DRIVE_FOLDER_ID,
            make_public=False,
            user_id=user_id_str,
        )
    except Exception as e:
        print(f"[Auth Register] Cảnh báo tạo thư mục Drive cho user {req.username}: {e}")

    now = datetime.now(timezone.utc)

    # Tạo bản ghi trong collection users
    user_doc = {
        "_id": user_id_obj,
        "username": req.username,
        "email": user_email,
        "hashed_password": hash_password(req.password),
        "full_name": req.full_name,
        "drive_folder_id": drive_folder_id,
        "drive_folder_name": user_folder_name,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    await db.users.insert_one(user_doc)

    return {
        "status": "success",
        "message": "Đăng ký thành công",
        "user_id": user_id_str,
        "username": req.username,
        "email": req.email,
        "drive_folder_id": drive_folder_id,
        "drive_folder_name": user_folder_name,
    }


@router.post(
    "/login",
    summary="Đăng nhập tài khoản",
    description="Đăng nhập bằng tên đăng nhập và mật khẩu để nhận Access Token và Refresh Token (hỗ trợ cả JSON body và Form-data)",
    response_model=LoginResponse,
)
async def login(
    request: Request,
):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Cơ sở dữ liệu không khả dụng")

    username = None
    password = None

    # 1. Thử đọc từ JSON body
    content_type = request.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        try:
            body = await request.json()
            username = body.get("username")
            password = body.get("password")
        except Exception:
            pass

    # 2. Thử đọc từ Form data
    if not username or not password:
        try:
            form = await request.form()
            username = form.get("username")
            password = form.get("password")
        except Exception:
            pass

    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Vui lòng cung cấp đầy đủ tên đăng nhập (username) và mật khẩu (password)",
        )

    user = await db.users.find_one({"username": username})
    if not user or not verify_password(password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tên đăng nhập hoặc mật khẩu không chính xác",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Tài khoản đã bị vô hiệu hóa")

    user_id = str(user["_id"])
    access_token = create_access_token(user_id, user["username"])
    refresh_token = create_refresh_token(user_id)

    # Đảm bảo thư mục Drive và bản ghi collection folders luôn tồn tại cho tài khoản
    try:
        await get_or_create_user_drive_folder(user)
    except Exception as e:
        print(f"[Auth Login] Cảnh báo đồng bộ thư mục người dùng {username}: {e}")

    SET_LOGIN = {"$set": {"refresh_token": refresh_token, "last_login": datetime.now(timezone.utc)}}
    await db.users.update_one(
        {"_id": user["_id"]},
        SET_LOGIN,
    )

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )



@router.post(
    "/refresh",
    summary="Làm mới Access Token",
    description="Cấp lại Access Token mới khi token cũ hết hạn bằng Refresh Token",
)
async def refresh_token(req: RefreshRequest):
    invalid_exc = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token không hợp lệ hoặc đã hết hạn")
    try:
        payload = jwt.decode(req.refresh_token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise invalid_exc
        user_id: str = payload.get("sub")
        if not user_id:
            raise invalid_exc
    except JWTError:
        raise invalid_exc

    db = get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Cơ sở dữ liệu không khả dụng")

    from bson import ObjectId
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user or user.get("refresh_token") != req.refresh_token:
        raise invalid_exc

    new_access = create_access_token(user_id, user["username"])
    return {"access_token": new_access, "token_type": "bearer", "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60}


@router.post(
    "/logout",
    summary="Đăng xuất tài khoản",
    description="Đăng xuất và thu hồi Refresh Token của phiên làm việc",
)
async def logout(current_user: dict = Depends(get_current_user)):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Cơ sở dữ liệu không khả dụng")
    UNSET_OP = {"$unset": {"refresh_token": ""}}
    await db.users.update_one({"_id": current_user["_id"]}, UNSET_OP)
    return {"status": "success", "message": "Đã đăng xuất thành công"}


@router.get(
    "/me",
    summary="Xem thông tin cá nhân",
    description="Lấy thông tin tài khoản người dùng đang đăng nhập",
    response_model=UserProfile,
)
async def get_me(current_user: dict = Depends(get_current_user)):
    return UserProfile(
        id=str(current_user["_id"]),
        username=current_user["username"],
        email=current_user["email"],
        full_name=current_user.get("full_name"),
        drive_folder_id=current_user.get("drive_folder_id"),
        drive_folder_name=current_user.get("drive_folder_name"),
        created_at=current_user["created_at"],
        is_active=current_user.get("is_active", True),
    )


@router.put(
    "/me",
    summary="Cập nhật thông tin cá nhân",
    description="Cập nhật họ tên hoặc email của tài khoản đang đăng nhập",
)
async def update_profile(
    req: UpdateProfileRequest,
    current_user: dict = Depends(get_current_user),
):
    db = get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Cơ sở dữ liệu không khả dụng")

    update_fields: dict = {"updated_at": datetime.now(timezone.utc)}
    if req.full_name is not None:
        new_name = req.full_name.strip()
        update_fields["full_name"] = new_name
        # Đổi tên thư mục cha trên Google Drive nếu đã có
        if current_user.get("drive_folder_id"):
            try:
                from app.services.drive_service import drive_service
                service = drive_service._get_service()
                service.files().update(
                    fileId=current_user["drive_folder_id"],
                    body={"name": new_name},
                ).execute()
                update_fields["drive_folder_name"] = new_name
            except Exception as e:
                print(f"[Auth Update] Lỗi đổi tên folder Drive: {e}")

    if req.email is not None:
        NE_QUERY = {"email": req.email, "_id": {"$ne": current_user["_id"]}}
        conflict = await db.users.find_one(NE_QUERY)
        if conflict:
            raise HTTPException(status_code=409, detail="Email đã được sử dụng bởi tài khoản khác")
        update_fields["email"] = req.email

    SET_OP = {"$set": update_fields}
    await db.users.update_one({"_id": current_user["_id"]}, SET_OP)
    updated_keys = [k for k in update_fields if k != "updated_at"]
    return {"status": "success", "message": "Cập nhật thành công", "updated": updated_keys}


@router.post(
    "/change-password",
    summary="Đổi mật khẩu",
    description="Thay đổi mật khẩu tài khoản hiện tại (yêu cầu mật khẩu cũ)",
)
async def change_password(
    req: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    if not verify_password(req.old_password, current_user["hashed_password"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mật khẩu cũ không chính xác")
    if req.old_password == req.new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mật khẩu mới phải khác mật khẩu cũ")

    db = get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Cơ sở dữ liệu không khả dụng")

    SET_PW = {
        "$set": {
            "hashed_password": hash_password(req.new_password),
            "refresh_token": None,
            "updated_at": datetime.now(timezone.utc),
        }
    }
    await db.users.update_one({"_id": current_user["_id"]}, SET_PW)
    return {"status": "success", "message": "Đổi mật khẩu thành công. Vui lòng đăng nhập lại."}
