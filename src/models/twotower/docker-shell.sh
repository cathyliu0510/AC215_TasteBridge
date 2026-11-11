#!/bin/bash
# Build the image and open it with the repo's data, runs and secrets mounted (the L13/L15
# docker-shell.sh pattern). Works in Git Bash on Windows, and in bash on macOS/Linux.
#
#   bash src/models/twotower/docker-shell.sh                      interactive shell
#   bash src/models/twotower/docker-shell.sh train --data-dir /data --out /runs \
#        --wandb-key-file /secrets/wandb.key                      one training run, tracked in W&B
#   bash src/models/twotower/docker-shell.sh python -c "import torch; print(torch.cuda.is_available())"
#                                                                 GPU check
#
# Mounts:  <repo>/data -> /data (read-only)   <repo>/runs -> /runs   <repo>/../secrets -> /secrets (read-only)
set -euo pipefail

# Git Bash rewrites anything that looks like a Unix path (/data, /runs) into a Windows path
# (C:/Program Files/Git/data) before docker sees it. This switches that rewrite off.
export MSYS_NO_PATHCONV=1

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../../.." && pwd)"
secrets="$(cd "$repo/.." && pwd)/secrets"
mkdir -p "$repo/runs"

# With the rewrite off, Docker on Windows needs host paths as E:/..., which `pwd -W` gives
# in Git Bash (elsewhere `pwd -W` fails and plain `pwd` is used).
host() { (cd "$1" && (pwd -W 2>/dev/null || pwd)); }

IMAGE="${IMAGE:-twotower:dev}"
TORCH="${TORCH:-cu128}"
docker build --platform linux/amd64 \
  --build-arg TORCH="$TORCH" \
  --build-arg GIT_COMMIT="$(cd "$repo" && git rev-parse --short HEAD 2>/dev/null || echo unknown)" \
  -f "$(host "$here")/Dockerfile" -t "$IMAGE" "$(host "$repo/src")"

gpu=()
if [ "$TORCH" != "cpu" ] && command -v nvidia-smi >/dev/null 2>&1; then gpu=(--gpus all); fi
mounts=(-v "$(host "$repo/data"):/data:ro" -v "$(host "$repo/runs"):/runs")
if [ -d "$secrets" ]; then mounts+=(-v "$(host "$secrets"):/secrets:ro"); fi
tty=(); if [ -t 0 ] && [ -t 1 ]; then tty=(-it); fi

docker run --rm "${tty[@]}" "${gpu[@]}" "${mounts[@]}" \
  -e WANDB_PROJECT="${WANDB_PROJECT:-tastebridge-two-tower}" \
  -e WANDB_ENTITY="${WANDB_ENTITY:-}" \
  -e WANDB_MODE="${WANDB_MODE:-online}" \
  "$IMAGE" "$@"
