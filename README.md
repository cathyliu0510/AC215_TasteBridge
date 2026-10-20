# TasteBridge

A book recommender for two readers. Each picks five favorites; TasteBridge suggests five shared reads with a reason for each person.

[MS2 slides](https://docs.google.com/presentation/d/1JUz5bPlGqBAYeBMOLzO22sUbZ3DdYllxlPU6gF_tK54/edit) · [MS1 proposal](milestones/ms1/) · [Standalone frontend prototype](https://tastebridge-prototype.landenini.chatgpt.site/)

## Milestone 2

The app serves a trained **B2 implicit ALS model over 5,000 Goodreads works**. Version A and the FastAPI backend run together in local Docker. The public prototype above is a separate frontend demo.

| Deliverable | Evidence |
| --- | --- |
| Data ingestion, preprocessing and versioning | [Pipeline instructions](docs/ms2/datapipeline/) · [real-data manifests and sample input/output](docs/ms2/datapipeline/evidence/) · [DVC pointers](data/) |
| B0 popularity, B1 item-kNN and B2 implicit ALS | [Models and results](docs/ms2/models/) · [tuning/test logs](docs/ms2/models/runs/) |
| Description embeddings and retrieval | [MiniLM/Chroma evidence and query examples](docs/ms2/embed/) |
| Frontend + real-model API | [Docker integration, screenshots and input/output](docs/ms2/frontend-api/real-model-20261018/) · [running containers](docs/ms2/running-containers.png) |

The saved evidence covers each real-data stage, a synthetic preprocessing/evaluation demo, and a [one-command end-to-end run on the full data](docs/ms2/datapipeline/evidence/e2e-full-windows.log) (ingest → preprocess → embed + train → evaluation, `data_version gr-317756d1a1ad`, exit code 0).

## Run the app

Requires Docker with Compose. `make` is optional: every target has a plain `docker compose` equivalent (below, and in the [pipeline guide](docs/ms2/datapipeline/#run-it-from-the-repo-root)), so Windows PowerShell works without it. To use the existing trained export, also install DVC with GCS support and the Google Cloud CLI; your Google account needs read access to the team's DVC bucket. Without bucket access, build everything from the public Goodreads files with the pipeline command below.

From the repository root:

```sh
gcloud auth application-default login
dvc pull data/artifacts.dvc
make app
```

Windows PowerShell, without `make`: replace the last line with `$env:ARTIFACT_DIR="/artifacts/current"; docker compose -f compose.integration.yml up --build`.

This downloads the model artifacts, not the raw dataset, then starts **both frontend and backend**. Open **http://127.0.0.1:4176/a/?api=1**. Check [API health](http://127.0.0.1:4176/api/health) for 5,000 books, model `b2-als-gr-317756d1a1ad` and data version `gr-317756d1a1ad`.

To build the artifacts yourself, one command runs ingest → preprocess → embed + train/export → evaluation, each stage in its own container:

```sh
docker compose --profile pipeline build
docker compose --profile pipeline run --rm pipeline     # or: make pipeline
```

For a quicker run on the first 200,000 lines of each interaction file, set `INGEST_SAMPLE_LINES=200000` first (`make sample`; in PowerShell `$env:INGEST_SAMPLE_LINES=200000`). See the [pipeline guide](docs/ms2/datapipeline/) for inputs, dependencies and run scope.

For the bundled 52-book toy catalogue, use `docker compose -f compose.integration.yml up --build --wait`. Plain `docker compose up --build` starts only the backend. The [integration guide](docs/backend-integration.md) covers alternate artifact locations, shutdown and UI checks.

## Dataset

[UCSD Goodreads Book Graph](https://cseweb.ucsd.edu/~jmcauley/datasets/goodreads.html), collected from public shelves in late 2017. Academic use only; do not redistribute dataset files or use them commercially.

| Subset | Books | Interactions | Downloads |
| --- | ---: | ---: | --- |
| Fantasy & Paranormal | 258,585 | 55,397,550 | [Metadata](https://mcauleylab.ucsd.edu/public_datasets/gdrive/goodreads/byGenre/goodreads_books_fantasy_paranormal.json.gz) · [Interactions](https://mcauleylab.ucsd.edu/public_datasets/gdrive/goodreads/byGenre/goodreads_interactions_fantasy_paranormal.json.gz) |
| Mystery, Thriller & Crime | 219,235 | 24,799,896 | [Metadata](https://mcauleylab.ucsd.edu/public_datasets/gdrive/goodreads/byGenre/goodreads_books_mystery_thriller_crime.json.gz) · [Interactions](https://mcauleylab.ucsd.edu/public_datasets/gdrive/goodreads/byGenre/goodreads_interactions_mystery_thriller_crime.json.gz) |

These are gzip-compressed JSON files. Counts are before filtering; the genres overlap.

The processed snapshot **`gr-317756d1a1ad`** contains **5,000 works, 9,896 readers and 499,915 interactions**. Preprocessing groups editions by `work_id`, deduplicates interactions and keeps the most-liked works within the MVP cap. Raw and processed data, text embeddings and model exports are tracked with DVC; GitHub stores pointers and evidence, not the Goodreads files.

## Model and evaluation

- **Served model:** B2 implicit ALS, with average or least-misery ranking. Each reader's taste vector is the normalized mean of their five favorites' book vectors.
- **Evaluation:** an 80/10/10 reader split and simulated pairs; Min-Recall@10, mean NDCG@10 and long-tail coverage. Offline evaluation ranks ten books; the app displays five.
- **Results:** item-kNN remains the strongest baseline on Min-Recall@10. [Full results](docs/ms2/models/#results-on-the-test-split) distinguish held-out evaluation from the model export refit on all retained readers.
- **Text retrieval:** MiniLM description vectors and Chroma are prepared separately; the current app ranks using ALS factors.

## Submission

The [official MS2 requirements](https://harvard-iacs.github.io/2026-AC215/milestone2/) specify the `milestone2` branch and its **full commit hash on Canvas by October 20, 10pm ET**. The final deck is the [shortened presentation](https://docs.google.com/presentation/d/1JUz5bPlGqBAYeBMOLzO22sUbZ3DdYllxlPU6gF_tK54/edit), with 16 main slides and five backup slides. The TF asked for slides with the submission. Repository updates do not confirm Canvas submission.

## Frontend

Editable A/B source, standalone HTML and [build/run instructions](frontend/prototype/README.md#build-and-run) are in [frontend/prototype](frontend/prototype/).
