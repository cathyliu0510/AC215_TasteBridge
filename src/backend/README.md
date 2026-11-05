# TasteBridge API service

FastAPI service that returns "bridge books" for two readers. It serves a model
exported by the modeling pipeline. It never trains one. The full contract is in
[SPEC.md](SPEC.md).

## Run it

**With Docker (one command, from the repo root):**

```bash
docker compose up --build
```

If `docker compose` isn't recognized, use `docker-compose` (the standalone binary) in place of `docker compose` in every command below, or install the Compose plugin.

Stop it:

```bash
docker compose down
```

Feedback votes persist in the named volume `feedback`; to wipe them:

```bash
docker compose down -v
```

**Locally with uv (from `src/backend/`):**

```bash
uv sync                                          # create .venv from uv.lock
uv run uvicorn app.main:app --reload --port 9000
```

Open http://localhost:9000/docs for interactive API docs.

## Try it

```bash
curl http://localhost:9000/health
curl "http://localhost:9000/books/search?q=mist"
curl http://localhost:9000/books/w_1001
curl -X POST http://localhost:9000/recommend -H "Content-Type: application/json" \
  -d '{"reader_a":["w_1001","w_1002","w_1003","w_1004","w_1005"],
       "reader_b":["w_2001","w_2002","w_2003","w_2004","w_2005"]}'
curl -X POST http://localhost:9000/feedback -H "Content-Type: application/json" \
  -d '{"book_id":"w_3002","vote":"would_read","model_version":"sample-shelf-toy-v1"}'
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Service status and loaded model version |
| GET | `/books/search?q=&limit=` | Title/author search for the picker |
| GET | `/books/{book_id}` | One book's details |
| POST | `/recommend` | Ranked bridge books, reasons and galaxy coordinates |
| POST | `/feedback` | Anonymous "would read / not for us" vote |

Search ignores accents and punctuation while preserving catalogue display text.
Catalogue search keys are built once at model startup; user queries are not cached.
URL-encode book IDs in detail paths. Feedback must use the loaded model version;
a stale version returns 409 without recording a vote, so refresh recommendations before retrying.

`/health` and `/recommend` also return `artifact_fingerprint`, a SHA256 identity of
the four files loaded at startup. Reconcile it together with `model_version` from
the recommendation response, which identifies the model that actually answered
the request. Same-version exports can have different fingerprints. Feedback may
include that fingerprint for an additional check; older requests still work.
See [the artifact contract](SPEC.md#5-model-artifact-contract-hand-off-from-modeling--backend)
for the exact hashing formula. The detail path reserves `search` and cannot
reliably represent HTTP dot segments (`.` and `..`); numeric catalogue IDs work.

## Configuration

Settings are read from environment variables. See [.env.example](.env.example).

| Variable | Default | Meaning |
|---|---|---|
| `ARTIFACT_DIR` | `sample_artifacts/` | Model artifact folder (SPEC.md §5) |
| `FEEDBACK_PATH` | `feedback/feedback.jsonl` | Where votes are appended |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins |
| `PORT` | `9000` | Container port (Cloud Run sets this) |

The server refuses to start if the artifact folder is missing files or the row
counts don't match.

## Serve the trained model

By default the API serves the toy sample artifacts. The data pipeline's `train`
stage (`src/evaluation/evaluation/export.py`, B2 ALS) writes a real artifact
folder to `data/artifacts/current/` at the repo root. To serve it, from the repo root:

```bash
make train
```

```bash
make serve
```

`make serve` mounts `data/artifacts` into the container and sets
`ARTIFACT_DIR=/artifacts/current`. These targets need the pipeline's `Makefile`
and compose services (Cathy's `feature/datapipeline` branch) and Docker Compose v2
(`docker compose`).

Without Docker, from `src/backend/`:

```bash
ARTIFACT_DIR=../../data/artifacts/current uv run uvicorn app.main:app --port 9000
```

Check which model and data snapshot are loaded:

```bash
curl http://localhost:9000/health
```

The output looks like this (the versions and book count depend on the run):

```json
{"status":"ok","model_version":"b2-als-gr-317756d1a1ad","data_version":"gr-317756d1a1ad","num_books":5000}
```

`data_version` comes from `meta.json`. It ties every answer to the preprocessed
dataset (`data/processed/manifest.json`, tracked with DVC). MS2 evidence is in
[`docs/ms2/backend/`](../../docs/ms2/backend/).

## Sample artifacts

`sample_artifacts/` holds 52 hand-picked books (IDs `w_1xxx` fantasy, `w_2xxx`
mystery, `w_3xxx` in between). The embeddings are **toy** vectors built from
shelf tags. They are not a trained model. To regenerate them after editing
`books.json`:

```bash
uv run python scripts/make_sample_artifacts.py
```

## Tests

```bash
uv run pytest --cov --cov-report=term-missing
```

## Layout

```
app/
  main.py               app factory, startup loading, CORS, request logging
  config.py             environment settings
  artifacts.py          load + validate the model artifact folder
  schemas.py            Pydantic request/response models (the JSON contract)
  search.py             catalogue search
  recommender.py        taste vectors, fit scores, aggregation, top-k
  explanations.py       metadata-only reason text
  recommend_service.py  assembles the /recommend response
  feedback.py           JSON-lines vote store
  routers/              one thin module per endpoint group
sample_artifacts/       toy artifact set for development
scripts/                sample-artifact generator
tests/                  pytest suite
```
