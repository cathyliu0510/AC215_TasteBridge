Updated November 5, 2026. This manuscript matches the editable review deck and retains the cloud evidence gaps. Total timing: 900 seconds.

# 1

::: notes
Timing: 45 seconds.

The existing 5,000-book team model now works with Reading Desk release 20261105.1. We verified local HTTP, browser recovery and the current Linux/amd64 containers. Cloud training, the deployed service and production monitoring still need evidence. The separate public Site remains a 23-book static demo. The app source for the latest container check is 2a87e200430a4b8eb15810cae591fb0c7661151c. The initial milestone3 upload was verified at 59ef1a5; any later branch update requires a separate remote verification. No Canvas submission occurred. Sources: docs/ms3/evidence/overnight-20261105; docs/ms3/evidence/overnight-20261105/github-initial-upload.json; https://harvard-iacs.github.io/2026-AC215/milestone3/.
:::

# One export drives the API and interface

::: notes
Timing: 75 seconds.

The backend reads books.json, item_embeddings.npy, coords_2d.npy and meta.json together. Their hashes match the pinned team DVC directory. The API now reports a fingerprint calculated from the exact four file buffers loaded at startup. A model label alone is insufficient: the old Docker report used the same name with different vectors, coordinates and metadata. Sources: src/backend/app/artifacts.py; docs/ms3/evidence/identity-handoff-20261105/identity-audit-v2.json; current container release record.
:::

# Two synthetic runs reproduce the same outputs

::: notes
Timing: 75 seconds.

These are two historical clean synthetic runs in the same environment at source e8a3128. Their recorded input, processed tables, model outputs, metrics and responses support the stated local reproducibility result. They are separate from the current 5,000-book serving check. The stronger comparator also checks catalogue, configuration, parameters and complete request/response semantics. No cross-platform bitwise reproduction or new model-quality result is claimed. Sources: local-integration-20261104/runs/reproducibility.json; tools/summarize_integration.py and its regressions.
:::

# Evaluation and serving use separate fits

::: notes
Timing: 90 seconds.

The existing team serving export records 5,000 books, 9,896 users, 499,915 interactions, 128 factors and 15 iterations. The synthetic integration used 160 books, 395 retained users, 16 factors and 8 iterations. Evaluation fits training users and scores held-out readers; the serving export refits all retained users. The historical real-data split was 7,917/990/989. We did not retrain the real model. Sources: team-model-retrieval.json; historical-evaluation-context.json; evaluation/export.py and run.py.
:::

# The evaluator records both ranking rules

::: notes
Timing: 75 seconds.

All visible metrics come from synthetic input and 20 simulated pairs. They test metric generation rather than Goodreads quality. For context, the historical tuned B2 average Min-Recall@10 was 0.0432 and least-misery 0.0236. The historical item-kNN baseline did better. Evaluation uses a training-user fit, while serving uses the all-reader export. Sources: docs/ms2/models/runs/test-tuned-f128-r50; saved synthetic evaluation-summary.csv. Keep those results separate.
:::

# Existing team model in the Reading Desk

::: notes
Timing: 120 seconds.

The screenshots show the real team model through the current frontend. Desktop and 320px phone checks verified both reader reasons, Interested, explicit shared choice and return to the shortlist. Refresh restored the favorites and choice. A subsequent Pass revoked the choice, and it stayed revoked after another refresh. A separate manual flow chose five Mieville books and five Agatha Christie books, then selected The Prestige. Search works with and without accents. Search text is not saved. No browser feedback event was sent. These screenshots are bound to the ccda4b6 source manifest and all four model hashes; the later backend search index leaves frontend bytes unchanged. Sources: serving-ccda4b6/browser-checks.json and evidence-binding.json.
:::

# The API contract checks actual responses

::: notes
Timing: 75 seconds.

The actual model API passed both ranking modes, unique non-favorite results, reader-specific references, finite scores, aggregation ordering, map coordinates and private-route isolation. Health and recommendation responses share the exact artifact fingerprint. The small contract check uses two known IDs; browser flows use five favorites per reader. Clean-checkout acceptance adds malformed and unknown-ID requests and explicit model-startup failures. Source: current acceptance and container smoke records; src/backend/SPEC.md.
:::

# Tests cover each integration boundary

::: notes
Timing: 60 seconds.

These are dated checks for the current local candidate, rather than evidence of cloud execution. The frontend has 107 passing tests, backend 124, integration tools 68 and offline workflow candidate 36. The two complete training runs are the historical synthetic runs. Existing preprocessing122 and evaluation54 reports remain available from November 4; they are not presented as fresh tests here. Sources: frontend-tests.txt; search-performance/backend-tests.txt; tool and workflow receipts. Any later changed source must be verified again. A separate first actual worker invocation now completed local synthetic training and evaluation in a network-disabled Linux/amd64 container: 160 books, 128 factors, 15 iterations, and 126 sampled pairs from 23 eligible held-out readers. It requested 300 pairs, but the existing sampler capped the finite eligible combinations. This is runtime integration evidence, not real-data quality or cloud execution. Source: evidence/overnight-20261105/workflow-runtime/pass20/runtime-verification.json.
:::

# Current export and deployment evidence

::: notes
Timing: 75 seconds.

We built and tested the current Linux/amd64 images from app source 2a87e20, using the locked export fingerprint cb4457b668e3. The actual running image IDs match the release record. Search now uses catalogue keys built once at startup, preserving result order and display text without caching user queries. The old Docker result remains historical. The Cloud Run service, training jobs, pipelines and registry reads returned 403; absence is not established. Publication preserves invocation policy, requires a reviewed private registry and records actual prior traffic for rollback. Sources: containers-2a87e20; search-performance; deploy/cloud-run.
:::

# Production logging still needs cloud evidence

::: notes
Timing: 60 seconds.

The displayed lines are actual local container requests, not a production latency benchmark. The local smoke sent one explicit test vote into its owned container stdout and removed its containers afterward. Browser QA sent no feedback. A bounded production-log query returned 403 without identifying the missing permission. We still need a real cloud revision, a matching request/error/performance event and approved log access. Sources: containers-2a87e20/container-smoke-2a87e20.log; cloud-readiness.json; backend request middleware.
:::

# MS3 evidence still has cloud requirements

::: notes
Timing: 75 seconds.

The rubric requires one successful tracked reproducible serverless run or an accepted equivalent. Multi-GPU is conditional. A qualifying automated workflow need not contain every stage. Authenticated teaching-staff service access is acceptable, and basic Cloud Logging or equivalent meets minimum monitoring. The new worker is a candidate pending team reconciliation, qualifying cloud execution evidence and acceptance of its tracking/workflow approach. Local receipts and test runs cannot close the cloud cells. Source: https://harvard-iacs.github.io/2026-AC215/milestone3/; evidence/index.json; deploy/vertex-ms3/README.md.
:::

# Remaining cloud evidence and team review

::: notes
Timing: 75 seconds.

The milestone3 preparation branch exists and main remains unchanged. First collect and reuse existing cloud run, workflow and tracker records. Then an authorized operator verifies the current model images, cloud revision, staff access and production logs. Finish the team review and presentation, then submit the reviewed full commit hash on Canvas. Deadline: November 12 at 10pm Eastern, with a 15-minute team presentation. This deck remains a review draft while cloud evidence is missing. Sources: docs/ms3/evidence/overnight-20261105/github-initial-upload.json, current MS3 runbook and official rubric.
:::
