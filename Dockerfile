FROM python:3.11-slim

WORKDIR /app

# システム依存（pypdf/openpyxl/python-pptxは純Pythonなので軽量で済む）
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

# 依存だけ先にコピーしてインストール（キャッシュ効率化）
COPY pyproject.toml ./
COPY app/__init__.py app/__init__.py
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -e ".[dev]"

# 本体コピー
COPY app/ app/
COPY scripts/ scripts/
COPY tests/ tests/
COPY data/ data/

ENV DEMO_MODE=1 \
    FAQ_MASTER_DIR=/app/data/demo_faq \
    SESSION_SECRET=demo-secret \
    ORG_NAME="貴社" \
    ASSISTANT_ROLE="社内ヘルプデスク" \
    HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000

# 起動前にテストを走らせる（失敗したらコンテナ起動しない）
CMD ["sh", "-c", "pytest -q --tb=short && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
