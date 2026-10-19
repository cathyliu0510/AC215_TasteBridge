#!/usr/bin/env bash
# Run once by a TasteBridge project administrator, with Jenny's Google account.
set -euo pipefail
if [[ $# != 1 || "$1" != *@* ]]; then
  echo 'Usage: bash deploy/cloud-run/admin-setup.sh JENNY_GOOGLE_EMAIL' >&2
  exit 2
fi
PROJECT=tastebridge-511403
REGION=us-central1
REPOSITORY=tastebridge-app
RUNTIME=tastebridge-runtime
MEMBER="user:$1"
SA="$RUNTIME@$PROJECT.iam.gserviceaccount.com"

# Keep model-bearing container images private, including inherited project grants.
# Review any public project binding before continuing; this script never removes IAM.
check_private() {
  python3 -c 'import json,sys; p=json.load(sys.stdin); public=[b["role"] for b in p.get("bindings",[]) if set(b.get("members",[])) & {"allUsers","allAuthenticatedUsers"}]; sys.exit("Review public IAM bindings before uploading model images: " + ", ".join(public)) if public else None'
}
gcloud projects get-iam-policy "$PROJECT" --format=json | check_private

gcloud services enable run.googleapis.com artifactregistry.googleapis.com iam.googleapis.com --project="$PROJECT"
if ! gcloud artifacts repositories describe "$REPOSITORY" --location="$REGION" --project="$PROJECT" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$REPOSITORY" --repository-format=docker --location="$REGION" --project="$PROJECT" --description='TasteBridge app images with a trained model export'
fi
gcloud artifacts repositories get-iam-policy "$REPOSITORY" --location="$REGION" --project="$PROJECT" --format=json | check_private
if ! gcloud iam service-accounts describe "$SA" --project="$PROJECT" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$RUNTIME" --project="$PROJECT" --display-name='TasteBridge Cloud Run runtime'
fi
# No application roles are granted to the runtime identity: the model is in its image.
gcloud projects add-iam-policy-binding "$PROJECT" --member="$MEMBER" --role=roles/run.admin --condition=None
gcloud projects add-iam-policy-binding "$PROJECT" --member="$MEMBER" --role=roles/serviceusage.serviceUsageConsumer --condition=None
gcloud artifacts repositories add-iam-policy-binding "$REPOSITORY" --location="$REGION" --project="$PROJECT" --member="$MEMBER" --role=roles/artifactregistry.writer --condition=None
gcloud iam service-accounts add-iam-policy-binding "$SA" --project="$PROJECT" --member="$MEMBER" --role=roles/iam.serviceAccountUser --condition=None
gcloud projects add-iam-policy-binding "$PROJECT" --member="$MEMBER" --role=roles/logging.viewer --condition=None
