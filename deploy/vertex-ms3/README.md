# Offline MS3 training/workflow candidate

**Status: locally executed candidate; cloud execution unverified.** The source-only Linux/amd64 image built successfully, passed its actual entrypoint dry run, and completed one network-disabled local synthetic training/evaluation invocation. No image was published, cloud job submitted or online experiment created. [Actual runtime evidence](../../docs/ms3/evidence/overnight-20261105/workflow-runtime/pass20/runtime-verification.json). This directory prepares a small, reviewable wrapper around the existing B2 exporter and held-out evaluator. It does not establish that the team needs a second cloud workflow: existing team jobs and pipelines could not be verified with the available read access.

The [MS3 rubric](https://harvard-iacs.github.io/2026-AC215/milestone3/) asks for tracked, reproducible serverless training and an automated ML workflow using Vertex AI Pipelines or an equivalent. This candidate proposes one CPU CustomJob that runs input verification → serving export → held-out evaluation → output verification. It is **not a compiled Vertex AI Pipeline**, and its local JSON receipts are **not yet an accepted experiment-tracking equivalent**. Confirm both decisions with the team/TF before selecting or executing this approach. Reuse an existing team pipeline/tracker if one already exists.

## Existing behavior preserved

The worker invokes `python -m evaluation.export` and `python -m evaluation.run`; it contains no replacement model or scoring code. ALS remains 128 factors, regularization 50, alpha 20, 15 iterations and seed 42. Evaluation uses the existing defaults: popularity/item-kNN/ALS, average/least-misery/merged-seeds, five favorites, 300 pairs, K=10, item-kNN 100 neighbors and the test split. These are explicit in the recorded parameter object/hash. No reduced smoke settings are substituted.

The exporter fits the serving B2 model on all retained readers. The evaluator independently fits the three models on training readers and scores held-out readers; those metrics do not directly measure the all-reader serving refit. Preprocessing is deliberately outside this candidate: inputs must already be the approved `books.parquet`, `interactions.parquet` and `manifest.json`. There is no ingestion, dataset download, DVC access, embedding-model download or automatic package installation.

Source files, evaluation `pyproject.toml`, `uv.lock`, `.python-version`, both Dockerfiles and this wrapper are SHA256-pinned. The base Git commit is recorded separately from the actual file fingerprint so uncommitted preparation cannot masquerade as an exact committed revision. At execution, existing model/evaluation metadata receives `source-sha256:<fingerprint>` through its existing `GIT_COMMIT` mechanism. Model math and defaults remain unchanged.

## Local checks with no cloud access

From the repository root:

```sh
python3.12 -m unittest discover -s deploy/vertex-ms3/tests -v
python3.12 deploy/vertex-ms3/verify_offline.py \
  --out deploy/vertex-ms3/.local-offline-review
```

Choose a new output directory each time. The second command generates a concrete candidate request and dry-run receipt using deliberately invalid parquet fixture bytes. It proves configuration/provenance handling only; it does not load table schemas, fit a model, benchmark quality, validate a cloud API or prove execution. The fake project, bucket names and image digest are labeled fixture-only. Its summary is `verification.json`.

Tests cover altered/missing inputs, synthetic-origin labeling, changed code/lockfiles, output collisions, unsafe storage URIs, mutable image tags, parameter drift, failures/timeouts/interruption, incomplete/nonfinite metrics, isolated input copies, partial persistence and exclusion of reader-level output. Execution tests mock the existing ML subprocesses. They are not training evidence.

## Prepare a plan for the actual approved snapshot

Fill the [decision record](review-intake.json) first. The historical committed [preprocess manifest](../../docs/ms2/datapipeline/evidence/real-preprocess-manifest.json) identifies data version `gr-317756d1a1ad` and the two table hashes, but those processed tables are not present here. Their storage location, exact staged manifest bytes and current approval must be confirmed. A matching historical hash is not permission to access or redistribute data.

The planner requires explicit reviewed values; it does not infer service accounts, buckets or image identities:

```sh
python3.12 deploy/vertex-ms3/workflow.py plan \
  --manifest /approved/local/processed/manifest.json \
  --base-commit FULL_40_CHARACTER_COMMIT_SHA \
  --run-id ms3-approved-run-001 \
  --processed-uri gs://APPROVED_INPUT_BUCKET/processed/APPROVED_VERSION \
  --approval-reference TEAM_APPROVAL_RECORD \
  --project APPROVED_PROJECT_ID --region APPROVED_REGION \
  --image-uri APPROVED_REGISTRY_IMAGE_AT_SHA256_DIGEST \
  --service-account APPROVED_EXISTING_SERVICE_ACCOUNT \
  --output-uri gs://APPROVED_PRIVATE_OUTPUT_BUCKET/ms3-runs \
  --out .integration-runtime/ms3-approved-plan-001
```

Replace the descriptive uppercase values; they intentionally fail validation. Image syntax must end with `@sha256:` and an actual 64-character digest. Input/output prefixes must be disjoint and contain no query, credentials or traversal. The planner produces:

| File | Meaning |
| --- | --- |
| `plan.json` | Source/input/parameter identities and explicit proposed infrastructure |
| `custom-job-request.json` | REST CustomJob body, with `jobSpec.workerPoolSpecs` and one bounded CPU worker |
| `review.json` | Unresolved decisions and explicit `submitted: false` |

Configuration generation reads the supplied manifest and source. It has not verified the table bytes until the worker dry run succeeds:

```sh
python3.12 deploy/vertex-ms3/workflow.py run \
  --plan .integration-runtime/ms3-approved-plan-001/plan.json \
  --processed /approved/local/processed \
  --out .integration-runtime/ms3-approved-dry-run-001
```

The default `run` command verifies regular files, complete table/manifest hashes, origin labels and source/lock identities. It records `dry_run_validated` and never launches the model/evaluator. It does not parse parquet tables. A run directory is exclusive and never overwritten.

## Source-only image preparation

The Dockerfile reuses Python 3.12, uv 0.12.19 and the existing evaluation lockfile. It copies only Python package sources and explicitly selected configuration; no data, model export, `.git`, `.env` or credentials are copied. Prepare a narrow build context locally:

```sh
python3.12 deploy/vertex-ms3/workflow.py context \
  --out .integration-runtime/ms3-source-context-001
```

This stages files and their hash inventory only. After the team confirms the platform and authorizes the image operation, the context is suitable for `docker build -f deploy/vertex-ms3/Dockerfile <staged-context>`. Build, upload and obtain the real image digest through the team's existing process. The actual source-only image build and default-user entrypoint dry run are now verified locally. One subsequent run used the existing synthetic processed cache with network disabled, original 128/15/50/20/42 ALS parameters, two CPUs and 2 GB memory. It completed in about 431 seconds. The requested 300 pairs produced 126 actual pairs from 23 eligible held-out readers because the existing sampler caps the available combinations. These are local runtime results, not Goodreads-quality or cloud/tracker evidence. The final image digest pins the built environment; base-image tags alone do not promise identical future rebuilds.

## Activation and persistence require the operator decision

The generated request deliberately omits `--execute` and `--persist-output`. Submitting it as-is would still incur a cloud job but only run provenance validation. **Do not submit it to test a configuration.** There is no submission function or cloud client in this package.

After existing-team reconciliation, image validation, data/access checks, tracking/workflow agreement and execution/cost authorization, the responsible operator can review adding `--execute` and `--persist-output` to the container argument list and submit through the approved team process. The JSON here is a REST request body; it is not a `gcloud --config` job-spec file. No credential values or access tokens belong in it.

The [official container settings guide](https://cloud.google.com/vertex-ai/docs/training/configure-container-settings) documents `workerPoolSpecs`, immutable custom-container selection and command/argument overrides. The proposed worker uses the platform's [Cloud Storage filesystem](https://cloud.google.com/vertex-ai/docs/training/cloud-storage-file-system) to read approved objects under `/gcs/<bucket>/<prefix>`. Verify regional bucket/mount availability and permissions for the selected existing service account. This worker creates no mount and changes no IAM. A configured `baseOutputDirectory` does not make this wrapper upload arbitrary local outputs automatically.

When explicitly executed, the worker verifies inputs and copies only the three approved processed files to a private temporary directory, hashes the copies and removes that snapshot on success or failure. It runs the existing modules with subprocess argument arrays and the locked environment, captures local logs, verifies both export and evaluator source identities/metrics and checks for source/input drift. It installs nothing. Children share one monotonic time budget, with up to 120 seconds reserved for output verification/persistence and a final five-second receipt margin; evaluation receives only the remaining training time. A nonzero child result, exhausted budget, timeout, interruption, missing output or provenance mismatch records failure and stops downstream work. The margins reduce the risk of losing a receipt to the platform timeout; they cannot guarantee persistence after a worker/host failure.

With the separate persistence flag, a future authorized worker copies only these outputs into a **new** `<output-prefix>/<run-id>/` directory and verifies the copied hashes:

```text
artifacts/current/{books.json,item_embeddings.npy,coords_2d.npy,meta.json}
evaluation/held-out/{config.json,summary.csv,summary.md}
metrics.json
plan.json
tracking.jsonl
receipt.json  # written last, after the selected copies verify
```

No full processed input, reader-level `per_pair.csv`, favorite/example lists or private subprocess logs are included in that persistence allowlist. Keep the output prefix private under existing ownership/access; selected catalogue/model files can still carry licensing restrictions. Full local execution folders also contain private evaluation files and belong under ignored `.integration-runtime/`, not Git or a public Site. Partial copies have no successful destination receipt; inspect and clean them through the operator's approved process rather than overwriting.

Receipts record plan/source/input/parameter/output hashes, stage outcomes and aggregate metrics. `completed_local` means the invoked local processes and output checks completed. Even in a cloud container, `cloud_execution_verified` and `external_tracking_verified` remain false until independent job/tracker evidence is reconciled; `/gcs` being a directory does not prove cloud execution. Capture the actual job resource/state, immutable image, logs, tracker run link/screenshot and output receipt for the MS3 evidence package. Existing local or mocked evidence must keep its original label.

## Open decisions

The [decision record](review-intake.json) lists the precise missing inputs. This candidate closes the offline orchestration-preparation gap only. It does not close tracked cloud training, accepted pipeline equivalence, successful cloud execution, live deployment, production monitoring or submission evidence. The separate existing [Cloud Run package](../cloud-run/) remains the deployment path; no competing service or model change is introduced.
