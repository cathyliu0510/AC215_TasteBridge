# Data pipeline: quality checks + embed stage — notes for the team

Owner: YiTong. Code from branch `feature/datapipeline-embed` (PR #3); Cathy's `feature/datapipeline` builds ingest + preprocess on top of it.
No Goodreads data is in git. The evidence in `docs/ms2/embed/` comes from the full real run (Oct 17) and holds only titles, authors, genres and similarity scores.

## What this adds

| Path | What it is |
|---|---|
| `src/datapipeline/preprocess/quality.py` | `add_quality_flags(books)` for Cathy's preprocess: cleans descriptions and shelf tags, adds `has_description` and `description_issue`, returns a summary for `manifest.json["quality"]` |
| `src/datapipeline/embed/` | The embed stage (own `pyproject.toml`, `uv.lock`, `Dockerfile`, tests): `books.parquet` → 384-number vector per book → ChromaDB index + retrieval examples |
| `docker-compose.yml` | New `embed` service, **opt-in** via the `pipeline` profile (see below); the backend service is unchanged |
| `.dvc/`, `.dvcignore`, `.gitignore` | DVC initialised with remote `gs://tastebridge-dvc`; git ignores `data/raw/`, `data/interim/`, `data/processed/`, `data/embeddings/` by name, so the `data/*.dvc` tickets stay visible to both git and DVC |
| `docs/ms2/embed/` | MS2 evidence from the full real-data run (`retrieval_example.md`, `run.log`, `meta.json`) |

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

## Real-data run (Oct 17, YiTong's Windows laptop, full files)

`INGEST_SAMPLE_LINES=0 docker compose --profile pipeline run --rm embed` (ingest → preprocess → embed), then `train` and `evaluation`:

| Check | Result |
|---|---|
| Wall time, ingest + preprocess + embed | 12.5 min (4.4 GB download included) |
| `data_version` | **`gr-317756d1a1ad`**, identical to Cathy's MacBook run, so preprocess is reproducible across machines and OSes |
| Quality step (`manifest.json["quality"]`) | 5,000 books; 13 missing + 1 too-short descriptions (embedded from title + author + shelves); 8.9 M raw shelf entries → 99,959 kept; 0 books left without shelves |
| Embed | 5,000 × 384 vectors + Chroma index in 70 s on CPU; `input_data_version` = `gr-317756d1a1ad` |
| Retrieval examples | heist → *The Art Forger*, *Heist Society*; village murder → mystery series; magic school → *The Wizard Heir*, *Young Wizards* |
| `train` → backend | `b2-als-gr-317756d1a1ad` served with 5,000 books; `/recommend` answers |
| Evaluation (test split, 5 favorites) | B0 0.038, B1 item-kNN avg 0.071, B2 tuned ALS avg **0.043** Min-Recall@10, matching `docs/ms2/models/README.md` |

## Known limitations

- **DVC: verified against the real bucket, first push pending.** On Oct 17, a scratch clone pushed 7 files to a temporary `gs://tastebridge-dvc/_verify-…` prefix with Application Default Credentials. It deleted them locally, pulled them back byte-identical, and got "Cache and remote are in sync". The prefix was deleted afterwards. The first real push (`make dvc-push`: raw ≈ 4.4 GB, processed, embeddings, artifacts) should be done by **one** person, so the `.dvc` pointers in git match the bucket. Each pusher needs `gcloud auth application-default login` once. The "no quota project" warning it prints is harmless.
- **DVC + `.gitignore` gotcha (fixed).** The first version used `/data/*` with `!/data/*.dvc` exceptions. Git accepted it, but DVC then saw no tracked data, and `dvc push` printed "Everything is up to date" while uploading nothing. Keep each data folder listed by name, and add a new line for any new folder under `data/`.
- **Windows + Git Bash.** Git Bash rewrites container paths such as `ARTIFACT_DIR=/artifacts/current` into `D:/Git/artifacts/current`, and the backend then exits with code 3. Run with `MSYS_NO_PATHCONV=1` (or add `export MSYS_NO_PATHCONV := 1` to the Makefile). `make` is not installed on Windows by default; the README's plain `docker compose` commands work.
- **Image size is about 3 GB.** It's verified CPU-only torch (`2.x+cpu`) plus the baked model. Slimming it (e.g. ONNX) is deferred.
- **Windows file locks.** On Windows, keep `embed.query` and notebooks closed while re-running embed, because Chroma holds its files open. The run stops cleanly if you forget.
- **Unparseable shelf text.** A shelf value that's text but not a parseable list (e.g. `"[broken"`) becomes a single shelf name. Preprocess hands over lists, so this doesn't happen on real data (`n_unknown_shelf_entries` = 0).
- **Excerpts are off.** `EMBED_EVIDENCE_EXCERPTS` stays off while the repo is public, so no description text lands in committed evidence.

## Needs a team decision

- **`milestone2` branch.** The course requires a `milestone2` branch and its commit hash on Canvas. Who creates it, and when?
- **Calling the quality step.** ✅ Done in Cathy's `preprocess.py` (after grouping editions by `work_id`; summary under `manifest.json["quality"]`).
- **Repo visibility.** Make the repo private before any real-data evidence or excerpts are committed.
