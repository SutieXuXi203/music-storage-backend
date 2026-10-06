# Base Python Image
FROM python:3.11-slim

# Copy Deno binary (official recommended JS runtime for yt-dlp EJS challenge solving)
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

# Thiết lập biến môi trường
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

# Cài đặt ffmpeg và các gói cần thiết
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    ca-certificates \
    nodejs \
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
