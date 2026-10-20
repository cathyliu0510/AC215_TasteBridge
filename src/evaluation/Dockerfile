# TasteBridge evaluation: offline pair simulation (Min-Recall@10, NDCG@10, coverage)
FROM python:3.12-slim-bookworm

# uv for dependency management (same pinned version as the backend)
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:$PATH" \
    NUMBA_CACHE_DIR=/tmp/numba-cache

RUN useradd --create-home --uid 1000 app
WORKDIR /app

# Dependencies first, so this layer is cached when only code changes
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY evaluation ./evaluation
RUN mkdir -p /app/results /app/data /app/artifacts && chown app:app /app/results /app/data /app/artifacts

USER app

# Same image also trains + exports B2 for the backend:
#   python -m evaluation.export --processed /app/processed --out /app/artifacts   (compose service `train`)
# Default: a full run on synthetic data, so the container works without a download.
# Real data: mount it at /app/data and override the command (see README).
ENTRYPOINT ["python", "-m", "evaluation.run"]
CMD ["--synthetic", "--out", "/app/results", "--favorite-counts", "1,2,3,4,5"]
