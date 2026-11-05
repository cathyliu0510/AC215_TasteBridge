# Milestone 3: current status

Checked November 5, 2026 against the [official rubric](https://harvard-iacs.github.io/2026-AC215/milestone3/). The private `milestone3` preparation branch exists. The current application source is `2a87e200430a4b8eb15810cae591fb0c7661151c`; publication receipts distinguish it from the initial uploaded `59ef1a5`. The final documentation commit may be newer without changing these application bytes. Main and Canvas remain unchanged.

[Latest work and exact evidence](overnight-progress-20261105.md) · [Reproduce without retraining](reproduce.md) · [Review deck](presentation/TasteBridge-MS3-review.pptx) · [15-minute rehearsal](rehearsal.md) · [Operator handoff](operator-handoff.md).

## Requirement and evidence

| Requirement | Verified locally | Remaining requirement |
| --- | --- | --- |
| Tracked, reproducible serverless training | Two historical synthetic runs reproduce. Existing real team export retrieved and locked. New worker has offline tests and separate local runtime evidence | One successful serverless run or accepted equivalent, with execution, tracking and reproduction evidence. Existing team jobs are unreadable, so absence is unknown |
| Automated ML workflow | Existing Compose pipeline, local integration runner and [reviewable CPU-worker candidate](../../deploy/vertex-ms3/) | Reconcile existing team workflow and confirm any equivalent with the TF, then show a successful qualifying run |
| Deployed model/API | Exact 5,000-book export through current clean-checkout API, UI and local Linux/amd64 containers | Authorized live revision, matching model/image identities and teaching-staff access |
| Production monitoring | Actual local request and explicit local smoke-feedback logs | Revision-linked production request/error/performance evidence and log-access instructions |
| Documented, tested prediction API | [SPEC](../../src/backend/SPEC.md), both ranking rules, malformed inputs, missing/mismatched-model startup failure | Run the same checks against the authorized deployed endpoint |
| Code and presentation | Private preparation branch, updated frontend, source-bound evidence and editable 12-slide/900-second review deck | Close cloud gaps, team/native presentation review and submit reviewed full SHA on Canvas |

The rubric permits equivalents, makes multi-GPU conditional and does not require every stage in one workflow. An authenticated service with arranged TF access is acceptable. Basic Cloud Logging or equivalent meets minimum monitoring. A local run or static Site does not establish these cloud requirements.

## Current implementation

- Reading Desk `20261105.1`: favorites, responses, choice and view recover in the same origin/tab for up to 24 idle hours. Start over clears saved state after confirmation. Search text, full book metadata, credentials and sent-feedback status are not saved. Explicit shared URLs take priority. Saved opinions are discarded when the model fingerprint changes.
- Title/author search ignores accents and common punctuation differences. A frozen search index is built once when the model loads. Original text, result order and scoring remain unchanged; user queries are not cached.
- The backend hashes the same four model buffers it loads. Health and recommendations expose the fingerprint; feedback rejects stale model identity before writing. Invalid factors and malformed exports fail startup clearly.
- Local container packaging validates the reviewed model lock. Future publication checks private registry/project policy and preserves invocation settings and records prior traffic for rollback. No Google Cloud deployment or IAM command was executed.
- Evidence binding records a recursive 124-file source manifest and all four artifact hashes. A binding verifies file bytes, not that a screenshot action or test actually ran; separate reports record those actions.

## Exact-model validation

The recovered team export is `b2-als-gr-317756d1a1ad`, data `gr-317756d1a1ad`, 5,000 works, 9,896 readers and 499,915 interactions. Its canonical four-file fingerprint is `cb4457b668e3561692d557a44a54378966fc400719120162c2838a76258e0164`. [Reviewed artifact lock](evidence/identity-handoff-20261105/artifact-lock.json) · [DVC retrieval ledger](evidence/team-serving-20261105/team-model-retrieval.json).

[Clean current source acceptance](evidence/overnight-20261105/serving-2a87e20/evidence-binding.json) covers API/relay checks, 13 additional HTTP cases, two fail-closed startup probes and actual desktop/320px choice recovery. [Current local images](evidence/overnight-20261105/containers-2a87e20/local-smoke.json) match the release image IDs. The [extended browser pass](evidence/overnight-20261105/serving-ccda4b6/browser-checks.json) records manual five-favorite selection, both ranking rules, choice revocation, accented search and clear/recovery at earlier source `ccda4b6`; its frontend bytes match current source. Do not relabel earlier screenshots as later executions.

Latest suites: **107 frontend, 124 backend, 68 integration-tool and 36 offline-worker tests passed**. Historical November 4 preprocessing/evaluation reports remain 122/54; they are not new runs. The bounded native search benchmark is an in-process comparison, not production latency. Inherited catalogue year fields have not been independently validated.

## Reproduce and review

Use [reproduce.md](reproduce.md) first. It separates existing-export serving from optional synthetic training. Model/data files remain ignored and are not included in Git or the public Site.

```sh
node --test frontend/prototype/tools/verify-*.mjs
uv --directory src/backend run --frozen pytest -q
python3 -m unittest discover -s tools/tests
python3 -m unittest discover -s deploy/vertex-ms3/tests
python3 tools/check_ms3.py
```

The final checker intentionally reports incomplete cloud/presentation/submission evidence. It validates coverage and file presence only. A green path check cannot certify cloud execution or Canvas submission.

## Hosted frontend and next actions

The [original public Site](https://tastebridge-prototype.landenini.chatgpt.site/) is now Site version **7**, frontend **20261105.1**, with its established public audience and ownership unchanged. It contains only the 23-book static demo; model weights, reader histories, team documents and private API credentials are excluded. [Deployment and rollback receipt](evidence/overnight-20261105/site-static-release/deployment.json). Version 6 remains available for rollback.

Existing ADC permits the team GCS export read, but service/job/pipeline/registry reads and a bounded production-log read returned 403. No cloud-state absence was established. [Read-access evidence and exact remaining operator actions](operator-handoff.md). Check the existing team run/service/tracker first; do not duplicate training merely to fill a checklist.

[Architecture PR #11](https://github.com/cathyliu0510/AC215_TasteBridge/pull/11) remains a separate review stream. Do not overwrite it. Finish the evidence and team review, then submit the reviewed full `milestone3` SHA by **November 12, 10pm Eastern**, with a 15-minute presentation. No main merge or Canvas submission is included here.
