#!/bin/bash
# Callable container (lecture 15, s.28): the same image is a dev shell, a training job and a
# pipeline step, depending only on its arguments.
#   (no args)              -> interactive bash (use `docker run -it ...`)
#   train    [flags...]    -> python -m twotower.train    [flags...]
#   evaluate [flags...]    -> python -m twotower.evaluate [flags...]
#   anything else          -> run it as a command, e.g. `pytest` or `python -c ...`
set -euo pipefail

case "${1:-}" in
  "")
    exec /bin/bash
    ;;
  train|evaluate)
    cmd="$1"
    shift
    exec python -m "twotower.${cmd}" "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
