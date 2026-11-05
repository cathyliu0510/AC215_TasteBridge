# OFFLINE, UNEXECUTED MS3 CANDIDATE. Build context: repository root.
# Building/publishing this image and running a job are separate operator actions.
FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/
ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_CACHE=1 \
    PATH="/app/source/src/evaluation/.venv/bin:$PATH" NUMBA_CACHE_DIR=/tmp/numba-cache \
    WANDB_MODE=disabled
RUN useradd --create-home --uid 1000 app
WORKDIR /app/source/src/evaluation
COPY src/evaluation/pyproject.toml src/evaluation/uv.lock src/evaluation/.python-version src/evaluation/Dockerfile ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src/evaluation/evaluation/*.py ./evaluation/
COPY deploy/vertex-ms3/workflow.py deploy/vertex-ms3/Dockerfile /app/source/deploy/vertex-ms3/
WORKDIR /app/source
USER app
ENTRYPOINT ["python", "/app/source/deploy/vertex-ms3/workflow.py"]
CMD ["--help"]
