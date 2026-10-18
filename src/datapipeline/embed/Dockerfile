# TasteBridge embed stage: description embeddings + ChromaDB index
FROM python:3.12-slim-bookworm

# uv for dependency management (pinned, copied from the official image)
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:$PATH" \
    HF_HOME=/models

# Run as a non-root user
RUN useradd --create-home --uid 1000 app
WORKDIR /app

# Install dependencies first so this layer is cached when only code changes
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

# Bake the pinned model into the image so runs are offline and reproducible
ARG EMBED_MODEL=sentence-transformers/all-MiniLM-L6-v2
ARG EMBED_MODEL_REVISION=1110a243fdf4706b3f48f1d95db1a4f5529b4d41
RUN python -c "from sentence_transformers import SentenceTransformer as S; S('${EMBED_MODEL}', revision='${EMBED_MODEL_REVISION}', device='cpu')" \
    && chown -R app:app /models

COPY embed ./embed

ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

USER app
CMD ["python", "-m", "embed.run"]
