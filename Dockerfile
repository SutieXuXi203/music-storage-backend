# Base Python Image
FROM python:3.11-slim

# Thiết lập biến môi trường
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

# Cài đặt ffmpeg (bắt buộc cho yt-dlp trích xuất âm thanh mp3 và cover art)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Thiết lập thư mục làm việc
WORKDIR /app

# Copy requirements và cài đặt dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ mã nguồn ứng dụng
COPY . .

# Tạo thư mục downloads tạm thời
RUN mkdir -p /app/downloads

# Expose port
EXPOSE 8000

# Chạy FastAPI với Uvicorn
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
