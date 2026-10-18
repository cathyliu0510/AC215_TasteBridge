# Data pipeline: quality checks + embed stage — notes for the team

Owner: YiTong. Branch `feature/datapipeline-embed`, based on `main` after PRs #1 and #2 were merged.
All data used here is **synthetic** (8 invented books); no Goodreads data is in git.

## What this adds

| Path | What it is |
|---|---|
| `src/datapipeline/preprocess/quality.py` | `add_quality_flags(books)` for Cathy's preprocess: cleans descriptions and shelf tags, adds `has_description` and `description_issue`, returns a summary for `manifest.json["quality"]` |
| `src/datapipeline/embed/` | The embed stage (own `pyproject.toml`, `uv.lock`, `Dockerfile`, tests): `books.parquet` → 384-number vector per book → ChromaDB index + retrieval examples |
| `docker-compose.yml` | New `embed` service, **opt-in** via the `pipeline` profile (see below); the backend service is unchanged |
| `.dvc/`, `.dvcignore`, `.gitignore` | DVC initialised with remote `gs://tastebridge-dvc`; git ignores `data/raw/`, `data/interim/`, `data/processed/`, `data/embeddings/` by name, so the `data/*.dvc` tickets stay visible to both git and DVC |
| `docs/ms2/embed/` | MS2 evidence from the synthetic run (`retrieval_example.md`, `run.log`, `meta.json`) |

How to run and test it: `src/datapipeline/embed/README.md`.

## Compatibility with the current `main`

- **Backend (PR #2):** not modified. Its 71 tests pass on this branch. `docker compose up --build` still starts only the backend, healthy, on port 9000.
- **Frontend / `compose.integration.yml` (PR #1):** not touched.
- **Artifact contract (backend `SPEC.md` §5):** not changed. The embed output (`data/embeddings/desc_embeddings.npy`, 384 dims) is an input for the MS3 hybrid model. It does not replace the backend's `item_embeddings.npy`.
- **Compose profile:** `embed` has `profiles: ["pipeline"]`. A plain `docker compose up` doesn't build its ~3 GB image, and doesn't fail when `data/processed/books.parquet` is absent. Run it with `docker compose run --rm embed`, or `docker compose --profile pipeline up --build` for both services.

## Issues found in review and fixed on this branch (each has a test)

1. **Missing quality step.** If preprocess skips `add_quality_flags`, the embed stage now stops with a clear message instead of embedding raw `{name, count}` shelf records as text.
2. **Interrupted output swap.** If the final rename fails, the previous `data/embeddings/` is restored. A leftover `.old` folder from an interrupted run is restored, not deleted.
3. **Locked output folder.** A locked folder (Windows, a query or notebook still open) now gives "close the program and re-run" with exit code 1, not a traceback.
4. **Incomplete index.** `python -m embed.query` on an incomplete index (folder without a collection, or `meta.json` missing keys) prints a one-line error with exit code 1.
5. **Unwritable `./data` on Linux.** The input is checked before anything is written, so a missing `books.parquet` is reported as such. An unwritable `./data`, typically root-owned because Docker created it, gives the exact `chown` command.
6. **`EMBED_BATCH_SIZE`.** It's validated: a whole number of at least 1, otherwise exit code 1 with a message.
7. **`code_version` in Docker.** It was `null` inside Docker, which has no git. It now falls back to `src-sha256:<12 hex>`, a fingerprint of the `embed/*.py` code.
8. **Contract column names.** `add_quality_flags(..., shelves_col="popular_shelves")` now writes its cleaned output to the contract columns `shelves` / `description`. The raw columns are left for preprocess to drop.
9. **Shelf lists saved as text.** These are parsed, whether JSON or Python repr. A bare name inside a list of `{name, count}` records has no count. It's now counted as unknown instead of as infinitely popular.

## Known limitations (not fixed, by decision)

- **Evidence is synthetic.** `docs/ms2/embed/` was produced from the 8 invented books. Regenerate it from Cathy's preprocess sample before submission.
- **DVC is configured and rehearsed, not pushed yet.** The bucket `gs://tastebridge-dvc` exists and is private. The full cycle (`dvc add` → `dvc push` → delete → `dvc pull`) was rehearsed against a local test remote, and the files came back byte-identical. The first real `dvc push` waits for (a) Google credentials on the pusher's machine and (b) the real preprocess sample. Setup: `gcloud auth application-default login`, then `dvc add data/processed data/embeddings`, `git add data/*.dvc`, `dvc push`.
- **DVC + `.gitignore` gotcha (fixed).** The first version used `/data/*` with `!/data/*.dvc` exceptions. Git accepted it, but DVC then saw no tracked data, and `dvc push` printed "Everything is up to date" while uploading nothing. Keep each data folder listed by name, and add a new line for any new folder under `data/`.
- **No `depends_on` on preprocess.** `embed` doesn't wait for preprocess yet, because there's no preprocess service in compose. A commented `depends_on` block is ready to enable.
- **Image size is about 3 GB.** It's verified CPU-only torch (`2.x+cpu`) plus the baked model. Slimming it (e.g. ONNX) is deferred.
- **Windows file locks.** On Windows, keep `embed.query` and notebooks closed while re-running embed, because Chroma holds its files open. The run stops cleanly if you forget.
- **Unparseable shelf text.** A shelf value that's text but not a parseable list (e.g. `"[broken"`) becomes a single shelf name. Preprocess should hand over lists.
- **Excerpts are off.** `EMBED_EVIDENCE_EXCERPTS` stays off while the repo is public, so no description text lands in committed evidence.

## Needs a team decision

- **`milestone2` branch.** The course requires a `milestone2` branch and its commit hash on Canvas. Who creates it, and when?
- **Calling the quality step.** Cathy's preprocess should call `add_quality_flags` right after grouping editions by `work_id`, then write the summary under `manifest.json["quality"]`.
- **Repo visibility.** Make the repo private before any real-data evidence or excerpts are committed.
