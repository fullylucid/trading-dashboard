FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y gcc ffmpeg && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY backend /app/backend
COPY hermes /app/hermes
ENV PYTHONPATH=/app:/app/backend
WORKDIR /app/backend
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=5)"
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
