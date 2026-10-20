# MS2 evidence: backend API serving the trained B2 model

Owner: **Nikhil** (backend API and deployment). Code: [`src/backend/`](../../../src/backend/). Contract: [`src/backend/SPEC.md`](../../../src/backend/SPEC.md) (v0.4).

This folder shows that the backend container loads the artifact folder written by the modeling pipeline, reports which model and data version it serves, and answers every endpoint.

> **Data used here is synthetic.** The run uses the pipeline's invented Goodreads-shaped data (`synthetic_raw.py`: 600 works, 2,948 readers), so it can be reproduced in minutes without the 3 GB download. The code path is the same as the real-data run: preprocess, B2 ALS export, then the backend container. Real-data model results are in [`docs/ms2/models/`](../models/).

## What ran

```
synthetic_raw.py ─► preprocess.py ─► data/processed/ (data_version gr-db9936ca43ed)
                                          │
                                          ▼
                        evaluation.export (B2 ALS, 128 factors, reg 50, UMAP)
                                          │
                                          ▼
                        data/artifacts/current/  ── mounted read-only ──►  backend container
                        books.json, item_embeddings.npy,                   ARTIFACT_DIR=/artifacts/current
                        coords_2d.npy, meta.json                           http://localhost:9000
```

| Item | Value |
|---|---|
| Model served | `b2-als-gr-db9936ca43ed` ([`artifact-meta.json`](artifact-meta.json)) |
| Data version | `gr-db9936ca43ed`, reported by `/health` and the startup log |
| Pipeline code | `feature/datapipeline` at `b78a57a` |
| Backend code | `feature/backend-ms2` (based on `main` at `5c7e31e`) |
| Container | `python:3.12-slim-bookworm`, non-root, Docker 29 on Colima ([`environment.txt`](environment.txt)) |
| Tests | 77 passed, 99% line coverage ([`pytest.log`](pytest.log)) |

## Files

| File | Shows |
|---|---|
| [`health.png`](health.png), [`docs-page.png`](docs-page.png) | The running container: `/health` and the interactive API docs |
| [`container.log`](container.log) | Startup line naming the model and data version, then one log line per request with status and latency |
| [`requests/`](requests/) | Each request and its full response (input → output) |
| [`artifact-meta.json`](artifact-meta.json) | The `meta.json` the backend loaded: hyperparameters, counts, versions |
| [`environment.txt`](environment.txt) | Versions, image ID and `docker ps` at capture time |
| [`capture_requests.py`](capture_requests.py) | The script that produced `requests/` |

## Results

| # | Request | Status | Result |
|---|---|---|---|
| 01 | `GET /health` | 200 | `b2-als-gr-db9936ca43ed`, data `gr-db9936ca43ed`, 600 books |
| 02 | `GET /books/search` | 200 | Title search for the book picker |
| 03 | `GET /books/{id}` | 200 | One book with year and shelves |
| 04 | `POST /recommend`, `least-misery` | 200 | 5 bridge books (below) |
| 05 | `POST /recommend`, `average` | 200 | 5 books that suit reader B only (below) |
| 06 | `POST /feedback` | 200 | Vote stored with the served `model_version` |
| 07 | Unknown book ID | 404 | Lists every unknown ID |
| 08 | Six favorites for one reader | 422 | "at most 5 items" |

Every request took under 6 ms in the container ([`container.log`](container.log)). The proposal's target is under 0.5 s.

Reader A picked five fantasy works and reader B five mystery works. The two aggregation modes give very different lists:

| Mode | Top book's shelves | `fit_a` (fantasy reader) | `fit_b` (mystery reader) |
|---|---|---|---|
| `least_misery` | epic-fantasy, magic, **mystery**, thriller | 0.49 | 0.46 |
| `average` | psychological-thriller, noir, detective, mystery | 0.16 | 0.90 |

With `average`, all five results are mystery books that reader A barely matches (`fit_a` 0.13 to 0.16). With `least_misery`, every result keeps both readers above 0.28. This is one synthetic example, not a metric. The models README reports that on real data least misery lowers Min-Recall@10. The team should weigh both before changing the API default (SPEC §9, question 5).

## Reproduce

These are the exact steps used for this folder. They need `uv`, Docker, and a checkout of `feature/datapipeline` (for the pipeline code). Run them from the repo root.

1. Make synthetic raw data and preprocess it:

   ```bash
   cd src/datapipeline/preprocess && uv run python synthetic_raw.py --out ../../../data/synthetic/raw --works 600 --users 3000
   ```

   ```bash
   RAW_DIR=../../../data/synthetic/raw PROCESSED_DIR=../../../data/synthetic/processed uv run python preprocess.py
   ```

2. Train B2 ALS and export the backend's artifact folder:

   ```bash
   cd ../../evaluation && uv run python -m evaluation.export --processed ../../data/synthetic/processed --out ../../data/artifacts
   ```

3. Serve it from the repo root:

   ```bash
   docker build -t tastebridge-backend src/backend
   ```

   ```bash
   docker run --rm -p 127.0.0.1:9000:9000 -e ARTIFACT_DIR=/artifacts/current -v "$PWD/data/artifacts:/artifacts:ro" tastebridge-backend
   ```

4. In a second terminal, capture the requests:

   ```bash
   python3 docs/ms2/backend/capture_requests.py http://localhost:9000 data/artifacts/current/books.json docs/ms2/backend/requests
   ```

With real data, `make train` and then `make serve` do steps 2 and 3. On Colima, the mounted folder must be inside your home directory.
