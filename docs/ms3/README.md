# Milestone 3 requirements and current evidence

Reviewed November 11, 2026 against the [official course instructions](https://harvard-iacs.github.io/2026-AC215/milestone3/) and their [source](https://github.com/Harvard-IACS/2026-AC215/blob/main/milestone3.md). The deployed application is pinned to commit `5184a6c836b2988f18f1f9586bb0ebf1a43f2731`; later documentation commits do not change its runtime bytes.

## Jenny's responsibility

The November 9 TF meeting assigned Jenny and Nikhil the Cloud Run backend deployment, followed by a deployed curl screenshot and cloud monitoring evidence. Jenny's completed work covers the frontend/API boundary, exact-model validation, containers, deployed prediction and cloud logs. The private service is live; the teaching-staff account's own invocation access remains to be confirmed. Team training and pipeline ownership stay with the teammates already doing that work; everyone still needs to understand the complete system for individual questions.

## Requirement check

| Requirement | Evidence now | What is still needed |
| --- | --- | --- |
| Tracked reproducible serverless training | PR #13 documents Vertex job `3911991530436427776` and W&B run `zijfiixh` | Direct successful-job/tracker evidence and required screenshot, tied to code, image, data and settings; integrate team files into final branch |
| Automated ML workflow | Shared KFP code at `d05a6be`, including run-ID fix | Successful qualifying execution and matching graph/output evidence; README run instructions remain incomplete |
| Deployed model/API | Ready revision `tastebridge-staging-00002-vzn`, full live smoke, model/image identity and real prediction screenshots | Teaching-staff account invocation confirmation |
| Production monitoring | Actual revision-linked request and one explicit test feedback log; access/query instructions | No extra setup required for basic logging evidence; retention was not audited |
| Documented and tested prediction API | SPEC, 108 frontend, 124 backend, 79 tools tests; local and live smoke, independent curl | Preserve exact evidence when integrating team changes |
| README and evidence | MS2 changes and runbook links now explicit in this candidate | Final merged source, required screenshots and removal of stale completion claims |
| Submission and presentation | `milestone3` exists; November 5 review deck available | Final reviewed full SHA on Canvas by November 12 at 10 PM ET, and refreshed 15-minute team slides |

The rubric allows one successful training run, a workflow covering any of preprocessing/training/evaluation, and authenticated teaching-staff access. Multi-GPU is conditional. The TF accepted selecting one serving model if the team explains the choice. A new GPU job, public access or serving all models is not required to close Jenny's part.

## What has actually passed

[Live November 11 evidence](evidence/deployed-serving-20261111/): clean deployed commit `5184a6c836b2988f18f1f9586bb0ebf1a43f2731`, 108 frontend tests, four release routes, 124 backend tests and 79 tool tests (311 unique tests). Both local container smoke and authenticated live smoke passed. Independent curl verified both ranking modes, exact fingerprint, private-route 404s and anonymous 403. Real browser checks verified the five-pick flow, reasons, shared choice, reload recovery and connections. The earlier 51 targeted tests are included in 79, not additional.
The locked export is B2 ALS `b2-als-gr-317756d1a1ad`, data `gr-317756d1a1ad`, 5,000 books, fingerprint `cb4457b668e3561692d557a44a54378966fc400719120162c2838a76258e0164`. [Original DVC ledger](evidence/team-serving-20261105/team-model-retrieval.json) · [artifact lock](evidence/identity-handoff-20261105/artifact-lock.json).

The published summary is derived from original release/deployment/smoke receipts, actual curl responses and Cloud Logging records. It distinguishes local image IDs from immutable registry digests. Historical local-only evidence is retained with its original scope.

## Current cloud and branch facts

- Project/repository IAM checks now pass with no public bindings. Runtime identity and required serving permissions were verified. Older November 5 blanket-permission statements are historical.
- `tastebridge-staging` is Ready with 100% traffic on `tastebridge-staging-00002-vzn`. See the live evidence above. Teaching-staff account access is not yet independently verified.
- Ancestor IAM reads were not retried. The operator explicitly confirmed no public access and compliance before publication. Direct project/repository checks passed before each image push and service update. No policy changes were made.
- Final serving integration is based on remote `milestone3` at `46f6622d9ca9e211113df63b122349af1c708b1a`, with the existing serving-readiness fix and the namespaced health-route repair. Final remote publication must be checked after push; a local commit is not a submission receipt.
- [PR #13](https://github.com/cathyliu0510/AC215_TasteBridge/pull/13) remains open/draft at `d05a6be2404555cee3cc872f4ce971c55ed2d332`. Its standalone training success does not prove the full pipeline succeeded or that M1 is served.
- [Architecture PR #11](https://github.com/cathyliu0510/AC215_TasteBridge/pull/11) merged to `main` on November 9 at `37ea20bd0b57523c1f5715c8de61aea4584648fc`. It is not a still-open PR, and main is not the submission branch.

## Finish without overstating progress

Use [Jenny's serving and evidence handoff](jenny-serving-handoff-20261111.md). Deployment, actual predictions and cloud logs are complete. Confirm teaching-staff invocation access without making the service public. Keep any new logs free of tokens and reader history.

Use the existing training owner's evidence rather than rerunning training. Review and integrate the team branches; retest the actual final combined source. Refresh the old deck using [current speaking notes](jenny-presentation-notes-20261111.md). Verify the full remote `milestone3` SHA and Canvas receipt separately. The November 16 presentation meeting does not move the November 12 submission deadline.

`python3 tools/check_ms3.py` checks manifest coverage and file presence only. It should continue reporting incomplete team training/workflow/presentation or staff-access evidence until those specific gaps are closed. Do not turn its cells green because documentation or a screenshot placeholder exists.
