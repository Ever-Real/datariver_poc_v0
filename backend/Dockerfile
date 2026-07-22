# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.9.17@sha256:5cb6b54d2bc3fe2eb9a8483db958a0b9eebf9edff68adedb369df8e7b98711a2 AS uv

FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    DATARIVER_SEED_ROOT=/app/seed

COPY --from=uv /uv /uvx /usr/local/bin/

RUN apt-get update \
    && apt-get upgrade --yes \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 datariver \
    && useradd --system --uid 10001 --gid datariver --home-dir /app datariver

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY backend ./backend
COPY seed ./seed

RUN uv sync --frozen --no-dev --no-editable \
    && chown -R datariver:datariver /app

USER 10001:10001
EXPOSE 8000

CMD ["/app/.venv/bin/uvicorn", "datariver.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
