from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import close_mongo_connection, connect_to_mongo
from app.routes.auth import router as auth_router
from app.routes.youtube import router as youtube_router
from app.routes.songs import router as songs_router
from app.routes.folders import router as folders_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Khởi động kết nối MongoDB
    await connect_to_mongo()
    yield
    # Ngắt kết nối MongoDB khi tắt server
    await close_mongo_connection()

app = FastAPI(
    title="Hệ thống API Ứng dụng Nghe nhạc",
    description="Backend API cho ứng dụng nghe nhạc đa nền tảng (Flutter + MongoDB + Google Drive)",
    version="1.0.0",
    lifespan=lifespan,
)

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi import Request

# Cấu hình CORS để ứng dụng Flutter (Mobile & Desktop) có thể gọi API không bị chặn
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    print(f"[Validation Error 422] {request.method} {request.url.path} - Chi tiết lỗi: {errors}")
    return JSONResponse(
        status_code=422,
        content={"detail": errors},
    )

# Đăng ký routes
app.include_router(auth_router)
app.include_router(youtube_router)
app.include_router(songs_router)
app.include_router(folders_router)


@app.get("/", tags=["Hệ thống"], summary="Kiểm tra trạng thái hệ thống")
async def root():
    return {
        "ung_dung": "Music App Backend",
        "trang_thai": "Hoạt động",
        "tai_lieu_api": "/docs",
    }

@app.get("/api/health", tags=["Hệ thống"], summary="Kiểm tra kết nối cơ sở dữ liệu")
async def health_check():
    return {"trang_thai": "khỏe mạnh", "co_so_du_lieu": settings.DATABASE_NAME}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
