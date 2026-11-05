# MS3 deployment and evidence handoff

Historical interim snapshot. For the current frontend, container, branch and presentation status, use [overnight-progress-20261105.md](overnight-progress-20261105.md).
The current model-to-UI path is verified locally. The next step is to inspect and reuse the team's existing cloud execution, service and logging records. Five cloud reads are denied, so this package prepares exact identity checks and evidence intake without creating another training/deployment workflow or starting a job.

## Exact model identity

The [reviewed four-file lock](evidence/identity-handoff-20261105/artifact-lock.json) is pinned to the repository's existing DVC directory index. The [local audit](evidence/identity-handoff-20261105/identity-audit-v2.json) verifies each byte hash, catalogue row count, finite NPY matrices and factor dimension. The original-byte index MD5 is `d084e50dc63c3203fc81d7ba09128074`; its four `current/` entries match the retrieved files.

| Field | Verified value |
| --- | --- |
| Model / data labels | `b2-als-gr-317756d1a1ad` / `gr-317756d1a1ad` |
| Books and matrices | 5,000 books; float32 vectors 5,000 × 128; float32 coordinates 5,000 × 2 |
| Recorded parameters | factors 128, regularization 50, alpha 20, iterations 15, seed 42 |
| Export byte fingerprint | `cb4457b668e3561692d557a44a54378966fc400719120162c2838a76258e0164` |
| Model suffix used by the existing image builder | `cb4457b668e3` |
| Recorded export source | `a5ee615bce37340b4cbff3aea50de10583ebc631` |
| Evaluation module source tree | `89d86b55f92395124821b7339225e1c7ea1be9ce`, identical in that recorded commit and this preparation source |

The [October Docker check](../../deploy/cloud-run/verification.local.json) has the same model label but different hashes for `item_embeddings.npy`, `coords_2d.npy` and `meta.json`, and different backend/frontend source trees. Its successful execution stays historical. It cannot verify the current model/images. A model name is not an immutable artifact identity.

The [historical evaluation context](evidence/identity-handoff-20261105/historical-evaluation-context.json) confirms the same parameter values and evaluation module source. Those results evaluate a training-user fit, while serving refits all retained readers. Current export metadata does not include processed input hashes, so the exact historical input linkage was not independently re-established. This work verifies an existing export, not training reproducibility from raw data.

## Current read access

| Surface | Observed result | Capability needed for the next check |
| --- | --- | --- |
| Existing GCS DVC snapshot | Read succeeds | No additional artifact access is needed for this export |
| Existing Cloud Run service | 403 with `run.services.get` | Read service/revision configuration |
| Vertex custom-job list | 403 with `aiplatform.customJobs.list` | Find existing training run, then read its record |
| Vertex pipeline-job list | 403 with `aiplatform.pipelineJobs.list` | Find existing workflow, then read its record |
| Existing Artifact Registry repository | 403 with `artifactregistry.repositories.get` | Inspect the existing private repository; image/digest inspection may require further read permissions |
| Bounded Cloud Logging query | 403, no permission identifier in response | Ordinary log-entry read access, commonly `logging.logEntries.list`, or access to an approved log view; the exact missing grant remains unconfirmed |

The first three denials are saved in [service/job visibility](evidence/team-serving-20261105/cloud-visibility.json); the last two in [registry/log visibility](evidence/identity-handoff-20261105/cloud-readiness.json). The log query requests at most five events for this service since October 1. It does not save raw log payloads, IP addresses or request URLs. The used read-only OAuth scope is supported by the [Logging API](https://docs.cloud.google.com/logging/docs/reference/v2/rest/v2/entries/list).

The team can supply sanitized existing evidence instead of granting new access. If an administrator chooses to grant read visibility, review the scoped permissions against [Cloud Run Viewer](https://docs.cloud.google.com/iam/docs/roles-permissions/run), [AI platform read roles](https://docs.cloud.google.com/iam/docs/roles-permissions/aiplatform), [Artifact Registry read roles](https://docs.cloud.google.com/iam/docs/roles-permissions/artifactregistry) and [Logging access](https://docs.cloud.google.com/logging/docs/access-control). These are read-visibility options, not a request for deployment, job-creation, IAM administration or broad project ownership. No permissions were changed.

## Ready-to-run local identity gate

This command reads existing files and writes a fresh report. It neither downloads nor stages data, starts services, trains, builds images nor contacts cloud APIs:

```sh
python3 tools/audit_serving_identity.py \
  --artifact-dir /absolute/path/to/approved/current \
  --lock docs/ms3/evidence/identity-handoff-20261105/artifact-lock.json \
  --dvc-index docs/ms3/evidence/identity-handoff-20261105/dvc-directory-index.json \
  --container-verification deploy/cloud-run/verification.local.json \
  --out .integration-runtime/identity-check-NEW.json
```

For this preparation copy, the recovered input is `.integration-runtime/team-model-20261105/current`. Keep it ignored. Use a fresh output filename to retain prior reports. The full backend/API/browser serving check has already passed for these exact four hashes; it need not be rerun until the model or served code changes.

## Operator build and deployment sequence

A functioning Docker daemon/Buildx and an existing Google Cloud CLI operator environment are still needed. Neither is available here. After the exact source is committed and reviewed, the operator can build **locally** with the new lock gate:

```sh
python3 deploy/cloud-run/deploy.py build /absolute/path/to/approved/current \
  --artifact-lock docs/ms3/evidence/identity-handoff-20261105/artifact-lock.json
python3 deploy/cloud-run/smoke.py --local
```

The lock gate compares staged SHA256 values before any Docker build. A mismatch aborts; no image is built. The build release records the reviewed lock's SHA256 alongside exact artifact hashes, app-source trees, image IDs and model/data labels. The existing local smoke verifies the actual images and writes ignored `.state/local-smoke.json`. Compare these current records; the October image IDs are insufficient.

Before updating anything, inspect existing team cloud work. An already authorized teammate can run these bounded read commands from their existing CLI environment; keep raw output in ignored runtime storage, and share only the necessary sanitized fields:

```sh
gcloud run services describe tastebridge-staging \
  --project=tastebridge-511403 --region=us-central1 --format=json

gcloud ai custom-jobs list --project=tastebridge-511403 \
  --region=us-central1 --limit=20 --format=json

gcloud artifacts repositories describe tastebridge-app \
  --project=tastebridge-511403 --location=us-central1 \
  --format='json(name,format,mode)'
```

For pipeline records, provide the existing `projects/.../locations/us-central1/pipelineJobs/...` resource or export from the team's console. The [custom-job CLI reference](https://docs.cloud.google.com/sdk/gcloud/reference/ai/custom-jobs/list) documents the bounded job lookup. Do not commit whole service definitions if they contain private environment values. Do not provide credentials or broaden IAM to make this checklist green.

Any actual image upload/service update remains a separate authorized operator action using the existing [Cloud Run package](../../deploy/cloud-run/README.md). Preserve existing service identity and invocation policy. Do not start a competing service or use the public static Site as evidence of model hosting. Save previous revision information before an update; deployment/rollback changes cloud state and has not been executed here.

## Evidence intake and acceptance

The [intake record](evidence/identity-handoff-20261105/cloud-evidence-intake.json) leaves unavailable fields null. It requests only what closes an MS3 gate:

1. **Existing training and workflow:** actual execution resources and completion status, source commit, immutable image/code identity, input hashes/locations, exact parameters, output identity, tracker record and screenshot. Reuse a valid existing run. If none exists, confirm the team's platform and execution authorization before implementation/execution.
2. **Deployment:** actual service URL and ready revision, immutable frontend/backend image digests, current build/local-smoke records, exact model hash manifest, responding API check and a browser screenshot with approved staff access. Preserve the access policy.
3. **Production monitoring:** a sanitized real request/error/performance event tied to that revision, timestamp, status/latency and documented log query/access. A local request log cannot close this gate. No feedback event is needed for the ordinary request-log evidence.

A person must review that these are actual accessible records, not placeholders or local output. Update the existing evidence index only when the gate's proof is complete. `check_ms3.py` validates coverage/path presence; it does not authenticate cloud receipts, screenshots or Canvas submission.

The [presentation integration manuscript](presentation-integration-20261105.md) maps this evidence to the existing 12-slide, 15-minute review. The PPTX remains the earlier review draft until its visual evidence is replaced and rendered. GitHub publication remains paused at the explicitly reported approval block. No push retry, cloud mutation, new training, external message, sharing change or formal submission occurred in this pass.
