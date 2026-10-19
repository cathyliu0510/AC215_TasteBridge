# TasteBridge shared demo

**Status: prepared and tested in local Docker; cloud deployment awaits project permissions.** [Local verification](verification.local.json). No public URL has been created by this package yet.

Deploys the PR #6 frontend and the existing backend with the real 5,000-book model to **`tastebridge-511403`**, region **`us-central1`**, service **`tastebridge-staging`**. Updating that service keeps its Cloud Run URL. This does not update the older static prototype website.

```text
One public HTTPS link
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

No files in `src/backend/`, model training or data pipelines are changed. The derived backend image adds only `books.json`, `item_embeddings.npy`, `coords_2d.npy` and `meta.json`. The model files stay outside Git and inside a **private** image repository. The app exposes search/recommendation endpoints; it does not expose raw model downloads.

## Administrator: one-time access

In [TasteBridge IAM](https://console.cloud.google.com/iam-admin/iam?project=tastebridge-511403), grant Jenny's Google account the roles below. Use the same account already authorized to download the model.

| Role | Scope | Purpose |
| --- | --- | --- |
| Cloud Run Admin (`roles/run.admin`) | `tastebridge-511403` | Create/update the demo and allow teammates to open it |
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

Replace `JENNY_GOOGLE_EMAIL` with Jenny's actual Google account. The script adds these scoped grants, checks project/repository IAM for public bindings and leaves existing policies intact. An administrator should also confirm there is no inherited public Artifact Registry access from a folder or organization; those ancestor policies are not inspected by this script. If organization policy blocks a public demo, resolve that with the administrator before publication.

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

`publish` checks access before uploading, verifies the tested images, pushes to the private repository, deploys by image digest, enables public invocation, then tests the returned URL without login. It refuses to overwrite an existing service with a different owner label. The resulting URL is saved to `.state/url.txt`; keep sharing that URL for future updates.

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
