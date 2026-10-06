import uvicorn
from app.config import settings

if __name__ == "__main__":
    print(f"Starting Music App Backend on http://{settings.HOST}:{settings.PORT}")
    print(f"Interactive Swagger Documentation: http://localhost:{settings.PORT}/docs")
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
