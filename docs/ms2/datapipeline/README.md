# MS2 data pipeline: ingest → preprocess → embed / train / evaluation

Owners: **Cathy** (ingest, preprocess, compose/Makefile), **YiTong** (`quality.py`, embed, DVC), **Anhad** (evaluation).

```
UCSD Goodreads ──► ingest ──► data/raw/ ──► preprocess ──► data/processed/ ──┬──► embed       ──► data/embeddings/
 (5 .json.gz)     (Cathy)    + manifest     (Cathy +      books.parquet      │    (YiTong)
                                            YiTong's      interactions.parquet
                                            quality.py)   manifest.json      └──► evaluation  ──► src/evaluation/results/
                                                          (data_version)          (Anhad)
                                                                             └──► train (B2)  ──► data/artifacts/current ──► backend API
                                                                                  (Cathy)         (SPEC §5 folder)           (Nikhil)
```

Models, hyperparameters and early results: [docs/ms2/models/README.md](../models/README.md).

Every stage is its own container (Dockerfile + `pyproject.toml` + `uv.lock`, Python 3.12, non-root user), reads and writes `./data`, and exits when done.

## Run it (from the repo root)

Requirements: Docker Desktop running. `uv` and `make` only for tests and the Makefile.

| Command | What it does | Time |
|---|---|---|
| `make sample` | **Demo run.** Ingest keeps the first 200k lines of each interaction file (metadata in full), then preprocess → embed → train → evaluation | ~10–20 min (first build + ~0.5 GB download) |
| `make pipeline` | **Full run** on all ~80M interactions | ~1 h (several GB download, then ~10–20 min preprocess) |
| `make data` | Ingest + preprocess only (skips the 3 GB embed image) | ~5 min on the sample |
| `make demo` | **Fully offline:** invented Goodreads-shaped data in `data/synthetic/` (never touches `data/raw`) → preprocess → evaluation | ~2 min |
| `make evaluate` | Evaluation of B0, B1, B2 on whatever is in `data/processed/` | ~1–2 min |
| `make train` | Train B2 ALS on `data/processed/`, export `data/artifacts/current/` for the backend | ~1–2 min |
| `make serve` | Backend API on http://localhost:9000/docs serving the trained model | — |
| `make app` | Frontend (http://localhost:4176) + backend with the trained model | — |
| `make test` | Unit tests for ingest and preprocess | seconds |
| `make dvc-push` | `dvc add` raw/processed/embeddings and push to `gs://tastebridge-dvc` | depends on size |

Without `make`, the same one-command run is:

```bash
INGEST_SAMPLE_LINES=200000 docker compose --profile pipeline run --rm embed   # ingest -> preprocess -> embed
```

`depends_on: service_completed_successfully` makes compose run ingest, then preprocess, then embed, each starting only after the previous one exits successfully.

Plain `docker compose up --build` still starts only the backend, as before.

## Real-data run (Oct 16, full files)

| | Sample (`make data`, 200k lines/file) | Full (`INGEST_SAMPLE_LINES=0 make data`) |
|---|---|---|
| Interaction lines read | 400,000 | **80,197,446** |
| Editions → works | 470,776 → 208,416 | 470,776 → 208,416 |
| Catalogue works | 5,000 | 5,000 |
| Users kept | 2,407 | **9,896** (of 709,000 touching the catalogue) |
| Interactions kept (likes) | 128,153 (88,388) | **499,915 (349,962)** |
| Users with ≥15 likes | 1,544 | 6,114 |
| `data_version` | `gr-80911e8f118a` | **`gr-317756d1a1ad`** |
| Preprocess time (MacBook, Docker) | ~1.5 min | ~6 min |

Running the same input on two machines gave the same `data_version` (`gr-db9936ca43ed` on the synthetic demo data), so the stage is reproducible.

## Stage 1: ingest (`src/datapipeline/ingest/`)

Downloads five files from `https://mcauleylab.ucsd.edu/public_datasets/gdrive/goodreads/`:

| Local name | Source | Why |
|---|---|---|
| `books_fantasy.json.gz` | `byGenre/goodreads_books_fantasy_paranormal.json.gz` | edition metadata, `work_id`, shelves, descriptions |
| `books_mystery.json.gz` | `byGenre/goodreads_books_mystery_thriller_crime.json.gz` | same for mystery |
| `inter_fantasy.json.gz` | `byGenre/goodreads_interactions_fantasy_paranormal.json.gz` | user × edition ratings |
| `inter_mystery.json.gz` | `byGenre/goodreads_interactions_mystery_thriller_crime.json.gz` | same for mystery |
| `authors.json.gz` | `goodreads_book_authors.json.gz` | author names (metadata only has IDs) |

| Variable | Default | Meaning |
|---|---|---|
| `INGEST_SAMPLE_LINES` | `0` | `0` = full files; `N` = stream only the first N lines of each **interaction** file |
| `RAW_DIR` | `/data/raw` | output folder |
| `INGEST_BASE_URL` | UCSD URL | change for a mirror; `file://` works for offline tests |
| `INGEST_FORCE` | `0` | `1` = re-download even if unchanged |

Writes `data/raw/manifest.json` (URL, size, sha256, line cap per file). Reruns skip files that match the manifest. Downloads go to `.part` files and are renamed only when complete.

## Stage 2: preprocess (`src/datapipeline/preprocess/`)

1. **Editions → works.** Every `book_id` maps to its `work_id`. This prevents leakage: the same book in two editions can't land in both train and test.
2. **Catalogue.** Count likes (rating ≥ 4) per work over both genres; keep the **5,000 most liked**.
3. **Interactions.** One row per (user, work), with the best rating over editions. Rows neither read nor rated (bare to-read shelves) are dropped. Users need **≥ 5 likes**. Whole users are sampled (seed 42) down to **≤ 500,000 rows**.
4. **Books.** Title and author come from the most-rated edition; year is the earliest edition; shelves are summed over editions. YiTong's `add_quality_flags()` cleans descriptions and shelves (removes `to-read`, `favorites`, …) and adds `has_description` / `description_issue`.
5. **Versioning.** Files are written to `processed.tmp/`, hashed, and swapped into place. The hash of the files plus the settings gives the **`data_version`** (e.g. `gr-37c641fd8a07`).

| Variable | Default |
|---|---|
| `PREPROCESS_MAX_WORKS` | `5000` |
| `PREPROCESS_MAX_INTERACTIONS` | `500000` |
| `PREPROCESS_MIN_USER_LIKES` | `5` |
| `PREPROCESS_SEED` | `42` |

**Output contract** (`data/processed/`):

| File | Columns | Used by |
|---|---|---|
| `books.parquet` | `work_id` (str), `title`, `author`, `author_id`, `year` (nullable), `description`, `description_issue`, `has_description`, `shelves` (list), `genre` (`fantasy`/`mystery`/`both`), `genres` (list), `n_editions`, `n_likes`, `n_ratings` | embed, evaluation, model export → backend |
| `interactions.parquet` | `user_id` (str), `work_id` (str), `rating` (0–5), `is_read` | evaluation, B2 training |
| `manifest.json` | `data_version`, `params`, `counts`, `quality`, `inputs` (the ingest manifest), `code_version`, file sha256 | every later stage records `data_version` |

The 80/10/10 user split is done **inside the evaluation package** with a fixed seed, so every model is scored on the same users.

## Data versioning: which data each container used

| Stage | Records |
|---|---|
| ingest | `data/raw/manifest.json`: sha256 + line cap of each raw file |
| preprocess | `data/processed/manifest.json`: **`data_version`**, settings, counts, the ingest manifest, code version |
| embed | `data/embeddings/meta.json`: upstream `data_version`, model + revision |
| evaluation | `results/<run>/config.json`: sha256 of the input files (and DVC md5 when `.dvc` files exist) |
| DVC | `data/raw.dvc`, `data/processed.dvc`, `data/embeddings.dvc` in git point to the exact data in `gs://tastebridge-dvc` |

To version a run:

```bash
gcloud auth application-default login   # once per computer
make dvc-push                           # dvc add + dvc push
git add data/*.dvc && git commit -m "data: <data_version>"
```

Teammates get the same data with `dvc pull`.

## Tests

```bash
make test        # ingest: 7 tests; preprocess: 121 tests (incl. YiTong's quality tests)
```

The preprocess tests run the whole stage on invented Goodreads-shaped data (`synthetic_raw.py`). They check:
- the contract columns that embed and evaluation require
- edition merging (two editions → one row, best rating)
- the caps, and that the same input gives the same `data_version`
- that reruns leave no temp folders behind

## Known limitations

- **No registry access when drafting.** The Docker images were not built during drafting. Each container's exact file set was run with `uv sync --frozen --no-dev` and the same environment variables. Run `make sample` once on a laptop to record the Docker evidence.
- **Sample mode is a prefix,** not a random sample: the first N lines of each interaction file. Good for a demo; use `make pipeline` for reported results.
- **Fewer than 5,000 works:** after the user filter and cap, a few catalogue works can be left with no interactions. They are dropped, so the catalogue can come out slightly under 5,000 (`counts.catalogue_works`).
- **2017 data:** the dataset was collected in 2017, so newer books are absent.
