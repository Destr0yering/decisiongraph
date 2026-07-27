FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DECISIONGRAPH_DB_PATH=/tmp/decisiongraph.db \
    DATAHUB_MCP_ENABLED=false

WORKDIR /app

COPY backend /app/backend
RUN python -m pip install --no-cache-dir /app/backend

WORKDIR /app/backend

EXPOSE 8000

CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
