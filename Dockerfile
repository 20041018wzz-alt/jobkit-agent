# wzz-agent 生产镜像：非 root 运行 + 内置健康检查
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8100 \
    WZZ_KNOWLEDGE_DIR=/app/data/knowledge

WORKDIR /app

# 依赖先装，利用构建缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 非 root 用户运行（安全基线）
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8100

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8100/health', timeout=2).status==200 else 1)"

CMD ["python", "chat_service.py"]
