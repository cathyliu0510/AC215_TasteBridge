#!/bin/bash
# Pipeline entry for the ALS branch of deploy/twotower/pipeline.py (same interface as the M1 image).
#   (no args)        -> interactive bash
#   train [flags...] -> python -m evaluation.pipeline_train [flags...]   (Vertex CustomJob step)
#   anything else    -> run it as a command
# The image's default ENTRYPOINT (python -m evaluation.run, used by docker compose) is unchanged;
# the pipeline overrides it with `command: /docker-entrypoint.sh`.
set -euo pipefail

case "${1:-}" in
  "")
    exec /bin/bash
    ;;
  train)
    shift
    exec python -m evaluation.pipeline_train "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
