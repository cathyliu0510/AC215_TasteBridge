# Milestone 3: integration readiness

Checked November 4, 2026 against the [official MS3 instructions](https://harvard-iacs.github.io/2026-AC215/milestone3/) and the remote repository. **This is a preparation branch, not a completed submission.**

Remote `main` and `milestone2` both point to `fccfbac53a96de18b71ca1c3f668a6bea115e51e`; no remote `milestone3` branch was listed. The course requires that branch and its full commit hash on Canvas by **November 12, 10pm ET**, plus a 15-minute TF presentation with slides. Canvas and presentation submission have not been verified.

## Requirement → evidence → gap

| Area | Available implementation/evidence | Remaining evidence |
| --- | --- | --- |
| Tracked, reproducible serverless training | [Existing ALS runs, configuration and metrics](../ms2/models/runs/) · [Training/export code](../../src/evaluation/evaluation/) | A successful cloud training execution, tracking record and screenshot; local MS2 runs do not establish this |
| Deployed model/API | [Cloud Run preparation](../../deploy/cloud-run/) · [historical local container verification](../../deploy/cloud-run/verification.local.json) | Authorized deployment URL, revision/configuration and request/response screenshot |
| Automated ML workflow | [One-command Compose pipeline](../ms2/datapipeline/) covering ingest → preprocess → embed/train → evaluation | Verify the selected cloud workflow or document the accepted equivalent with the TF |
| Production monitoring | [Backend request/feedback logging](../../src/backend/app/) · Cloud Logging configuration in the deployment guide | Actual deployed logs, access instructions and a captured example |
| Documented, tested prediction API | [SPEC](../../src/backend/SPEC.md) · [backend instructions](../../src/backend/README.md) · current local tests | Run the same contract checks against the authorized deployed service |

[Evidence index](evidence/index.json) is intentionally incomplete. Run `python3 tools/check_ms3.py` to list gaps; a nonzero result means the recorded submission evidence is not complete. The checker validates manifest coverage and repository-relative evidence paths; it does not certify cloud execution, screenshot contents or Canvas submission.

## What changed after MS2

- Reading Desk A `20261104.3`: [named book connections, response/choice state, responsive checks and independent UX review](connections-ux-20261104.md). The model scores and returned coordinates are preserved. B remains the comparison.
- Frontend prerequisite checks, explicit container host configuration and cancellation/child-process cleanup: [local setup record](local-readiness.md).
- Existing Cloud Run preparation commits `3b7dafa` and `df64cdbe` were brought into this isolated branch, retaining the original authorship. The `.gitignore` conflict was resolved by keeping both the current DVC/data protections and deployment-state exclusions. No cloud deployment or access change was performed.
- The Cloud Run frontend environment now uses `TASTEBRIDGE_HOST`, matching the current server/container contract. A pure configuration test checks the ingress and internal API settings without contacting Google Cloud.
- This README, evidence index and completeness checker make the missing MS3 proof explicit. No new hybrid model, serving-rule change, team allocation or claimed experiment result is introduced.

The proposed next model steps in the [MS2 model notes](../ms2/models/README.md#next-iteration-ms3) remain proposals. The inspected shared notes confirm Jenny's frontend/API integration contribution; no later adopted model replacement or finalized MS3 work split was established by the accessible sources. Unpushed teammate work and existing cloud executions remain unknown.

## Reproduce locally

From a fresh checkout, follow the [root app instructions](../../README.md#run-the-app). Python components use their committed `pyproject.toml` and `uv.lock`.

```sh
# Frontend and bundled API preflight
node frontend/prototype/scripts/check-setup.mjs
node frontend/prototype/scripts/build-prototype.mjs
node frontend/prototype/scripts/verify-release.mjs
node --test frontend/prototype/tools/verify-*.mjs

# Existing model/API tests; run each from its component folder
cd src/backend
uv run --frozen pytest -q
cd ../evaluation
uv run --frozen pytest -q
```

### Data, training and evaluation

Use the [pipeline guide](../ms2/datapipeline/) to obtain the licensed input files or the authorized DVC snapshot. Keep data and model exports out of Git. The expected processed inputs are `data/processed/books.parquet`, `interactions.parquet` and `manifest.json`.

From the repository root:

```sh
docker compose --profile pipeline build
docker compose --profile pipeline run --rm pipeline
```

This executes the existing local chain. The training service calls `evaluation.export` on all retained readers; evaluation independently fits/evaluates models using the reader split. The serving export is written to `data/artifacts/current/`, and evaluation writes configuration, metrics and logs under `src/evaluation/results/<run_id>/`. See [model parameters and run provenance](../ms2/models/README.md).

For a data-free evaluation smoke run, use `uv run python -m evaluation.run --synthetic` from `src/evaluation`. Label its outputs synthetic. It is not a cloud-training or production-data result.

### Deployment and API verification

The [Cloud Run guide](../../deploy/cloud-run/README.md) contains the existing image build, local smoke, deployment, rollback and log-access commands for `tastebridge-511403`, `us-central1`, `tastebridge-staging`. Use the prepared package rather than creating a competing deployment workflow.

```sh
# Requires the team's trained four-file export and a running Docker daemon
python3 deploy/cloud-run/deploy.py build /absolute/path/to/data/artifacts/current
python3 deploy/cloud-run/smoke.py --local
```

Cloud publication is a separate operator action after project access and publication are authorized. `publish` uploads images, updates a service and grants public invocation; `admin-setup.sh` changes IAM. Neither was executed during this preparation task. Confirm existing cloud runs/services with the responsible teammate before creating duplicates.

After an approved deployment, use its actual returned HTTPS origin:

```sh
curl --fail "$SERVICE_URL/api/health"
curl --fail --get "$SERVICE_URL/api/books/search" --data-urlencode 'q=Tolkien'
python3 deploy/cloud-run/smoke.py --url "$SERVICE_URL"
```

The smoke script discovers book IDs and checks both ranking modes and explanation references. Do not use the 52-book fixture IDs against the trained catalogue. The backend also exposes its endpoint documentation at `/docs` when accessed directly; browser requests go through the frontend's `/api` relay.

### Tracking and monitoring evidence

Attach a real run record with source commit, input/data version, parameters, metrics, execution identifier, output location and completion status. Add the tracking screenshot and cloud execution/configuration record under `docs/ms3/evidence/`; record whether the implementation is W&B/Vertex or a documented equivalent. This branch does not claim that file-based MS2 records satisfy the required cloud-training run.

After an approved service deployment, capture a responding API and the corresponding request/error or performance log. The deployment guide's Cloud Logging filters identify the target service; confirm the actual revision and model identity. Do not commit credentials, tokens, raw reader histories or dataset exports.

## Current verification limits

- Frontend: 80 tests and actual desktop/390px/320px flows passed; [full report](connections-ux-20261104/frontend-tests.tap).
- Backend: 77 tests passed in the current checkout.
- Existing model/evaluation package: 54 tests passed. Two UMAP warnings state that the fixed random seed uses one job; neither was a failure.
- MS3 evidence/configuration checks: `python3 -m unittest discover -s tools/tests`.
- Docker daemon: configured Colima socket is absent; this task did not rerun the real-model container smoke.
- Google Cloud CLI: not on PATH; no fresh cloud service, training execution or production log state was verified.
- Real processed data and trained export: absent locally. Historical MS2 evidence is retained as historical evidence.
- The separately hosted ChatGPT Site is a static 23-book UX review, not the model API deployment required for MS3.

## Final team handoff

1. Reconcile this branch and [architecture PR #11](https://github.com/cathyliu0510/AC215_TasteBridge/pull/11) through review; do not overwrite either workstream.
2. Confirm the training/workflow choice, existing cloud runs and responsible operators; collect the missing evidence rather than relabeling local fixtures.
3. Update [evidence/index.json](evidence/index.json), run the checker and component tests, then review the exact final diff.
4. The authorized maintainer creates/updates `milestone3` from the reviewed state and submits the full hash on Canvas. Prepare the required slides. This document does not perform or confirm those actions.
