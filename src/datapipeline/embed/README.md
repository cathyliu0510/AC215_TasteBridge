# embed: description embeddings + vector index

Part of the TasteBridge data pipeline (`ingest → preprocess → embed / train`). Owner: YiTong.

## What it does (plain terms)

Every book's blurb is turned into a list of 384 numbers, a "coordinate for meaning", by a
small pre-trained AI model. Books whose blurbs talk about similar things end up close
together. The coordinates are saved, put into a searchable index (ChromaDB), and three
example searches are saved as proof that it works. Books without a usable blurb are
described by title, author and shelf tags instead, and marked as such.

Nothing here changes the backend. At MS3 the hybrid model (M1) uses these coordinates
as one of its inputs.

## Run it

```bash
# this stage (it has the compose profile `pipeline`, so a plain `docker compose up`
# starts only the backend and does not build this ~3 GB image)
docker compose run --rm embed

# backend + this stage together
docker compose --profile pipeline up --build

# search the index
docker compose run --rm embed python -m embed.query "a heist with a crew of con artists" --k 5 --genre fantasy
```

Local development (from `src/datapipeline/embed`):

```bash
uv sync
uv run pytest -q                       # fast tests (fake encoder)
uv run pytest -m slow -q               # real model test (~90 MB download once)
uv run pytest --cov --cov-report=term-missing
uv run python scripts/make_synthetic_books.py --out ../../../data/processed/books.parquet  # invented books
```

## Input

`data/processed/books.parquet` from preprocess: `work_id`, `title`, `author`, `description`,
`shelves` (required), plus `has_description`, `year`, `genre` (used when present), and
`data/processed/manifest.json` (`data_version`).

## Output: `data/embeddings/`

| File | What it is |
|---|---|
| `desc_embeddings.npy` | float32 (num_books × 384), unit-length rows |
| `desc_rows.parquet` | row → `work_id`, `text_source` (`description` / `title_shelves`), `n_chars` |
| `meta.json` | model + revision, input hash, upstream `data_version`, git commit, time |
| `chroma/` | ChromaDB index, collection `book_descriptions`, cosine |
| `retrieval_example.json` / `.md` | example queries → top-5 books |
| `run.log` | log of the run |

The folder is replaced only when a run fully succeeds (written to `embeddings.tmp/` first).
It is versioned with DVC (`dvc pull` to get it), never committed to git.

## Settings (environment variables)

| Variable | Default |
|---|---|
| `EMBED_INPUT` | `/data/processed/books.parquet` |
| `EMBED_OUTPUT_DIR` | `/data/embeddings` |
| `EMBED_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` |
| `EMBED_MODEL_REVISION` | `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` |
| `EMBED_BATCH_SIZE` | `64` (whole number ≥ 1, else exit code 1) |
| `EMBED_EXAMPLE_QUERIES` | three built-in queries, separated by `\|` |
| `EMBED_EVIDENCE_EXCERPTS` | off (turn on only once the repo is private) |
| `EMBED_CODE_VERSION` | `git rev-parse HEAD` if available, else `src-sha256:<12 hex>` of the `embed/*.py` code (inside Docker) |

## How it works (for Q&A)

1. `inputs.py` checks the table (columns, duplicates, empty titles) and stops with exit code 1 and a clear message if something is wrong.
2. `texts.py` builds `"{title} by {author}. {description}"`, or `"{title} by {author}. Shelves: …"` when `has_description` is false (the 40-character rule from `preprocess/quality.py`).
3. `encoder.py` runs the pinned model on CPU with `normalize_embeddings=True`, so the dot product equals cosine similarity.
4. `store.py` writes the arrays and builds the Chroma collection (`hnsw` space `cosine`; similarity = 1 − distance; a genre filter also returns books tagged `both`).
5. `query.py` runs the example searches; the CLI always uses the model recorded in `meta.json`.
6. `run.py` writes to a temp folder and renames it into place at the end.

## Troubleshooting

- **Linux host, "cannot write to /data"**: the container runs as uid 1000 and `./data` was created by Docker as root; `sudo chown -R 1000 data`. The input check runs first, so a missing `books.parquet` is still reported as such.
- **`embed.query` says the index is incomplete or `meta.json` lacks a key**: the output folder is from an interrupted or older run; re-run `docker compose run --rm embed`.
- **Windows, "Access is denied" when renaming**: Chroma held files open; `release_chroma()` is called before every rename. Report it if you still see this.
- **Image is several GB**: torch isn't the `+cpu` build; check `[tool.uv.sources]` in `pyproject.toml`.
- **Windows warning "To support symlinks on Windows…"** during local runs: harmless; the Hugging Face model cache copies files instead of linking them.
