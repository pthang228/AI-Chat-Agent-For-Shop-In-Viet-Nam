# Ảnh Python dùng CHUNG cho 7 dịch vụ Flask (bridge + 6 kênh).
# docker-compose chạy cùng ảnh này với command khác nhau (python -m app.main_X).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Cài phụ thuộc trước (tận dụng cache layer khi chỉ đổi code)
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy mã nguồn (data/ media/ bị .dockerignore loại — dùng volume lúc chạy)
COPY app/ ./app/

# Thư mục dữ liệu + media dùng volume (khai trong compose)
RUN mkdir -p /app/data /app/media

# Mặc định chạy bridge; compose override command cho từng dịch vụ
CMD ["python", "-m", "app.main_node"]
