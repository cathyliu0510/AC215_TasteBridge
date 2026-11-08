# M1 two-tower recommender (MS3)

*In plain words.* This folder holds TasteBridge's new learned recommender, called M1:
- it reads a reader's five favourite books and scores every other book in the catalogue;
- it trains on past Goodreads readers, stops when a held-out group of readers stops improving, and is then scored by the team's evaluator next to the existing baselines;
- the whole thing ships as one container image, so the same program runs on a laptop, as a Google Vertex AI training job, and as a pipeline step.

*Technical.* The model has two parts:
- an **item tower**: frozen MiniLM description vector, plus ID and genre embeddings, then a residual MLP, giving unit vectors with d = 128;
- a **reader tower**: a set-Transformer over the favourites (2 pre-LN layers, 4 heads) with a multi-interest readout. The score is `s = τ·logsumexp_j(u_j·z_i/τ)`.

It trains with full-catalogue softmax and multi-positive targets. `TwoTower` implements the team evaluator's `Recommender` protocol, so `src/evaluation` is reused unchanged. Diagram, results and the MS3 plan are in `doc/ms3-two-tower/`, which is local only.

| file | role |
|---|---|
| `twotower/model.py` | `TwoTowerParams`, `ItemTower`, `ReaderTower`, `interest_logits`, the loss |
| `twotower/recommender.py` | `TwoTower`: `fit` (early stopping, checkpoints, `--resume`), `score`, `save`, `load` |
| `twotower/data.py` | `--data-dir` layout (`processed/` + `embeddings/`) and content loading |
| `twotower/tracking.py` | JSONL always, plus W&B when a key is available (env var, key file or Secret Manager) |
| `twotower/train.py` | CLI: train, save, then TEST-evaluate (the lecture-13 `task.py`) |
| `twotower/evaluate.py` | CLI: score a saved model with the team evaluator; writes `metrics.json` |
| `tests/` | tiny synthetic fixtures, invariants, smoke test, resume, save/load, integration |
| `Dockerfile`, `docker-entrypoint.sh`, `docker-shell.sh` | the image and how to run it |

## Run it

All commands below start from the repo root unless stated otherwise.

**Tests and checks** (no data, no GPU, no login; about 5 s):
```bash
cd src/models/twotower
uv sync --extra cpu
uv run --extra cpu pytest -q
uv run --extra cpu ruff check . && uv run --extra cpu mypy
```

**Training in the container, with a GPU** (Git Bash on Windows, or bash on macOS/Linux; about 2 min on an RTX 5090). Needs `data/processed` and `data/embeddings` (`dvc pull`):
```bash
bash src/models/twotower/docker-shell.sh train --data-dir /data --out /runs --tracker off
bash src/models/twotower/docker-shell.sh train --data-dir /data --out /runs --wandb-key-file /secrets/wandb.key
```
- The first run tracks only to `runs/<run-id>/tracking.jsonl`.
- The second also logs to W&B. The key file sits in `../secrets/` next to the repo and is never copied into the image.

**Training with Docker Compose** (CPU, any machine):
```bash
docker compose --profile twotower build
docker compose --profile twotower run --rm twotower train --data-dir /data --out /runs
```

**Re-scoring a saved model:**
```bash
bash src/models/twotower/docker-shell.sh evaluate --data-dir /data --model-dir /runs/<run-id>/model --out /runs/<run-id>-re
```

**Useful flags:**
- `--epochs N`
- `--set field=value`, for any `TwoTowerParams` field, e.g. `--set tau=0.2`
- `--run-id`
- `--no-evaluate`, which stops after saving the model (used by the pipeline step)
- `--resume`, which continues from `runs/<run-id>/checkpoints/last.pt`
- `--tracker auto|wandb|off`
- `--wandb-secret projects/P/secrets/S/versions/latest`, which reads the key from Secret Manager (Vertex)

**What a run writes** (`runs/<run-id>/`):
- `config.json`: every setting, the data version, the git commit, and the torch and CUDA versions;
- `tracking.jsonl`;
- `summary.json`;
- `checkpoints/last.pt`;
- `model/`: `two_tower.pt`, `item_embeddings.npy`, `items.json`, `params.json`;
- `test-eval/`: the evaluator's own output;
- `headline.csv` and `metrics.json`.

> `test-eval/per_pair.csv` contains reader ids. `runs/` is git-ignored. Never commit it or upload it anywhere except the private bucket.

## Which torch build

| `TORCH` build arg / extra | torch | runs on | needs NVIDIA driver |
|---|---|---|---|
| `cu128` (default for training) | 2.11.0 | RTX 50xx (Blackwell), T4, L4, A100 | ≥ 570 |
| `cu130` | 2.14.1 (what the prototype used) | same | ≥ 580 |
| `cpu` (Compose default, serving) | 2.15.0 | any CPU | none |

PyTorch stopped publishing CUDA 12.8 wheels after torch 2.11, hence that version cap. `cu124` would fail on the RTX 5090 with "no kernel image is available", because CUDA 12.4 predates Blackwell.

## Why `MSYS_NO_PATHCONV=1` (Git Bash on Windows)

*In plain words.* Git Bash tries to be helpful: when it sees something that looks like a Linux folder, such as `/data`, it rewrites it into a Windows folder before the program sees it. Docker then gets `C:/Program Files/Git/data` instead of `/data`. That is a folder *inside the container*, so the rewrite breaks the command. Setting `MSYS_NO_PATHCONV=1` tells Git Bash "don't rewrite anything".

*Technical.* MSYS2 converts POSIX-looking arguments to Windows paths when it starts a native Windows executable such as `docker.exe` or `gcloud`.
- Put `MSYS_NO_PATHCONV=1` in front of a single command (a per-command environment variable), or `export` it for a whole script, as `docker-shell.sh` does.
- The host side of `-v` then has to be a real Windows path. `docker-shell.sh` gets it with `pwd -W`, which prints `E:/...`.
- PowerShell and macOS/Linux shells never do this rewrite, so there you drop the prefix.
- One-off form:
  ```bash
  MSYS_NO_PATHCONV=1 docker run --rm --gpus all -v "$(pwd -W)/data:/data:ro" -v "$(pwd -W)/runs:/runs" \
    twotower:dev train --data-dir /data --out /runs --tracker off
  ```

## The Dockerfile, line by line

*In plain words.* A Dockerfile is a recipe for a sealed lunchbox. It starts from a clean, minimal Linux with Python. It installs exactly the listed libraries, copies in our code, and labels the box with which version of the code is inside. Anyone (your laptop, Google's servers, the TF's laptop) who opens the same box gets the same program with the same libraries. Nobody has to "install things" again.

*Technical.* The build context is `src/`, not this folder, because the image also needs `src/evaluation`. `Dockerfile.dockerignore` (Docker reads `<Dockerfile name>.dockerignore` next to the Dockerfile) whitelists only the copied files.

| line | what it does | why |
|---|---|---|
| `# syntax=docker/dockerfile:1` | uses the current Dockerfile syntax | needed for `COPY --chmod` |
| `FROM python:3.12-slim-bookworm` | starts from Debian 12 with Python 3.12, nothing else | same base as the other team images. No CUDA base image is needed: the CUDA torch wheel brings its own CUDA libraries, and only the host's NVIDIA driver is used (`--gpus all` locally; Vertex installs it on GPU machines) |
| `COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/` | copies the `uv` tool from its official image | pinned version, identical to the team's other images |
| `ENV PYTHONUNBUFFERED=1` | prints logs immediately | so Vertex and Cloud Logging show progress live, not at the end |
| `UV_COMPILE_BYTECODE=1` | pre-compiles `.pyc` files at build time | faster start-up of every job |
| `UV_LINK_MODE=copy`, `UV_NO_CACHE=1` | copies files instead of linking, keeps no download cache | avoids link warnings across Docker layers; keeps the image smaller |
| `PATH="/app/.venv/bin:$PATH"` | makes the project's virtual environment the default `python` | no `uv run` / `source activate` needed inside the container |
| `PYTHONPATH="/app:/app/evaluation"` | lets Python import `twotower` and the team's `evaluation` | `evaluation` is not an installable package, so it is put on the path |
| `ARG RUN_AS=app` | build-time choice of the user the container runs as | default non-root; `--build-arg RUN_AS=root` is the fallback if a cloud storage mount refuses writes |
| `RUN useradd --create-home --uid 1000 app` | creates that unprivileged user | security: code in the container cannot change the system |
| `WORKDIR /app` | all later paths are relative to `/app` | |
| `ARG TORCH=cu128` | build-time choice of torch build | see "Which torch build" |
| `COPY ...pyproject.toml ...uv.lock ...python-version ./` | copies only the dependency lists | Docker caches each step; code edits then don't re-download the multi-GB torch layer |
| `RUN uv sync --frozen --no-dev --no-install-project --extra ${TORCH}` | installs exactly the versions in `uv.lock` | `--frozen`: fail rather than silently change versions (reproducibility); `--no-dev`: no pytest/ruff/mypy in the image; `--no-install-project`: only libraries, not the code (it is copied next); `--extra`: the chosen torch build |
| `COPY evaluation/evaluation ./evaluation/evaluation` | the team evaluator, unchanged | M1 is scored by exactly the same code as B0/B1/B2 |
| `COPY models/twotower/twotower ./twotower` | our package | last, because it changes most often |
| `COPY --chmod=755 ...docker-entrypoint.sh /docker-entrypoint.sh` | the start-up script, made executable | `--chmod` avoids a Windows checkout losing the executable bit |
| `ARG GIT_COMMIT=unknown` / `ENV GIT_COMMIT=... TORCH_BUILD=...` | stamps the commit and torch build into the image | `train.py` writes them into every run's `config.json` and W&B config, so a result can be traced to code |
| `USER ${RUN_AS}` | drops root for everything that runs | |
| `ENTRYPOINT ["/docker-entrypoint.sh"]` | every `docker run` goes through the script | no args gives a shell; `train …` / `evaluate …` give the Python CLIs; anything else is run as-is (lecture 15's "callable container") |

**The lecture-13 file names, mapped to this package:**

| lecture 13 | here |
|---|---|
| `trainer/task.py` | `twotower/train.py` |
| `docker-shell.sh` | `docker-shell.sh` |
| `docker-entrypoint.sh` | `docker-entrypoint.sh` |
| `cli.sh` / `cli.py` (Vertex job submission) | `deploy/twotower/` (MS3 sections 6.3 and 7) |
