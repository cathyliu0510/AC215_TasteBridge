# TasteBridge ingest stage: download raw Goodreads files into /data/raw
FROM python:3.12-slim-bookworm

# uv for dependency management (same pinned version as the other services)
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:$PATH"

# Run as a non-root user (uid 1000 matches the other pipeline stages)
RUN useradd --create-home --uid 1000 app
WORKDIR /app

# Dependencies first so this layer is cached when only code changes
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY ingest.py ./
USER app

# Settings come from environment variables (see README): RAW_DIR, INGEST_SAMPLE_LINES, ...
CMD ["python", "ingest.py"]
