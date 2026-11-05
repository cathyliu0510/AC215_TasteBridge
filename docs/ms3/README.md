# Milestone 3: integration readiness

Checked November 5, 2026 against the [official MS3 instructions](https://harvard-iacs.github.io/2026-AC215/milestone3/) and the remote repository. **This is a preparation branch, not a completed submission.**

Remote `main` and `milestone2` both point to `fccfbac53a96de18b71ca1c3f668a6bea115e51e`; a fresh remote check still lists no `milestone3` branch. The course requires that branch and its full commit hash on Canvas by **November 12, 10pm ET**, plus a 15-minute TF presentation with slides. A [12-slide review deck](presentation/TasteBridge-MS3-review.pptx), [15-minute rehearsal plan](rehearsal.md) and [local evidence package](evidence/local-integration-20261104/) now exist. The deck retains the missing cloud evidence explicitly. No Canvas or remote submission was performed.

## Requirement → evidence → gap

| Area | Available implementation/evidence | Remaining evidence |
| --- | --- | --- |
| Tracked, reproducible serverless training | [Two reproducible local synthetic fits with source/configuration/input hashes](evidence/local-integration-20261104/runs/) · [Existing MS2 results](../ms2/models/runs/) | A successful cloud training execution, approved tracking record and screenshot; local files do not establish cloud execution |
| Deployed model/API | [Cloud Run preparation](../../deploy/cloud-run/) · [historical local container verification](../../deploy/cloud-run/verification.local.json) | Authorized deployment URL, revision/configuration and request/response screenshot |
| Automated ML workflow | [One-command local B2 integration](reproduce.md) and the existing [Compose pipeline](../ms2/datapipeline/) | Implement/adapt and execute the selected cloud workflow, or document the accepted equivalent with the TF |
| Production monitoring | [Actual local model/API request logs](evidence/local-integration-20261104/runs/run-a/backend.log) · Cloud Logging configuration in the deployment guide | Actual deployed logs, access instructions and a captured example |
| Documented, tested prediction API | [SPEC](../../src/backend/SPEC.md) · [actual trained-synthetic HTTP checks](evidence/local-integration-20261104/runs/run-a/api-check.json) · component suites | Run the same contract checks against the authorized deployed service |

[Evidence index](evidence/index.json) is intentionally incomplete. Run `python3 tools/check_ms3.py` to list gaps; a nonzero result means the recorded submission evidence is not complete. The checker validates manifest coverage and repository-relative evidence paths; it does not certify cloud execution, screenshot contents or Canvas submission.

## Current delivery pass

See the [current team audit and next actions](team-audit-20261105.md), with the [November 4 execution record](next-steps-20261104.md) retained as historical evidence. The full review copy now includes the same frontend `20261104.6` as the original public Site. Actual serving checks now also reuse the existing 5,000-book team DVC export without retraining. [Hash/provenance ledger, HTTP results and desktop/mobile checks](evidence/team-serving-20261105/). Cloud publication code preserves access rather than granting public invocation. These local changes do not close any cloud/submission gate.

## What changed after MS2

- [One-command local integration](reproduce.md) reuses preprocessing, B2 export, held-out evaluation, the backend and the real frontend relay. It preserves prior output, records source/input/artifact hashes and failures, and isolates its loopback services. Two clean runs reproduce raw/processed/vector/projection/metric outputs and API rankings. [Actual evidence](evidence/local-integration-20261104/).
- Seeded synthetic gzip output now fixes the timestamp and filename header, making compressed input hashes reproducible across clock/destination changes. The smoke verifier supports actual catalogue IDs and checks ranking/coordinate consistency with the API's four-decimal serialization.
- A `20261104.5` identifies trained-synthetic exports in the footer. No model algorithm or B ranking rule changed. The [12-slide deck](presentation/TasteBridge-MS3-review.pptx) contains source notes, native tables/diagrams and actual UI evidence; native Keynote/PowerPoint rendering remains unverified after Keynote application control timed out.
- Local A `20261104.4`: search shortcuts follow loading state and clear-search consistently cancels old requests/timers, preserving both shelves. [Current local verification and Chrome limitation](local-continuation-20261104.md). At that earlier step the hosted preview remained `20261104.3`; the original public Site is now `20261104.6` (see the current handoff).
- Reading Desk A `20261104.3`: [named book connections, response/choice state, responsive checks and independent UX review](connections-ux-20261104.md). The model scores and returned coordinates are preserved. B remains the comparison.
- Frontend prerequisite checks, explicit container host configuration and cancellation/child-process cleanup: [local setup record](local-readiness.md).
- Existing Cloud Run preparation commits `3b7dafa` and `df64cdbe` were brought into this isolated branch, retaining the original authorship. The `.gitignore` conflict was resolved by keeping both the current DVC/data protections and deployment-state exclusions. No cloud deployment or access change was performed.
- The Cloud Run frontend environment now uses `TASTEBRIDGE_HOST`, matching the current server/container contract. A pure configuration test checks the ingress and internal API settings without contacting Google Cloud.
- This README, evidence index and completeness checker make the missing MS3 proof explicit. No new hybrid model, serving-rule change, team allocation or Goodreads-quality claim is introduced.

The proposed next model steps in the [MS2 model notes](../ms2/models/README.md#next-iteration-ms3) remain proposals. The inspected shared notes confirm Jenny's frontend/API integration contribution; no later adopted model replacement or finalized MS3 work split was established by the accessible sources. Unpushed teammate work and existing cloud executions remain unknown.

## Reproduce locally

Start with the [complete trained-model integration guide](reproduce.md), including locked environment setup, synthetic/approved-data modes and actual evidence outputs. From a fresh checkout, the [root app instructions](../../README.md#run-the-app) cover the simpler app launcher. Python components use their committed `pyproject.toml` and `uv.lock`.

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

Cloud publication is a separate operator action after project access and publication are authorized. `publish` uploads images and updates a service while preserving IAM and access settings; `admin-setup.sh` changes IAM. Neither was executed during this preparation task. Confirm existing cloud runs/services with the responsible teammate before creating duplicates.

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

- Frontend: 82 tests passed; [current report](evidence/local-integration-20261104/frontend-tests.tap). The [Book connections review](connections-ux-20261104.md) retains the earlier full visual pass, and the [new trained-model evidence](evidence/local-integration-20261104/) records current desktop/320px checks.
- Preprocessing: 122 tests passed. Local integration/evidence tools: 14 tests passed. Two complete training/evaluation/HTTP runs passed with matching hashes/rankings in this environment.
- Backend: 77 tests passed in the current checkout.
- Existing model/evaluation package: 54 tests passed. Two UMAP warnings state that the fixed random seed uses one job; neither was a failure.
- MS3 evidence/configuration checks: `python3 -m unittest discover -s tools/tests`. The evidence completeness checker intentionally still fails while cloud/submission proof is absent.
- Docker daemon: configured Colima socket is absent; this task did not rerun the real-model container smoke.
- Google Cloud CLI: not on PATH. Existing ADC supports read-only GCS retrieval; service/job metadata calls return IAM 403. Cloud service, training and production state remain unverified.
- Real processed tables remain absent. The existing team four-file model export was retrieved into ignored local runtime storage and verified; historical training evidence remains historical.
- The separately hosted ChatGPT Site is a static 23-book UX review, not the model API deployment required for MS3.

## Final team handoff

1. Reconcile this branch and [architecture PR #11](https://github.com/cathyliu0510/AC215_TasteBridge/pull/11) through review; do not overwrite either workstream.
2. Confirm the training/workflow choice, existing cloud runs and responsible operators; collect the missing evidence rather than relabeling local fixtures.
3. Update [evidence/index.json](evidence/index.json), run the checker and component tests, then review the exact final diff.
4. The authorized maintainer creates/updates `milestone3` from the reviewed state and submits the full hash on Canvas. Finalize the review slides with actual cloud evidence and a native presentation check. This document does not perform or confirm those actions.

The [operator handoff](operator-handoff.md) lists exact inputs, missing access and the remaining implementation/evidence. GitHub audience and write access are now verified; see the current audit for the requested preparation branch publication status. The Keynote control card is unrelated. No main merge, sharing change or Canvas submission is included.

Latest independent continuation: [exact artifact identity, deployment/evidence sequence and read-access gaps](deployment-evidence-handoff-20261105.md), with [presentation integration manuscript](presentation-integration-20261105.md). GitHub push remains paused.
