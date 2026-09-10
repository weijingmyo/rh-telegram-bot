FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATABASE_PATH=/app/data/bot.db

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml README.md ./
COPY src ./src
COPY tests ./tests

RUN pip install --upgrade pip && pip install -e ".[dev]" \
    && npm install -g gmgn-cli || true

RUN mkdir -p /app/data

VOLUME ["/app/data"]

EXPOSE 8080

CMD ["python", "-m", "src"]
