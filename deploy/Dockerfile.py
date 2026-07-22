# Ảnh Python dùng CHUNG cho 7 dịch vụ Flask (bridge + 6 kênh).
# docker-compose chạy cùng ảnh này với command khác nhau (python -m app.main_X).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# rclone: cho service `backup` đẩy bản sao OFFSITE (BACKUP_RCLONE_REMOTE). Ảnh
# dùng chung nên chỉ cài 1 lần; các service khác không dùng cũng không sao.
RUN apt-get update && apt-get install -y --no-install-recommends rclone \
    && rm -rf /var/lib/apt/lists/*

# Cài phụ thuộc trước (tận dụng cache layer khi chỉ đổi code).
# Ưu tiên requirements.lock (pin cứng, build tái lập được); fallback requirements.txt.
# Wildcard requirements.loc[k] để COPY không fail nếu lock chưa tồn tại.
COPY requirements.txt requirements.loc[k] ./
RUN pip install --upgrade pip && \
    if [ -f requirements.lock ]; then pip install -r requirements.lock; \
    else pip install -r requirements.txt; fi

# Copy mã nguồn (data/ media/ bị .dockerignore loại — dùng volume lúc chạy)
COPY app/ ./app/
# Script quản trị chạy tay trong container (vd: python -m scripts.create_admin)
COPY scripts/ ./scripts/

# Thư mục dữ liệu + media dùng volume (khai trong compose)
RUN mkdir -p /app/data /app/media

# Mặc định chạy bridge; compose override command cho từng dịch vụ
CMD ["python", "-m", "app.main_node"]
