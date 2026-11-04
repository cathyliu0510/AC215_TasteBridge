# Reproduce the served-model integration locally

This workflow invokes the existing preprocessor, B2 exporter, held-out evaluator, backend and frontend relay. It records configuration, source and input hashes, logs, model identity and HTTP contract results. It does not contact Google Cloud, publish a service or replace the course's serverless-training requirement.

## Fresh checkout

Requires Python 3.12, uv and Node 20+. From the repository root:

```sh
uv sync --frozen --project src/datapipeline/preprocess
uv sync --frozen --project src/evaluation
uv sync --frozen --project src/backend
python3 tools/verify_local_integration.py --synthetic --out .integration-runtime/ms3-example
```

Choose a new output directory for each run. Existing output is never overwritten. Environments use the committed lockfiles; the runner itself installs nothing and requires no credentials. In a restricted environment, set `UV_CACHE_DIR` to a writable local directory before `uv sync`.

The synthetic input contains invented books/readers. The served model is actually fitted by the B2 exporter on that input, but it establishes integration behavior only. It provides no estimate of Goodreads quality. The model/data identity includes `synthetic-` to keep this distinct from the 52-book fixed fixture and the licensed-data export.

The default smoke configuration is 160 generated works, 400 generated readers, seed 42, 16 ALS factors, 8 iterations and 20 held-out pairs, with both served ranking rules. The exporter retains its regularization 50 and alpha 20. These smaller smoke settings are not a replacement for the tuned MS2 configuration (128 factors, 15 iterations). All parameters and actual retained counts are recorded.

## Existing processed data

After an authorized data retrieval, reuse the same verification path without regenerating or writing to the input:

```sh
python3 tools/verify_local_integration.py --processed data/processed \
  --factors 128 --iterations 15 --n-pairs 300 \
  --out .integration-runtime/ms3-authorized-data
```

The required inputs are `books.parquet`, `interactions.parquet` and `manifest.json`. The runner labels the origin `operator_supplied`; the operator must establish its licensed source and version. No dataset download or DVC access occurs automatically.

## Inspect the model in the actual UI

Add `--serve` to keep only this run's two loopback services alive. The runner prints a URL containing ten IDs from the newly exported catalogue, so both readers can start with valid favorites. Automatic ports are the default. Use `--api-port` and `--ui-port` for explicit free ports. Ctrl-C stops the owned processes. No existing server is reused or terminated.

The HTTP check uses the same `deploy/cloud-run/smoke.py` contract logic as the prepared deployment package. Known catalogue IDs avoid assuming that The Hobbit or Gone Girl is present. The check verifies model/count identity, frontend routing, search/details, both ranking rules, finite and correctly aggregated scores, seed exclusion, unique results, per-reader references, matching projection coordinates and private-route isolation. It does not send feedback.

## Outputs

```text
<run>/
  run.json              source commit/hashes, inputs, parameters, stages, status
  generate.log          synthetic only
  preprocess.log        synthetic only
  processed/            synthetic only, original preprocessing fingerprint retained
  train.log
  artifacts/current/    backend's four-file export, never committed
  evaluation/held-out/  split/configuration, aggregate metrics, logs, examples
  api-check.json        actual relay/API response checks
  backend.log           actual local startup and request logs
  frontend.log
```

`run.json` records failure/interruption instead of converting incomplete stages into success. The source commit and per-file hashes distinguish committed code from a dirty working tree. Timings and creation timestamps can vary. Seeded synthetic compressed inputs and processed tables have stable content hashes; this is not a promise that UMAP coordinates or whole run folders are bitwise identical across platforms.

The local chain covers the currently served B2 path. The existing Compose workflow also runs text embeddings; this runner does not download the embedding model or claim to verify that separate index.

Keep full run folders under the ignored `.integration-runtime/`. Only deliberately selected, sanitized evidence belongs in `docs/ms3/evidence/`. No real reader histories, data export or credentials belong in Git.

## Remaining MS3 operator work

The [runbook](README.md) and [evidence index](evidence/index.json) track the real tracked serverless training run, approved cloud workflow, live service, production logs and teaching-staff access still required. Use the existing Cloud Run package and confirm prior team executions before creating duplicates. GitHub push remains denied by security review; no alternate publishing path is authorized.
