# Jenny's MS3 serving and evidence handoff

**Current status: deployed and API/browser/log verified; teaching-staff account access still requires confirmation.** Jenny and Nikhil own serving and its evidence. [Verified live bundle](evidence/deployed-serving-20261111/) records the actual URL, revision, immutable digests, model identity, screenshots and logs. No IAM was changed. The operator explicitly confirmed no public access and compliance; ancestor policies were not independently read.

## 1 Confirm the exact candidate

Deployed source: `5184a6c836b2988f18f1f9586bb0ebf1a43f2731`. Required model fingerprint: `cb4457b668e3561692d557a44a54378966fc400719120162c2838a76258e0164`. Data: `gr-317756d1a1ad`; 5,000 books. The [live deployment summary](evidence/deployed-serving-20261111/deployment-summary.json) records the passing local and cloud checks. After further source or packaging changes, build and smoke again from the final clean commit; do not relabel an old receipt.

[Build/publish/redeploy/rollback instructions](../../deploy/cloud-run/README.md) remain the operational source. The intended service is `tastebridge-staging`, project `tastebridge-511403`, region `us-central1`. The existing runtime account was verified; no new identity is needed. Live URL: https://tastebridge-staging-fbii3egyuq-uc.a.run.app. Ready revision `tastebridge-staging-00002-vzn`, 100% traffic.

## 2 Use the actual exposed API paths

The frontend container is Cloud Run's ingress and relays these routes to the internal FastAPI container:

| Exposed path | Purpose |
| --- | --- |
| `GET /frontend/health` | Frontend health, independently from backend |
| `GET /api/health` | Loaded model, fingerprint, data version and catalogue size |
| `GET /api/books/search?q=...` | Find real catalogue IDs |
| `GET /api/books/{id}` | Book details |
| `POST /api/recommend` | Prediction for both readers |
| `POST /api/feedback` | Explicit feedback write; omit from read-only evidence checks |

Direct FastAPI paths omit `/api`. Its `/docs` and `/openapi.json` are internal/local routes and are not forwarded by the deployed frontend. The [SPEC](../../src/backend/SPEC.md) is the external API documentation. Do not direct the TF to a nonexistent `/api/docs` URL or widen the relay simply to expose it.

## 3 Verify teaching-staff access without making the service public

A private Cloud Run service needs both an approved caller and an authentication token. Browser sign-in alone does not add that token to an ordinary service URL. After deployment, an already authorized user can run Google's supported local proxy:

```sh
gcloud run services proxy tastebridge-staging \
  --project=tastebridge-511403 --region=us-central1 --port=8080
```

Then open `http://localhost:8080/a/?api=1`. The CLI uses the active authorized account. The service must be reachable under its existing ingress policy. This proxy is a route to the cloud service, not a local model server; label it that way in evidence. Verify the agreed teaching-staff account can invoke it before marking staff access complete. Any missing access grant needs the separately authorized administrator action.

Sources: [Google authentication guide](https://docs.cloud.google.com/run/docs/authenticating/developers) and [proxy reference](https://docs.cloud.google.com/sdk/gcloud/reference/run/services/proxy). The execution checks used this authenticated proxy to the live service. No new account login or permission change was performed.

## 4 Capture a real prediction without capturing credentials

Keep the proxy running in its own terminal. In another terminal, record the live service URL/revision from the deployment receipt or this read-only lookup:

```sh
gcloud run services describe tastebridge-staging \
  --project=tastebridge-511403 --region=us-central1 \
  --format='yaml(status.url,status.latestReadyRevisionName,status.traffic)'
```

Use a fresh output directory so older evidence is not overwritten:

```sh
set -o pipefail
EVIDENCE_DIR="$(mktemp -d)"
BASE=http://localhost:8080
curl --fail-with-body --silent --show-error "$BASE/api/health" \
  | tee "$EVIDENCE_DIR/health.json"
curl --fail-with-body --silent --show-error \
  "$BASE/api/books/search?q=The%20Hobbit&limit=5"
curl --fail-with-body --silent --show-error \
  "$BASE/api/books/search?q=Gone%20Girl&limit=5"
```

Use the returned real `book_id` strings in a request file, with this format. Replace both placeholders before running; these are not valid catalogue IDs:

```json
{"reader_a":["REPLACE_WITH_FIRST_ID"],"reader_b":["REPLACE_WITH_SECOND_ID"],"k":5,"aggregation":"least_misery"}
```

Save it as `$EVIDENCE_DIR/request.json`, then run:

```sh
curl --fail-with-body --silent --show-error \
  -H 'Content-Type: application/json' --data-binary @"$EVIDENCE_DIR/request.json" \
  "$BASE/api/recommend" | tee "$EVIDENCE_DIR/recommend.json"
```

The API accepts 1–5 distinct IDs per reader; the UI asks for five. Capture a separate five-pick browser flow if demonstrating the complete product. Repeat the request with `aggregation` set to `average`, saving a different response file. Verify both responses match the expected fingerprint and model, exclude the favorites, and contain five finite, consistently ranked recommendations. The existing smoke verifier automates these checks using the local release identity:

```sh
gcloud auth print-identity-token | python3 deploy/cloud-run/smoke.py \
  --url "$SERVICE_URL" --identity-token-stdin
```

Set `SERVICE_URL` only from the confirmed deployment receipt, and keep the matching `deploy/cloud-run/.state/release.json` available. Do not pass `--feedback` unless a test feedback write was explicitly approved. Never print, save or photograph an identity token; do not use verbose HTTP logging. A successful local proxy screenshot must show the associated cloud URL/revision as context and be captioned as a cloud invocation through the authenticated proxy.

## 5 Collect revision-linked production logs

Use the actual revision from the deployment receipt and the request time window. In [Logs Explorer](https://console.cloud.google.com/logs/query?project=tastebridge-511403), start with:

```text
resource.type="cloud_run_revision"
resource.labels.service_name="tastebridge-staging"
resource.labels.location="us-central1"
resource.labels.revision_name="REPLACE_WITH_ACTUAL_REVISION"
```

The backend writes method, path, status and duration to stdout/stderr. Look for the actual `POST /recommend` event and its time/status/duration; Cloud Run request logs see the ingress route `/api/recommend`. Request lines are text logs, so filtering only on `jsonPayload.model_version` would miss them. Confirm the revision's image/model identity with the deployment receipt and health response. Basic logs satisfy the monitoring minimum; do not call a single request a production p95 benchmark or model-drift monitor.

Capture only the needed operational lines. Exclude tokens, credential fields, reader histories and unnecessary identity details. Feedback is optional and separate; a local feedback log does not prove production logging. This runbook does not authorize sharing screenshots externally.

## 6 Final evidence bundle and stopping rules

Keep originals and a short index with: source commit; deployed service URL and region; exact ready revision and traffic; immutable remote image digests; four-file model fingerprint; health and both recommendation responses; timestamped deployed curl screenshot; production log screenshot/query; teaching-staff access result; and test commands/results for the final source.

The required screenshot must show a real prediction, not health alone, a static Site or a fabricated output. Do not expose raw model files to obtain evidence. The 23-book public prototype and the 52-book toy catalogue are separate from the 5,000-book model.

Stop and report any failed identity match, unavailable access, unsuccessful revision or unresolved privacy check. A publish command can create a revision before a later check fails; inspect the saved deployment outcome before retrying. Keep failed outcomes in the record.
