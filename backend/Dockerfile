
FROM ghcr.io/astral-sh/uv:0.9.17@sha256:5cb6b54d2bc3fe2eb9a8483db958a0b9eebf9edff68adedb369df8e7b98711a2 AS uv

FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_CACHE_DIR=/uv-cache \
    DATARIVER_SEED_ROOT=/app/seed

COPY --from=uv /uv /uvx /usr/local/bin/

RUN groupadd --system --gid 10001 datariver \
    && useradd --system --uid 10001 --gid datariver --home-dir /app datariver \
    && install -d -o datariver -g datariver -m 0700 /var/spool/datariver-knowledge

# Offline uv cache: pre-downloaded wheels for closed-network builds.
# The tar is extracted once per layer; if the lockfile has not changed since the
# cache was built the sync step runs fully offline (--offline flag).
COPY offline_python/ /offline_python/
RUN set -eux; \
    CACHE_TAR=$(find /offline_python -maxdepth 1 -name 'datariver-uv-cache-linux-x86_64-*.tar.gz' | sort | tail -1); \
    if [ -n "$CACHE_TAR" ]; then \
        mkdir -p "$UV_CACHE_DIR"; \
        tar -xzf "$CACHE_TAR" -C "$UV_CACHE_DIR" --strip-components=1; \
    fi

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY backend ./backend
COPY seed ./seed

# Strictly enforce offline sync. If it fails, the cache is incomplete.
RUN uv sync --frozen --no-dev --no-editable --offline \
    && chown -R datariver:datariver /app

USER 10001:10001
EXPOSE 8000

CMD ["/app/.venv/bin/uvicorn", "datariver.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
