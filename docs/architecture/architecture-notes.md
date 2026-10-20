# TasteBridge architecture

These diagrams describe the **implemented MS2 system**, inspected on 20 October
2026 at commit
[`c9d02d6319ba225a958571f7cc780bd72a738203`](https://github.com/cathyliu0510/AC215_TasteBridge/tree/c9d02d6319ba225a958571f7cc780bd72a738203).
Future work is listed separately below. This is a source/configuration audit,
supported by the repository's existing runtime evidence; it is not a new
deployment or a fresh execution of every pipeline stage.

## Files and editing

| Diagram | Vector | Presentation image | Editable source |
|---|---|---|---|
| Solution | [SVG](solution-architecture.svg) | [PNG](solution-architecture.png) | [draw.io](solution-architecture.drawio) |
| Technical | [SVG](technical-architecture.svg) | [PNG](technical-architecture.png) | [draw.io](technical-architecture.drawio) |

Both diagrams use a white **1600 × 900 (16:9)** canvas. PNGs are exported at
**3200 × 1800**. Open `.drawio` files in diagrams.net to edit native rectangles,
text and connectors. SVG text is also editable; neither diagram is a flattened
screenshot. [build-diagrams.py](build-diagrams.py) is the maintainable layout
source, and [diagram-layout.json](diagram-layout.json) records its generated
elements. Running `python build-diagrams.py` regenerates both SVG and draw.io
files. Rasterize the SVGs at 2× after layout changes.

The readability revision uses original outline icons, shorter card labels and
dark blue arrows for the user/API interaction path. Green arrows identify model
loading; secondary file/dependency paths stay muted. Icons are vector paths in
SVG and self-contained, movable SVG objects in draw.io. No remote icon assets,
emoji fonts or brand logos are required. The implementation scope and connections
are unchanged; detailed technologies and file paths remain in these notes.

The conceptual structure follows Harvard AC215 **Lecture 12**:

- *App Design*, pages 20–22 and 32: people, executable components and persistent
  resources; page 47: technology and deployment boundaries.
- *Steps to Build a Solution Architecture*, page 2: the pink/blue/green
  three-layer template; page 4: the technical example.
- [Official course schedule](https://harvard-iacs.github.io/2026-AC215/schedule/),
  [Lecture 12 lesson](https://edstem.org/us/courses/97373/lessons/166037) and
  [architecture activity deck](https://docs.google.com/presentation/d/1U69Nri6ZBYmjGSv5402kZwXnswo1eYZDBhBRPuIfKas/edit).

The lecture PDFs were inspected locally. Its sample infrastructure was not
copied into TasteBridge's architecture.

## 1. Project overview

TasteBridge helps **two readers find a book to read together**. Each reader
selects five favorite books. The app returns five shared recommendations,
reader-specific reasons, a taste map, and an optional shared-feedback action.
The current real-model catalogue contains **5,000 Goodreads works**.

The connected application uses **B2 implicit ALS** factors. B0 popularity and
B1 item-kNN are offline comparison models. Description embeddings and a Chroma
index are implemented as a separate offline retrieval workflow.

## 2. Solution architecture

The three horizontal layers distinguish:

- **Process (People), pink:** developers build and test; the data/ML team
  prepares data and evaluates models; two readers use the app.
- **Execution (Code), blue:** development, data/model workflows, and the reader
  application. Data preparation supplies both baseline modeling and description
  retrieval. The frontend communicates with the recommendation API.
- **State (Source, Data, Models), green:** source/configuration/evidence,
  versioned datasets, the persistent text index, exported model files and
  anonymous feedback.

The roles describe activities, not new team assignments. The diagram groups
training and evaluation for readability; they are separate jobs, with different
training populations. Its arrows are dependencies/data or interaction flows,
not a literal schedule. Bidirectional arrows mean request/response or
read/write; a one-way arrow indicates the stated direction of data or action.

## 3. Technical architecture

### Local application

`make app` builds and starts the frontend and backend using
`compose.integration.yml`, after a trained export is present.

1. A browser runs Version A's plain **HTML/CSS/JavaScript**.
2. Host **127.0.0.1:4176** maps to the **Node.js 24 container's port 8080**.
3. Node serves the frontend and proxies same-origin `/api/*` requests to
   **http://backend:9000**, removing the `/api` prefix.
4. **FastAPI/Uvicorn** runs the Python backend. The connected-app configuration
   does not publish backend port 9000 to the host.
5. At startup, the backend reads a local, **read-only** model mount and keeps
   the catalogue and NumPy factors in memory. It does not call GCS per request.
6. Explicit shared feedback is appended to JSONL in the Docker `feedback`
   volume. The feedback action does not retrain the model.

The separate backend-only Compose configuration does expose `9000:9000`.
The technical diagram intentionally shows the connected application path,
without mixing those two configurations.

The browser's routes are `/api/health`, `/api/books/search`,
`/api/books/{book_id}`, `/api/recommend`, and `/api/feedback`. The backend
receives the corresponding paths without `/api`.

### Local offline jobs

Docker Compose builds images from the repository's Dockerfiles. Python
components use **Python 3.12**, `pyproject.toml`, `uv.lock`, and
`uv sync --frozen`.

- **Ingest:** downloads UCSD Goodreads book metadata, author metadata and
  interaction files over HTTPS.
- **Preprocess:** uses pandas, NumPy and PyArrow to group editions into works,
  clean metadata, deduplicate interactions and select the catalogue. A like
  uses an individual's rating threshold; this is not an average-book-rating
  filter.
- **Train/export:** custom NumPy/SciPy B2 implicit ALS fits all retained readers
  for the serving export. UMAP produces map coordinates, with a PCA fallback.
- **Evaluate:** B0, B1 and B2 are fitted/evaluated using a reader-based
  train/tune/test split. Evaluation does not consume the all-reader serving
  export.
- **Embed/query:** CPU SentenceTransformers `all-MiniLM-L6-v2` produces
  description vectors. An embedded persistent Chroma client supports the
  offline retrieval CLI. Chroma is a local file-backed index, not a separately
  hosted database service.

The diagram groups training/export and evaluation because they share the
evaluation source/image. Their inputs and purposes remain distinct. `make
pipeline` schedules ingest → preprocess → embed → train/export → evaluate;
**ALS and evaluation read processed Parquet, not MiniLM vectors**.

Hugging Face supplies a pinned MiniLM revision during the embedding image
build. The dashed connector is a **build-time download**, not a runtime
inference request. Embedding runtime is configured offline.

### Persistent storage and external services

| Resource | Location / persistence |
|---|---|
| Source, configuration, Dockerfiles, lockfiles | GitHub and local checkout |
| Data/model version pointers | `data/*.dvc` in GitHub |
| Raw Goodreads files | Local `data/raw/`; DVC copies in GCS |
| Processed catalogue/interactions | `data/processed/books.parquet`, `interactions.parquet`, `manifest.json`; DVC copies in GCS |
| Description vectors and Chroma files | `data/embeddings/`; DVC copies in GCS |
| ALS serving export | `data/artifacts/<model-version>/` and `data/artifacts/current/`; DVC copies in GCS |
| Export contents | `books.json`, `item_embeddings.npy`, `coords_2d.npy`, `meta.json` |
| Experiment outputs | Local `src/evaluation/results/`; selected records committed under `docs/ms2/models/runs/` |
| Anonymous shared feedback | Named Docker volume `feedback`, mounted at `/app/feedback`, with `feedback.jsonl` |

The configured GCS remote is **`gs://tastebridge-dvc`**. DVC CLI synchronizes
raw, processed, embedding and model-artifact directories. It does not
automatically sync evaluation results or the feedback volume. The technical
diagram's local ALS export box is a detail view of `data/artifacts`, not an
additional copy in a separate database.

Reader picks and individual interest controls are browser memory; selected
book IDs/ranking may be encoded in a share URL. There is no current account
database or durable user-profile service.

## 4. Main data flows

**Prepare data**

UCSD Goodreads → ingest → local raw files → preprocess → versioned Parquet.

**Export a serving model**

Processed data → B2 ALS fit → catalogue/factors/map/metadata → local model
directory → backend startup load.

**Evaluate models**

Processed data → reader split → independently fitted B0/B1/B2 →
paired-reader metrics, configurations and logs.

**Prepare text retrieval**

Processed book descriptions → MiniLM encoder → description vectors + Chroma
index → offline query CLI. This flow does not feed the current app API.

**Use the app**

Two sets of five favorites → Node `/api` proxy → FastAPI → each reader's
normalized mean ALS factor → per-book cosine scores → average or
least-misery aggregation → five shared recommendations, metadata-based reasons
and stored map coordinates → browser. Selected favorites are excluded.

**Save feedback**

Explicit shared feedback action → `/feedback` → append-only JSONL.

**Reproduce locally**

Git checkout + authorized `dvc pull` → local data/model files → local Docker
builds → pipeline jobs or connected app. A trained model can be downloaded
without rerunning preprocessing or training.

## 5. Implemented versus planned

**Implemented and represented in the diagrams**

- Local Docker frontend/API integration with real Goodreads data and ALS.
- Ingestion, preprocessing, training/export and baseline evaluation.
- Separate MiniLM embedding, Chroma persistence and offline retrieval.
- Git/DVC versioning, GCS storage and JSONL feedback persistence.
- Local source builds, automated tests and committed experiment evidence.

**Documented future work, excluded from the current runtime diagram**

- Hybrid ranking combining description/shelf features with collaborative
  factors; this integration is not the current recommender.
- Hosted real-model application and the proposal's Cloud Run deployment.
- W&B tracking and Vertex AI training/jobs in the next-iteration discussion.
- Later CI and Kubernetes/deploy-on-merge work described in the proposal.

These are recorded proposal/next-iteration items, not new commitments or
completed deployments. No tracked CI workflow, Terraform, Kubernetes manifest,
application container registry or cloud-application deployment manifest was
found in this snapshot. Base-image downloads do not establish an app-owned
container registry.

No generative LLM provider, agent framework, prompt-based application service,
relational database or automatic feedback-to-training loop is implemented.
The public hosted prototype is a separate frontend demo, not evidence of
public real-model backend hosting.

## 6. Assumptions and verification limits

- The diagram chooses the verified **Version A / `make app`** path. Alternate
  toy-catalogue and standalone Version B flows are not separate deployments
  in this diagram.
- `feedback` volume persistence means persistence across container recreation
  while the volume exists; it is not a cloud backup.
- DVC/GCS storage is supported by tracked configuration and existing records.
  Current bucket permissions and downloadability were not retested.
- Prior app screenshots document an October 18 real-model run. They are not
  proof of a fresh run of the latest re-exported artifact.
- The one-command pipeline is implemented. The audit does not claim that all
  stages were rerun together during diagram creation.
- Grouped boxes omit low-level library calls and base-image registries to keep
  the diagrams readable. The source table below provides the details.
- Known performance/causal wording issues in model documentation were not
  adopted as architecture facts. No latency or training-time claim is made.
- These files add architecture documentation only. Application and teammate
  backend/model code are unchanged.

## 7. Source evidence

Paths below are relative links into this repository. The pinned commit at the
top records the inspected implementation even if `main` changes later.

| Architectural decision | Supporting source |
|---|---|
| Product purpose, real-model app and separate hosted prototype | [README.md](../../README.md) |
| One-command jobs and application | [Makefile](../../Makefile), especially `pipeline`, `train`, `evaluate`, `app`, `dvc-push` |
| Pipeline containers and file mounts | [docker-compose.yml](../../docker-compose.yml) |
| Connected frontend/backend, ports, proxy environment, mounts and health dependency | [compose.integration.yml](../../compose.integration.yml) |
| Browser flow and explicit shared feedback | [app.mjs](../../frontend/prototype/src/a/app.mjs), [API client](../../frontend/prototype/src/api/client.mjs) |
| Node runtime, static serving and route allowlist/proxy | [frontend Dockerfile](../../frontend/prototype/Dockerfile), [serve.mjs](../../frontend/prototype/scripts/serve.mjs) |
| Backend dependencies and startup | [backend Dockerfile](../../src/backend/Dockerfile), [pyproject.toml](../../src/backend/pyproject.toml), [main.py](../../src/backend/app/main.py) |
| Local model loading and rejection of runtime `gs://` paths | [artifacts.py](../../src/backend/app/artifacts.py) |
| ALS scoring and aggregation | [recommender.py](../../src/backend/app/recommender.py) |
| Metadata reasons and map/results | [explanations.py](../../src/backend/app/explanations.py), [recommend_service.py](../../src/backend/app/recommend_service.py) |
| In-memory title/author search | [search.py](../../src/backend/app/search.py) |
| JSONL feedback persistence | [feedback.py](../../src/backend/app/feedback.py), [config.py](../../src/backend/app/config.py) |
| External data URLs and download manifest | [ingest.py](../../src/datapipeline/ingest/ingest.py) |
| Catalogue/interaction processing and Parquet/manifests | [preprocess.py](../../src/datapipeline/preprocess/preprocess.py), [preprocess dependencies](../../src/datapipeline/preprocess/pyproject.toml) |
| ALS fit, export files and map | [als.py](../../src/evaluation/evaluation/als.py), [export.py](../../src/evaluation/evaluation/export.py) |
| Independent held-out evaluation | [run.py](../../src/evaluation/evaluation/run.py), [evaluation README](../../src/evaluation/README.md) |
| Pinned encoder and offline image/runtime behavior | [embedding Dockerfile](../../src/datapipeline/embed/Dockerfile), [config.py](../../src/datapipeline/embed/embed/config.py), [encoder.py](../../src/datapipeline/embed/embed/encoder.py) |
| Embedded persistent Chroma and offline query | [store.py](../../src/datapipeline/embed/embed/store.py), [embedding README](../../src/datapipeline/embed/README.md) |
| Actual DVC remote and tracked folders | [.dvc/config](../../.dvc/config), [data/](../../data/) |
| Recorded real frontend/API integration | [real-model evidence](../ms2/frontend-api/real-model-20261018/), [integration guide](../backend-integration.md) |
| Model comparison and future hybrid work | [models README](../ms2/models/README.md) |
| Future cloud/CI/deployment plans | [MS1 milestones](../../milestones/ms1/source/sections/09_milestones.tex), [proposed solution](../../milestones/ms1/source/sections/04_solution.tex) |
