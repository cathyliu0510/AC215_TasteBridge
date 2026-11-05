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

An administrator can review and run [admin-setup.sh](admin-setup.sh) from an authenticated Google Cloud Shell:

```sh
git clone --branch frontend/cloud-staging --single-branch https://github.com/cathyliu0510/TasteBridge.git TasteBridge-cloud-setup
cd TasteBridge-cloud-setup
bash deploy/cloud-run/admin-setup.sh JENNY_GOOGLE_EMAIL
```

Replace `JENNY_GOOGLE_EMAIL` with Jenny's actual Google account. The script adds these scoped grants, checks project/repository IAM for public bindings and leaves existing policies intact. An administrator should also confirm there is no inherited public Artifact Registry access from a folder or organization; those ancestor policies are not inspected by this script. Keep the agreed teaching-staff/public audience. Publication does not grant invocation or disable the Invoker IAM check; any access-policy change is a separate administrator decision.

## Build and check locally

Requires Docker with Buildx, Python 3.10+ and the already downloaded four-file model export. Run from the repository root:

```sh
python3 deploy/cloud-run/deploy.py build /absolute/path/to/data/artifacts/current
python3 deploy/cloud-run/smoke.py --local
```

The build targets **linux/amd64**, including on an Apple Silicon Mac. The smoke check uses temporary containers sharing a localhost network, like Cloud Run. It checks the exact image IDs, model identity/count, search, both ranking modes, reader-specific reasons, map coordinates, one feedback event and blocked private routes. It removes its temporary containers and leaves any existing app running.

Build records and test evidence stay in ignored `.state/`; staged model files stay in ignored `.artifacts/`. No cloud resources are created by these commands. The actual model used for the October 18 test was `b2-als-gr-317756d1a1ad` (B2 ALS, 5,000 books, 128 factors).

## Publish after access is granted

Authenticate the Google Cloud SDK with the authorized account and put `gcloud` on `PATH`. A user who has already completed Application Default Credentials login can use that existing login:

```sh
export CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE="$HOME/.config/gcloud/application_default_credentials.json"
python3 deploy/cloud-run/deploy.py publish
```

`publish` checks access before uploading, verifies the tested images, pushes to the private repository, deploys by image digest, and tests the returned URL. It preserves existing IAM, ingress, Invoker IAM-check and default-URL settings. It never adds `allUsers`, changes an invocation grant or disables authentication. A new service retains Cloud Run’s default authentication requirement. It refuses to overwrite an existing service with a different owner label. The resulting URL is saved to `.state/url.txt`; keep sharing that URL for future updates.

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

Before updating, `publish` saves the previous service description in `.state/previous-service.json`. To roll back, use its `status.latestReadyRevisionName`:

```sh
gcloud run services update-traffic tastebridge-staging \
  --project=tastebridge-511403 --region=us-central1 \
  --to-revisions=PREVIOUS_REVISION=100
```

Use the existing service; deleting and recreating services is not the update workflow.

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
