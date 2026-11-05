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
  python3 -c '
import json, sys
policy = json.load(sys.stdin)
if (not isinstance(policy, dict) or
        ("bindings" not in policy and not isinstance(policy.get("etag"), str)) or
        not isinstance(policy.get("bindings", []), list)):
    sys.exit("Unverifiable IAM policy; stop before setup")
for binding in policy.get("bindings", []):
    if (not isinstance(binding, dict) or not isinstance(binding.get("role"), str) or
            not isinstance(binding.get("members"), list) or
            any(not isinstance(member, str) for member in binding["members"])):
        sys.exit("Unverifiable IAM binding; stop before setup")
    if set(binding["members"]) & {"allUsers", "allAuthenticatedUsers"}:
        sys.exit("Review public IAM bindings before uploading model images: " + binding["role"])
'
}
gcloud projects get-iam-policy "$PROJECT" --format=json | check_private

# Only the CLI's explicit NOT_FOUND result permits creation. Permission, API and
# transient failures must remain failures rather than being treated as absence.
resource_exists() {
  local output missing_pattern='^ERROR: \([^)]*\) NOT_FOUND:'
  if output=$("$@" 2>&1); then
    return 0
  fi
  if [[ "$output" =~ $missing_pattern ]]; then
    return 1
  fi
  printf '%s\n' "$output" >&2
  echo 'Resource lookup failed; no create will be attempted for this result.' >&2
  return 2
}

gcloud services enable run.googleapis.com artifactregistry.googleapis.com iam.googleapis.com --project="$PROJECT"
if resource_exists gcloud artifacts repositories describe "$REPOSITORY" --location="$REGION" --project="$PROJECT"; then
  :
else
  lookup_status=$?
  [[ "$lookup_status" == 1 ]] || exit "$lookup_status"
  gcloud artifacts repositories create "$REPOSITORY" --repository-format=docker --location="$REGION" --project="$PROJECT" --description='TasteBridge app images with a trained model export'
fi
gcloud artifacts repositories get-iam-policy "$REPOSITORY" --location="$REGION" --project="$PROJECT" --format=json | check_private
if resource_exists gcloud iam service-accounts describe "$SA" --project="$PROJECT"; then
  :
else
  lookup_status=$?
  [[ "$lookup_status" == 1 ]] || exit "$lookup_status"
  gcloud iam service-accounts create "$RUNTIME" --project="$PROJECT" --display-name='TasteBridge Cloud Run runtime'
fi
# No application roles are granted to the runtime identity: the model is in its image.
gcloud projects add-iam-policy-binding "$PROJECT" --member="$MEMBER" --role=roles/run.admin --condition=None
gcloud projects add-iam-policy-binding "$PROJECT" --member="$MEMBER" --role=roles/serviceusage.serviceUsageConsumer --condition=None
gcloud artifacts repositories add-iam-policy-binding "$REPOSITORY" --location="$REGION" --project="$PROJECT" --member="$MEMBER" --role=roles/artifactregistry.writer --condition=None
gcloud iam service-accounts add-iam-policy-binding "$SA" --project="$PROJECT" --member="$MEMBER" --role=roles/iam.serviceAccountUser --condition=None
gcloud projects add-iam-policy-binding "$PROJECT" --member="$MEMBER" --role=roles/logging.viewer --condition=None
