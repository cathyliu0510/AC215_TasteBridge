# syntax=docker/dockerfile:1
# TasteBridge M1 two-tower: one image for local training, Vertex AI CustomJobs and pipeline steps.
#
# Build from the repo root. The build context is src/ (not this folder) because the image also
# needs the team evaluator in src/evaluation:
#   docker build --platform linux/amd64 -f src/models/twotower/Dockerfile -t twotower:dev src
# Run:
#   docker run --rm --gpus all -v <repo>/data:/data:ro -v <repo>/runs:/runs twotower:dev \
#       train --data-dir /data --out /runs
# A line-by-line explanation is in README.md, section "The Dockerfile, line by line".
FROM python:3.12-slim-bookworm

# uv for dependency management (same pinned version as the other team images)
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app:/app/evaluation"

# Run as a non-root user. RUN_AS=root is the escape hatch if a cloud mount refuses writes.
ARG RUN_AS=app
RUN useradd --create-home --uid 1000 app
WORKDIR /app

# Dependencies first, so this (large) layer is cached when only code changes.
# TORCH picks the torch build: cu128 (GPU, default), cu130 (GPU, newer driver) or cpu.
ARG TORCH=cu128
COPY models/twotower/pyproject.toml models/twotower/uv.lock models/twotower/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project --extra ${TORCH}

# Code: the team evaluator (unchanged) and the two-tower package
COPY evaluation/evaluation ./evaluation/evaluation
COPY models/twotower/twotower ./twotower
COPY --chmod=755 models/twotower/docker-entrypoint.sh /docker-entrypoint.sh

# Provenance: which commit and which torch build this image holds (logged into every run's config)
ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=${GIT_COMMIT} \
    TORCH_BUILD=${TORCH}

USER ${RUN_AS}

# No arguments -> a shell; `train ...` / `evaluate ...` -> python -m twotower.<cmd> ... (L15 s.28)
ENTRYPOINT ["/docker-entrypoint.sh"]
