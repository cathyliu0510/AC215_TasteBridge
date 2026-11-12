# TasteBridge

A book recommender for two readers. Each picks five favorites; TasteBridge suggests five shared reads with a reason for each person.

[MS2 slides](https://docs.google.com/presentation/d/1JUz5bPlGqBAYeBMOLzO22sUbZ3DdYllxlPU6gF_tK54/edit) · [MS1 proposal](milestones/ms1/) · [Standalone frontend prototype](https://tastebridge-prototype.landenini.chatgpt.site/)

## Milestone 3

[Current requirements and evidence](docs/ms3/) · [Jenny's deployment and evidence checklist](docs/ms3/jenny-serving-handoff-20261111.md) · [Existing-model reproduction](docs/ms3/reproduce.md) · [API contract](src/backend/SPEC.md) · [Deploy and redeploy](deploy/cloud-run/README.md).

**Updated November 11, 2026: the private staging service is deployed and verified.** [TasteBridge staging](https://tastebridge-staging-fbii3egyuq-uc.a.run.app) serves the locked 5,000-book B2 ALS export at revision `tastebridge-staging-00002-vzn`. [Live API, prediction screenshots and cloud logs](docs/ms3/evidence/deployed-serving-20261111/). Authentication is preserved; the teaching-staff account's own access still needs confirmation. Team training, the Vertex AI pipeline and the kNN + ALS hybrid are merged into `milestone3` (PRs #13, #14 and #15).

### Changes since MS2

- Added a tested frontend API adapter, stale-response protection, same-tab recovery and fingerprint checks so saved responses cannot silently attach to a different model.
- Added startup validation and exact four-file model identity, plus a catalogue search index that preserves the backend's result order and scoring.
- Added Cloud Run frontend/backend packaging, startup probes, access-preserving publication, artifact checks and rollback records. Fresh local container and live cloud smoke passed with the existing 5,000-book ALS export. [Deployment verification](docs/ms3/evidence/deployed-serving-20261111/deployment-summary.json).
- Added M1 two-tower training on Vertex AI (T4 GPU) with W&B experiment tracking ([PR #13](https://github.com/cathyliu0510/AC215_TasteBridge/pull/13), [training record](deploy/twotower/README.md#reproduce-a-training-run)).
- Added a shared Vertex AI pipeline (check data → train → evaluate → gate → publish) with an M1 branch and an ALS branch ([PR #13](https://github.com/cathyliu0510/AC215_TasteBridge/pull/13), [PR #14](https://github.com/cathyliu0510/AC215_TasteBridge/pull/14), [pipeline runs](deploy/twotower/README.md#completed-runs-evidence)). M1 passed the 0.042 least-misery gate and was published as a candidate; ALS scored 0.0236 and publication was intentionally skipped.
- Added an item-kNN + ALS hybrid with ALS fold-in, tuned on the tune split and evaluated offline ([PR #15](https://github.com/cathyliu0510/AC215_TasteBridge/pull/15), [hybrid notes](docs/ms3/hybrid/README.md)).
- The app still serves B2 ALS. Serving M1 needs reader-tower inference, and serving the hybrid needs two extra artifact files; both are next steps.

### Runbook entry points

- Training and experiment tracking: [reproduce a Vertex AI training run with W&B](deploy/twotower/README.md#reproduce-a-training-run).
- Automated workflow: [run the Vertex AI pipeline](deploy/twotower/README.md#run-it) ([`pipeline.py`](deploy/twotower/pipeline.py); ALS step in [`pipeline_train.py`](src/evaluation/evaluation/pipeline_train.py)). Completed runs are recorded, so there is no need to start a new paid run.
- Hybrid model: [tune and evaluate with `make tune-hybrid`](docs/ms3/hybrid/README.md#run-it).
- Deployment: [build, local smoke, publish and rollback](deploy/cloud-run/README.md). The final deployed revision, immutable images and exact serving-model identity are recorded in the live evidence bundle. Authentication is required.
- API access and monitoring: [actual routed endpoints, authenticated browser access, curl capture and revision-linked logs](docs/ms3/jenny-serving-handoff-20261111.md). The deployed prediction, exact model identity and revision-linked logs are recorded in the live evidence bundle.

The [12-slide deck](docs/ms3/presentation/TasteBridge-MS3-review.pptx) is a November 5 historical review draft. Use [Jenny's updated speaking notes](docs/ms3/jenny-presentation-notes-20261111.md) and refresh team training/deployment claims before presenting. The public prototype remains a separate 23-book static demo.

Submit all final work on `milestone3` and its **full commit hash on Canvas by November 12, 10 PM ET**. The TF meeting scheduled the presentation for November 16; that does not extend the submission deadline. No submission receipt is established by this repository.

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

Local setup now includes a prerequisite check, consistent launcher validation and explicit Docker host configuration. Reading Desk keeps the active reader's shelf visible and brings search into view when editing on a phone. [M3 readiness and local verification](docs/ms3/local-readiness.md) separates these changes from the cloud training and deployment evidence still to be verified.

The [Book connections UX review](docs/ms3/connections-ux-20261104.md) covers the current named-reference diagram, optional similarity projection, narrow-screen flows and downloadable offline preview. The [design review](docs/ms3/design-review-20261104.md) records the daylight visual system, and the [earlier UI review](docs/ms3/ux-refinement-20261104.md) records the initial selection and map behavior changes.
