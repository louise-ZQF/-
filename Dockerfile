FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

# 系统依赖（tesseract 用于 OCR 截图导入）
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖（利用缓存）
COPY requirements.txt requirements-deploy.txt ./
RUN pip install -r requirements-deploy.txt

COPY . .

EXPOSE 8000

# $PORT 由多数平台注入；本地默认 8000
CMD ["sh", "-c", "gunicorn -b 0.0.0.0:${PORT:-8000} -w 2 --timeout 120 wsgi:app"]
