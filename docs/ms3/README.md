# Milestone 3 requirements and current evidence

Reviewed November 11, 2026 against the [official course instructions](https://harvard-iacs.github.io/2026-AC215/milestone3/) and their [source](https://github.com/Harvard-IACS/2026-AC215/blob/main/milestone3.md). The deployed application is pinned to commit `5184a6c836b2988f18f1f9586bb0ebf1a43f2731`; later documentation commits do not change its runtime bytes.

## Jenny's responsibility

The November 9 TF meeting assigned Jenny and Nikhil the Cloud Run backend deployment, followed by a deployed curl screenshot and cloud monitoring evidence. Jenny's completed work covers the frontend/API boundary, exact-model validation, containers, deployed prediction and cloud logs. The private service is live; the teaching-staff account's own invocation access remains to be confirmed. Team training and pipeline ownership stay with the teammates already doing that work; everyone still needs to understand the complete system for individual questions.

## Requirement check

| Requirement | Evidence now | What is still needed |
| --- | --- | --- |
| Tracked reproducible serverless training | **Run complete.** Vertex job `3911991530436427776`, W&B run `zijfiixh`, code/image/data/settings and CPU/T4/local reproducibility are recorded in the [training record](https://github.com/cathyliu0510/AC215_TasteBridge/blob/8bb0a750a161142298654bcd641b93813ea98b8e/deploy/twotower/README.md#reproducibility-record), with [job/tracker screenshots](https://github.com/cathyliu0510/AC215_TasteBridge/tree/8bb0a750a161142298654bcd641b93813ea98b8e/docs/ms3/two-tower) | Source and captured evidence are integrated and the manifest is reconciled; preserve the pinned records when checking the published team SHA; no additional training run is needed |
| Automated ML workflow | **Both branches ran.** M1 `tastebridge-train-twotower-20261109172259`: 5/5 steps, least misery `0.0468`, gate passed and model published. ALS `tastebridge-train-als-20261110212016`: 4/5 steps, `0.0236 < 0.042`, publication intentionally skipped. [Run commands, results and graph/output links](https://github.com/cathyliu0510/AC215_TasteBridge/blob/8bb0a750a161142298654bcd641b93813ea98b8e/deploy/twotower/README.md#ml-pipeline-vertex-ai-pipelines) are complete; [ALS screenshots](https://github.com/cathyliu0510/AC215_TasteBridge/tree/3749ed90bd2a948e1fa45e01c7439e43c9af4a02/docs/ms3/pipeline) are in PR #14 | PR #13 and PR #14 are merged and their evidence is reconciled; record the checker result for the exact published team SHA |
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

- Direct project/repository checks found no public bindings. Runtime identity and required serving permissions were verified; authentication remains required.
- `tastebridge-staging` is Ready with 100% traffic on `tastebridge-staging-00002-vzn`. See the live evidence above. Teaching-staff account access is not yet independently verified.
- Inherited privacy is operator-confirmed; direct project/repository policies were checked. No policy changes were made.
- Serving integration and live evidence are published on `milestone3` at `73d60fbb37f89fb619cfc04b9f2b6907e75421df`. [Remote verification](evidence/remote-refs-20261111.json). Documentation-only updates do not change the deployed application. Verify the final team SHA separately for Canvas submission.
- [PR #13](https://github.com/cathyliu0510/AC215_TasteBridge/pull/13) merged on November 11 at 16:06:25 UTC as [`5c04926f1656228dc05361f18c5e204327b1cdee`](https://github.com/cathyliu0510/AC215_TasteBridge/commit/5c04926f1656228dc05361f18c5e204327b1cdee); [PR #14](https://github.com/cathyliu0510/AC215_TasteBridge/pull/14) merged at 16:11:52 UTC as [`0964874b155b4842cf24e6fa1f0a6a53ad5bc314`](https://github.com/cathyliu0510/AC215_TasteBridge/commit/0964874b155b4842cf24e6fa1f0a6a53ad5bc314). The recorded M1 pipeline passed and published `m1-tt-gr-317756d1a1ad-tastebridge-train-twotower-20261109172259` to the model bucket. The ALS run exercised the intended gate rejection and did not publish a candidate. **M1 is published, not served**: the live application still serves the locked B2 ALS champion; M1 remains the challenger. These run results do not themselves merge either PR or switch the serving model.
- [Architecture PR #11](https://github.com/cathyliu0510/AC215_TasteBridge/pull/11) merged to `main` on November 9 at `37ea20bd0b57523c1f5715c8de61aea4584648fc`. It is not a still-open PR, and main is not the submission branch.

## Finish without overstating progress

Use [Jenny's serving and evidence handoff](jenny-serving-handoff-20261111.md). Deployment, actual predictions and cloud logs are complete. Confirm teaching-staff invocation access without making the service public. Keep any new logs free of tokens and reader history.

Use the completed training/workflow evidence rather than rerunning training. PR #13 and dependent PR #14 are merged; their M1 and ALS source/capture paths and this summary/manifest reconciliation are available together. Record the exact published `milestone3` SHA and `python3 tools/check_ms3.py` result. The earlier disposable local combination and intermediate checks do not replace this actual team-branch check. Refresh the old deck using [current speaking notes](jenny-presentation-notes-20261111.md). Verify the full remote `milestone3` SHA and Canvas receipt separately. The November 16 presentation meeting does not move the November 12 submission deadline.

`python3 tools/check_ms3.py` checks manifest coverage and file presence only. Training/workflow entries reference the actual records, code and captures integrated by PR #13 and PR #14. This does not claim a fresh cloud run, provider verification, staff access or Canvas submission. Teaching-staff invocation and the refreshed presentation remain separate gaps. Record the exact published team SHA and checker result; do not turn cells green because a screenshot placeholder exists.
