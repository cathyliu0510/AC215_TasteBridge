# Current MS3 delivery and evidence

Updated November 5, 2026. Current app source: `2a87e200430a4b8eb15810cae591fb0c7661151c`. Documentation/evidence commits may be newer while retaining those application bytes. The private preparation branch exists; the [initial after-upload receipt](evidence/overnight-20261105/github-initial-upload.json) verifies `59ef1a5`. Final remote publication is checked separately. Main, repository sharing and Canvas remain unchanged.

## Frontend

[Open the original public Site](https://tastebridge-prototype.landenini.chatgpt.site/) · [release/rollback receipt](evidence/overnight-20261105/site-static-release/deployment.json).

Site version 7 serves Reading Desk `20261105.1` with the established public access and owner. Version 6 is retained for rollback. The public payload contains the 23-book static demo only; the real model, reader data, team documents and credentials are excluded.

The current frontend restores favorites, ranking, opinions and shared choice after a refresh in the same tab/origin for up to 24 idle hours. It saves IDs and model identity rather than queries or full catalogue metadata. Explicit shared URL selections take priority once. Start over confirms before clearing; invalid, expired or unavailable storage recovers safely. A changed model fingerprint clears unverified opinions/choice. Legacy APIs without a fingerprint retain favorites only. Feedback remains an explicit action and its sent status is not saved.

Search accepts accented/unaccented names and common punctuation differences. The backend precomputes immutable catalogue search keys at startup. It keeps original display text, results and ordering, without caching user queries. The ALS serving rule is unchanged.

## Actual model and local execution

The retrieved existing DVC export has 5,000 works, 9,896 readers and 499,915 interactions. Its four-file fingerprint is `cb4457b668e3561692d557a44a54378966fc400719120162c2838a76258e0164`. [Retrieval/provenance](evidence/team-serving-20261105/team-model-retrieval.json) · [artifact lock](evidence/identity-handoff-20261105/artifact-lock.json).

| Evidence | Exact scope |
| --- | --- |
| [Clean current acceptance](evidence/overnight-20261105/serving-2a87e20/evidence-binding.json) | Clean source `2a87e20`, current API/relay, both rankings, 13 additional HTTP checks, missing/mismatched-model startup failures, desktop and actual 320px shared-choice refresh recovery |
| [Current images and smoke](evidence/overnight-20261105/containers-2a87e20/local-smoke.json) | Actual Linux/amd64 build; running frontend/backend image IDs match release; exact locked model; one explicit local-only feedback test to owned container stdout |
| [Extended browser acceptance](evidence/overnight-20261105/serving-ccda4b6/browser-checks.json) | Earlier clean source `ccda4b6`, same current frontend bytes; manual five favorites per reader, reasons, choice, revocation, ranking, accent search, Start over and desktop/phone recovery |
| [Search measurement](evidence/overnight-20261105/search-performance/search-benchmark.json) | Bounded native in-process comparison over 5,000 books; startup work replaces per-query normalization. It is not a production latency benchmark |
| [Presentation review](evidence/overnight-20261105/presentation-qa/visual-review.json) | Final editable 12-slide deck, 900-second notes, four native tables, structural/layout/import checks and all slides individually inspected after rendering |

Each serving binding records the recursive 124-file source manifest, all four model hashes and supplied screenshot/log/test bytes. Byte binding alone cannot prove browser actions or test execution; those have separate reports. Current acceptance reused an existing locked environment and the already verified export; it did not repeat dependency installation or a fresh DVC pull. The literal `make app` path was not used. The current container smoke is separate actual packaging evidence.

The old Docker report used the same model label but different vector, coordinate and metadata hashes, as well as different application source. It remains historical. No new real-data training or Goodreads-quality gain is claimed. Some inherited catalogue year fields need data-quality review.

## New worker runtime

The [worker candidate](../../deploy/vertex-ms3/) wraps the existing exporter/evaluator, preserves original 128-factor/15-iteration/50-regularization/20-alpha/42-seed parameters, checks source/input/output hashes, isolates processed input copies and shares one runtime budget across stages. Its generated request submits nothing and omits activation/persistence flags.

The [first actual local invocation](evidence/overnight-20261105/workflow-runtime/pass20/runtime-verification.json) completed once in a network-disabled Linux/amd64 container, with two CPUs and 2 GB memory, in **431.36 seconds**. It used the existing synthetic processed cache: 160 works, 395 readers and 9,072 interactions. Evaluation split readers 316/40/39 and had 23 eligible held-out readers. The requested 300 pairs yielded **126 actual pairs, 63 similar and 63 different**, because the existing sampler caps finite eligible combinations. Nine aggregate metric groups were produced. These are integration results, not a real-data quality experiment.

[Selected receipt](evidence/overnight-20261105/workflow-runtime/pass20/selected-evidence/receipt.json) · [selected-file audit](evidence/overnight-20261105/workflow-runtime/pass20/selected-evidence-audit.json) · [actual image/default-entrypoint dry run](evidence/overnight-20261105/workflow-runtime/runtime-verification.json).

Input and source hashes stayed unchanged. Owned containers were removed; no reader-level outputs, favorites, arrays/catalogue copies or private subprocess logs were copied into this evidence package. No remote persistence, cloud job, image upload or online tracker ran. The team/TF still needs to accept any workflow/tracking equivalent and reconcile existing team jobs first.

## Verification and remaining work

Ten distinct agents contributed implementation or independent review, followed by targeted repairs and actual acceptance. Latest reports: [107 frontend tests](evidence/overnight-20261105/frontend-tests.txt), [124 backend tests](evidence/overnight-20261105/search-performance/backend-tests.txt), [68 integration-tool tests](evidence/overnight-20261105/tools-tests-final.txt) and [36 offline-worker tests](../../deploy/vertex-ms3/offline-verification.json). The separate historical reproducibility runs and November 4 preprocessing/evaluation suites retain their dates.

Cloud Run service, Vertex job/pipeline, Artifact Registry and bounded production-log reads returned 403. This establishes denied visibility, not absence of completed team resources. No Google Cloud training, deployment or IAM write, paid job, new credential or Canvas submission occurred. The user-requested original Site update is independently verified above.

The next useful input is existing team job, tracker, workflow and service/revision evidence, or appropriate read-only visibility. If no qualifying system exists, the team must choose the accepted approach and authorize the required cloud execution. Then verify the exact model/images, TF access and production logs. Finish native presentation/team review and submit the reviewed full milestone3 SHA by **November 12, 10pm Eastern**. [Exact operator actions](operator-handoff.md) · [official requirements](https://harvard-iacs.github.io/2026-AC215/milestone3/).
