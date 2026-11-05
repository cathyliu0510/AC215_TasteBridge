# MS3: November 4 execution record

Historical snapshot. The [November 5 team audit](team-audit-20261105.md) supersedes its GitHub, export-availability and cloud-visibility conclusions.

The next priority is a verifiable cloud-backed system. The original [public frontend](https://tastebridge-prototype.landenini.chatgpt.site/) is at `20261104.6`, but remains a separate 23-book static demonstration. This local review copy integrates that same interface with the existing backend and prepares the deployment handoff. It has no remote configured; the original worktree and its denied GitHub push remain untouched.

The [official MS3 rubric](https://harvard-iacs.github.io/2026-AC215/milestone3/) requires a tracked reproducible serverless training run, an automated ML workflow, a deployed prediction API and production monitoring, with reproducibility/deployment instructions and running-system evidence. Delivery uses `milestone3` and a full commit hash on Canvas by **November 12, 10pm ET**, with a **15-minute TF presentation**. Vertex/W&B equivalents are allowed when appropriately documented; multi-GPU work is conditional on applicability.

## What this pass completed

| Change | Verification | Limit |
| --- | --- | --- |
| Integrated frontend `20261104.6` into a full isolated source copy | All **82 frontend tests**; actual backend/relay browser flow at desktop and 320px | The hosted static Site still has no model API |
| Added [`verify_serving_export.py`](../../tools/verify_serving_export.py) | Reused `b2-als-synthetic-244f05111efd`, 160 books; real HTTP requests through both owned services; two ranking modes, reader references, score/coordinate parity and private-route isolation passed | No new training, cloud execution or quality evaluation |
| Preserved existing invocation and network-access settings in [`deploy.py`](../../deploy/cloud-run/deploy.py) | Mocked publication tests prove no IAM mutations and retention of ingress/Invoker IAM-check/default-URL annotations | No Cloud Run execution or container rebuild |
| Added authenticated service verification to [`smoke.py`](../../deploy/cloud-run/smoke.py) | Token stays in memory/stdin; argv/files exclude it; HTTPS-origin binding and redirect rejection tested | An authorized identity and existing invocation permission are still required |
| Added demo-model and outcome checks | Synthetic/sample/toy exports require an explicit demo flag before upload; a service update followed by failed verification remains `deployed_unverified` | A non-demo model name alone does not verify data provenance |

The tool/configuration suite has **27 passing tests**, including 13 new checks. [Test output](evidence/current-serving-20261104/tools-tests.txt), [frontend output](evidence/current-serving-20261104/frontend-tests.txt), [actual API checks](evidence/current-serving-20261104/api-check.json), [source/artifact hashes](evidence/current-serving-20261104/run.json), and [browser record](evidence/current-serving-20261104/browser-checks.json) are retained. The captured source is based on `1872d1c` with `source_dirty=true`; per-file hashes identify the tested local code. This is a review patch, not a submitted commit.

The model is a **previously fitted synthetic ALS export**, not the fixed 52-book toy fixture and not a new Goodreads result. Earlier [MS2 evidence](../ms2/models/) records a real 5,000-work model, but that approved export is absent here. No raw data, model weights, real reader histories or credentials were added to source. Browser confirmation changed page-local state only; no `/feedback` event was sent.

## Current team and environment checks

A fresh [read-only reference check](evidence/current-serving-20261104/remote-refs.json) still finds `main` and `milestone2` at `fccfbac53a96de18b71ca1c3f668a6bea115e51e`, with no `milestone3` branch. The architecture branch remains at `744dc878c4c20e0883f8207adc3d53f78984a67a`; its inspected notes describe MS2 and separate future work. [PR #11](https://github.com/cathyliu0510/AC215_TasteBridge/pull/11) must be reconciled through normal review. Its current open/review state and teammates’ unpushed or cloud work are not established. No current MS3 work allocation was inferred from the historical MS2 offers.

The GitHub connector could not read the private repository; ordinary read-only SSH reference lookup succeeded. This did not retry the denied push. The source copy has no remote. The Keynote computer-control card does not govern GitHub. Any previously denied GitHub upload must be reconsidered through its original safety review using the verified repository audience and exact upload contents; no alternate account or destination is a substitute.

[Local environment checks](evidence/current-serving-20261104/environment.json) confirm `gcloud` is unavailable on PATH, the configured Docker Unix socket is absent, and the approved processed data/model export are absent. Docker CLI availability does not establish a running daemon. No cloud credentials were inspected or cloud jobs launched.

## Execute next, in this order

1. **Recover existing team evidence before rerunning anything.** Establish whether a cloud training/workflow run already exists, and obtain the approved export or processed-data path plus its version/hash record. Required fields: job/workflow ID and status, project/region, source commit, parameters, input/output URIs, tracker/run URL and screenshots. If a valid run already exists, verify and reuse it.
2. **Close training/workflow gaps on the approved platform.** If no run exists, confirm the team’s tracker and Vertex/equivalent choice, execution identity, authorized data/output locations and execution/budget approval. Adapt the existing B2 preprocessing/export/evaluation components to that selection, execute one successful tracked cloud run and preserve the evidence. The current 16-factor/8-iteration synthetic smoke settings do not replace the historical tuned 128-factor/15-iteration settings or decide a new model architecture.
3. **Verify the approved export locally, then deploy the tested images.** Use a working Docker/Buildx environment, `gcloud`, private registry access and the approved runtime identity for `tastebridge-511403`, `us-central1`, `tastebridge-staging`. Build and local-smoke the actual images using the existing [Cloud Run package](../../deploy/cloud-run/README.md). Confirm staff/public invocation arrangements before an authorized operator publishes; the updated code preserves existing access. Use `--authenticated` for an already authorized caller. Record immutable image digests, revision/configuration, HTTPS request/response and browser checks. No cloud commands in this step were run here.
4. **Capture actual production evidence.** With existing log-reader access, collect a request/error/latency log tied to the deployed revision and model version; document the log query and access. Explicit feedback verification is optional and requires authorization to send that test event. Local Uvicorn logs are not production-monitoring proof.
5. **Review and submit the integrated result.** Reconcile the source patch and architecture work, replace pending cloud evidence in the existing [12-slide deck](presentation/TasteBridge-MS3-review.pptx), verify native slide rendering and rehearse. After the original push block is resolved, the authorized maintainer creates/updates `milestone3` and submits the reviewed full hash on Canvas. Neither branch existence nor local code proves Canvas submission.

The inputs that currently prevent further execution are: **approved real artifact/data location; any existing cloud run and tracker records; selected cloud workflow; project/service-account/storage permissions and execution approval; working Docker and gcloud environment; confirmed teaching-staff invocation/log access; original GitHub approval resolution.** Credentials themselves should stay with the authorized operator, not in the handoff files.

## Reuse an existing export

From this review source, with an existing backend environment:

```sh
python3 tools/verify_serving_export.py --artifact-dir data/artifacts/current \
  --out .integration-runtime/ms3-serving-check --serve
```

Use `--backend-python PATH` when the locked environment exists in another checkout. The verifier reads the four-file export without modifying it and refuses to overwrite an existing output directory. It starts only two loopback services, sends no feedback, records failure instead of success if a stage fails, and stops its own services on Ctrl-C. `training_executed` and `cloud_execution` remain false. Real input provenance must be reviewed independently.

`python3 tools/check_ms3.py` still exits **1**, intentionally: cloud and submission evidence remain incomplete. The checker only validates coverage/file presence; even a future passing manifest does not replace human review of cloud evidence or Canvas status.
