# TasteBridge shared demo

**Status: cloud deployment unverified.** [Historical local Docker verification](verification.local.json) predates the current branch. The [current local integration evidence](../../docs/ms3/evidence/local-integration-20261104/) exercises Python/Node services, not the new container images. Rebuild and smoke-test the actual images before publication. This continuation did not publish a service.

Prepares the current frontend and existing backend with the team's approved model export for **`tastebridge-511403`**, region **`us-central1`**, service **`tastebridge-staging`**. The historical configuration used the real 5,000-book model; the currently pinned export with the same model label has now been recovered into ignored local runtime storage and verified against the existing DVC index. Its vector/metadata hashes differ from the historical container check; rebuild and verify current images. See [the current audit](../../docs/ms3/team-audit-20261105.md). Updating an existing service keeps its Cloud Run URL. This does not update the static prototype website.

```text
HTTPS link with approved access
        │
        ▼
┌──────────── Cloud Run service ──────────────┐
│ Frontend :8080 ── localhost ──► API :9000   │
│                                  │         │
│                     trained model export   │
│                                  │         │
│                     feedback → cloud logs  │
└────────────────────────────────────────────┘
```

The derived backend image adds only `books.json`, `item_embeddings.npy`, `coords_2d.npy` and `meta.json`. The model files stay outside Git and inside a **private** image repository. The app exposes search/recommendation endpoints; it does not expose raw model downloads.

## Administrator: one-time access

In [TasteBridge IAM](https://console.cloud.google.com/iam-admin/iam?project=tastebridge-511403), grant Jenny's Google account the roles below. Use the same account already authorized to download the model.

| Role | Scope | Purpose |
| --- | --- | --- |
| Cloud Run Admin (`roles/run.admin`) | `tastebridge-511403` | Create/update the approved demo service |
| Service Usage Consumer (`roles/serviceusage.serviceUsageConsumer`) | `tastebridge-511403` | Use enabled APIs and this project's quota |
| Artifact Registry Writer (`roles/artifactregistry.writer`) | Docker repository `us-central1/tastebridge-app` | Upload app images |
| Service Account User (`roles/iam.serviceAccountUser`) | `tastebridge-runtime@tastebridge-511403.iam.gserviceaccount.com` | Run the app with its dedicated identity |
| Logs Viewer (`roles/logging.viewer`) | `tastebridge-511403` | Verify requests and saved demo feedback |

Also enable the Cloud Run, Artifact Registry and IAM APIs; create the Docker repository and runtime service account if absent. The runtime identity needs **no application roles**, because the model is packaged with the app.

The publishing operator also needs read access to both IAM policies: `resourcemanager.projects.getIamPolicy` on this project and `artifactregistry.repositories.getIamPolicy` on this repository. The image-writer grant alone does not establish these permissions. An administrator can supply them through an existing suitable role or a scoped custom role; the publisher never grants them itself.

An administrator can review and run [admin-setup.sh](admin-setup.sh) from an authenticated Google Cloud Shell:

```sh
git clone --branch milestone3 --single-branch https://github.com/cathyliu0510/AC215_TasteBridge.git TasteBridge-cloud-setup
cd TasteBridge-cloud-setup
bash deploy/cloud-run/admin-setup.sh JENNY_GOOGLE_EMAIL
```

Replace `JENNY_GOOGLE_EMAIL` with Jenny's actual Google account. The script adds these scoped grants, checks project/repository IAM for public bindings and leaves existing policies intact. It creates a repository or service account only after an explicit `NOT_FOUND` lookup result; permission and transient failures stop the script. An administrator should also confirm there is no inherited public Artifact Registry access from a folder or organization; those ancestor policies are not inspected by this script. Keep the agreed teaching-staff/public audience. Publication does not grant invocation or disable the Invoker IAM check; any access-policy change is a separate administrator decision.

## Use an existing runtime service account

When the team has already provisioned `tastebridge-api@tastebridge-511403.iam.gserviceaccount.com`, select that existing identity explicitly at publication:

```sh
python3 deploy/cloud-run/deploy.py publish --authenticated \
  --runtime-service-account tastebridge-api@tastebridge-511403.iam.gserviceaccount.com
```

This command uploads images and deploys the service; it is not a readiness check and requires approval for publication and cloud spending. The option creates no account or IAM grants. Confirm the selected identity exists and the authorized publisher can act as it. Do not run `admin-setup.sh` to create the legacy `tastebridge-runtime` identity when the team is using `tastebridge-api`.

The legacy default remains `tastebridge-runtime` for existing operators. The selected identity must belong to `tastebridge-511403`; invalid values fail before publication reads state or runs subprocesses. The chosen account is recorded in the service spec and deployment outcome. Existing access settings are preserved. After integrating packaging changes, rebuild and locally smoke-test a clean, committed checkout as described below; an older build receipt cannot stand in for this changed packaging.

## Build and check locally

Requires Docker with Buildx, Python 3.10+ and the already downloaded four-file model export. Run from the repository root:

```sh
python3 deploy/cloud-run/deploy.py build /absolute/path/to/data/artifacts/current
python3 deploy/cloud-run/smoke.py --local
```

The build targets **linux/amd64**, including on an Apple Silicon Mac. Commit changes in `src/backend`, `frontend/prototype` and `deploy/cloud-run` before building: both application and deployment packaging trees are recorded and must remain clean through publication. Older release records without the packaging tree must be rebuilt and retested. The smoke check uses temporary containers sharing a localhost network, like Cloud Run. It checks the exact image IDs, model identity/count, search, both ranking modes, reader-specific reasons, map coordinates, one feedback event and blocked private routes. It removes its temporary containers and leaves any existing app running.

Build records and test evidence stay in ignored `.state/`; staged model files stay in ignored `.artifacts/`. No cloud resources are created by these commands. The actual model used for the October 18 test was `b2-als-gr-317756d1a1ad` (B2 ALS, 5,000 books, 128 factors).

Serving verification derives the full artifact fingerprint from the release's four `artifact_sha256` values, using the same format as the backend. Health must report that fingerprint and the expected `data_version`; both recommendation modes must report the same fingerprint. A model name and book count alone cannot identify the export. The contract check rejects missing or malformed expected identity before its first HTTP request; the local container runner has a separate startup readiness poll. Rebuild incomplete release records rather than treating a missing identity as a wildcard. An export without a recorded data version uses an explicit JSON `null` on both sides. The local export/integration verifiers pass hashes from their input files and the data version from export metadata, never from the service being checked.

## Publish after access is granted

Authenticate the Google Cloud SDK with the authorized account and put `gcloud` on `PATH`. A user who has already completed Application Default Credentials login can use that existing login:

```sh
export CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE="$HOME/.config/gcloud/application_default_credentials.json"
python3 deploy/cloud-run/deploy.py publish
```

`publish` checks access before uploading, verifies the tested images, pushes to the private repository, deploys by image digest, and tests the returned URL. It preserves existing IAM, ingress, Invoker IAM-check and default-URL settings. It never adds `allUsers`, changes an invocation grant or disables authentication. A new service retains Cloud Run’s default authentication requirement. It refuses to overwrite an existing service with a different owner label. The resulting URL is saved to `.state/url.txt`; keep sharing that URL for future updates.

Before each image push and again before replacing the service, publication reads the current project and repository IAM policies. A public binding (`allUsers` or `allAuthenticatedUsers`), denied query or unverifiable response stops further pushes and service updates. Policy hashes and check times are saved with that attempt, without saving member lists. This check covers those two policies at query time; it does not inspect inherited folder/organization policies or prevent an administrator from changing access afterward. Have an administrator confirm ancestor access before publication. Publication changes no IAM policy.

For an already authorized operator verifying an authenticated service, use:

```sh
python3 deploy/cloud-run/deploy.py publish --authenticated
```

This uses the existing gcloud identity. Its ID token passes to the smoke process through stdin, stays in memory and is scoped to the returned HTTPS origin. It is absent from command arguments and saved evidence. Cross-origin redirects are rejected. A user invoking the service must already have the required invocation permission; this command grants none. [Google’s developer-authentication instructions](https://docs.cloud.google.com/run/docs/authenticating/developers) describe this testing flow.

A synthetic/sample/toy model is refused before upload unless the operator explicitly passes `--allow-demo-model`. That flag permits a labeled demonstration; it does not establish real-data or MS3 training evidence. Other model identities remain operator supplied and unverified until provenance is reviewed.

The deployment outcome is saved to `.state/deployment.json` before API verification. If verification fails, it remains `deployed_unverified`; the actual service update is not reported as though nothing happened. Successful API verification changes it to `deployed_and_api_verified`. Browser/staff-access/log checks are still separate. Anonymous verification requires the service’s existing access policy already to allow it.

Before announcing the link, open it in a browser and check picking books, switching ranking modes, details and the map. Submit one explicit test feedback event and confirm its `book_id`, `vote`, `model_version` and timestamp in [Cloud Logging](https://console.cloud.google.com/logs/query?project=tastebridge-511403):

```text
resource.type="cloud_run_revision"
resource.labels.service_name="tastebridge-staging"
jsonPayload.model_version="b2-als-gr-317756d1a1ad"
jsonPayload.vote="would_read"
```

`FEEDBACK_PATH=/dev/stdout` sends the existing backend's anonymous vote records to Cloud Logging. This avoids losing the only copy on container restart. Check the project's log exclusions/retention after deployment; this is demo feedback logging, not a permanent feedback database. Cloud infrastructure also keeps operational request logs.

The service uses request-based CPU, zero minimum instances, a maximum of one instance and concurrency eight. These settings limit idle use and scale, but are not a billing cap. First requests after inactivity can take longer. No GPU, Cloud Build job or training job is needed.

## Updates and rollback

After committing frontend changes, repeat **build → local smoke → publish**. Replace the model-export directory only when the team approves a new model. Source commit, model hashes and exact Docker image IDs are saved with each build; each deployed revision uses immutable image digests.

Before uploading, `publish` saves an independent snapshot under `.state/attempts/ATTEMPT_ID/`. Each attempt contains the prior service, release identity, privacy checks and a `rollback.txt` operator command. Retries preserve earlier attempt directories. The compatibility file `.state/previous-service.json` is only a copy of the latest attempt's snapshot.

Read the rollback instructions for the specific update you want to reverse:

```sh
cat deploy/cloud-run/.state/attempts/ATTEMPT_ID/rollback.txt
```

The printed command uses the resolved `status.traffic` revision names and percentages. For example, if revision A served 100% while newer revision B was ready, it restores A; a 90/10 split stays 90/10. Publication refuses to proceed when an existing service's traffic cannot be resolved to 100%. Review the saved service before an operator executes rollback: the command restores traffic allocations, while tags and other configuration need separate review. A first deployment has no previous service to roll back to. The script prints instructions and never runs rollback. Use the existing service; deleting and recreating services is not the update workflow.

References: [Cloud Run containers](https://docs.cloud.google.com/run/docs/configuring/services/containers), [container contract](https://docs.cloud.google.com/run/docs/container-contract), [deployment](https://docs.cloud.google.com/run/docs/deploying), [logging](https://docs.cloud.google.com/run/docs/logging).

## Catalogue-independent verification

When the approved catalogue does not contain the default example titles, use two actual IDs from that catalogue:

```sh
python3 deploy/cloud-run/smoke.py --url "$SERVICE_URL" \
  --reader-a-id "$READER_A_BOOK_ID" --reader-b-id "$READER_B_BOOK_ID"
```

Supply both IDs. The verifier checks the served model identity, both ranking rules and their score calculation, seed exclusion, matching map coordinates and private-route isolation. Feedback remains opt-in for a deployed URL. The [local integration runner](../../docs/ms3/reproduce.md) reuses this check without Docker and without writing deployment state.

## Verify an existing export before rebuilding or retraining

The serving-only verifier reuses the current frontend, backend and smoke contract. It never downloads data, trains a model, creates a container, sends feedback or contacts cloud APIs:

```sh
python3 tools/verify_serving_export.py --artifact-dir data/artifacts/current \
  --out .integration-runtime/ms3-serving-check --serve
```

The backend environment must already exist (`uv sync --frozen --project src/backend`). Use `--backend-python PATH` for an existing environment in another checkout. The command validates the export, starts two owned loopback services on free ports, checks the API and prints a UI URL with valid five-book shelves. Ctrl-C closes only those processes. A fresh output directory is required. `run.json` records source/artifact hashes, source dirtiness, model identity, input kind and explicit `training_executed=false` / `cloud_execution=false`. A model identifier alone does not certify real-data provenance. See the [current local evidence](../../docs/ms3/evidence/current-serving-20261104/).

## Require the reviewed export bytes

The [current artifact handoff](../../docs/ms3/deployment-evidence-handoff-20261105.md) provides a reviewed SHA256 lock. Use it during the existing local build:

```sh
python3 deploy/cloud-run/deploy.py build /absolute/path/to/approved/current \
  --artifact-lock docs/ms3/evidence/identity-handoff-20261105/artifact-lock.json
```

A mismatch aborts before any Docker build. A successful locked build records the lock SHA256 in `.state/release.json`. This does not execute a cloud deployment or grant invocation.


## Frontend health verification

Use `/frontend/health` for external checks. It returns `{"status":"ok","service":"frontend"}` without contacting the backend. `/healthz` remains the internal Cloud Run startup probe. In the November 11 staging deployment, the external `/healthz` URL returned a Google-generated 404 while the container's startup probe succeeded; the namespaced route avoids that observed edge-path collision. `/api/health` independently verifies the served model identity. Neither route grants invocation access.
