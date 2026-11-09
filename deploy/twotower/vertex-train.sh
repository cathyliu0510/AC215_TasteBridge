#!/bin/bash
# Submit one M1 two-tower training run to Vertex AI as a CustomJob (the lecture-13 cli.sh step).
#
# It only *sends a request* to Google; the training itself runs in the pinned container on a
# Google machine, as the twotower-trainer service account, and writes to
# gs://tastebridge-twotower/runs/<RUN_ID>/ plus a W&B run. Nothing is built or uploaded here.
#
# From the repo root, in Git Bash (or bash on macOS/Linux), after `gcloud auth login`:
#   bash deploy/twotower/vertex-train.sh                       # T4 GPU, default settings
#   GPU=none bash deploy/twotower/vertex-train.sh              # CPU only (no GPU quota needed)
#   DRY_RUN=1 bash deploy/twotower/vertex-train.sh             # print the command, submit nothing
#   bash deploy/twotower/vertex-train.sh --epochs=5            # extra train.py flags, as --flag=value
#   RUN_ID=m1-vertex-s1 bash deploy/twotower/vertex-train.sh --seed=1
#
# Every setting can be overridden by an environment variable of the same name.
set -euo pipefail

# Git Bash would rewrite /gcs/... into a Windows path before gcloud sees it.
export MSYS_NO_PATHCONV=1
# With that rewrite off, Git Bash's `gcloud` (a POSIX sh wrapper) hands Python a /c/Users/... path
# it can't open ("E:/c/Users/.../gcloud.py: No such file"). On Windows, use the native launcher
# gcloud.cmd instead: it uses the SDK's bundled Python and Windows paths, and passes the
# arguments through unchanged. macOS/Linux/Cloud Shell have no gcloud.cmd and use plain gcloud.
GCLOUD="${GCLOUD:-$(command -v gcloud.cmd >/dev/null 2>&1 && echo gcloud.cmd || echo gcloud)}"

PROJECT="${PROJECT:-tastebridge-511403}"
REGION="${REGION:-us-central1}"   # Harvard's org policy forbids "global": always set a region
# The image, pinned by digest (commit 72945c2: export + UMAP). A digest can't be moved like a tag.
IMAGE_PINNED="${IMAGE_PINNED:-us-central1-docker.pkg.dev/tastebridge-511403/twotower/twotower-train@sha256:552558448e01b215583eeffc90051ef337d593ccaae6aa610f1b600b9d8ee2d3}"
# The identity the job runs as: the bucket, the W&B secret, Vertex and logging are granted to it.
SA="${SA:-twotower-trainer@tastebridge-511403.iam.gserviceaccount.com}"
BUCKET="${BUCKET:-tastebridge-twotower}"
DATA_VERSION="${DATA_VERSION:-gr-317756d1a1ad}"
WANDB_ENTITY="${WANDB_ENTITY:-TasteBridge}"
WANDB_SECRET="${WANDB_SECRET:-projects/${PROJECT}/secrets/wandb-api-key/versions/latest}"
GPU="${GPU:-t4}"                  # t4 | none
MACHINE="${MACHINE:-n1-standard-4}"
RUN_ID="${RUN_ID:-m1-vertex-$(date -u +%Y%m%dT%H%M%SZ)-$(openssl rand -hex 3)}"

pool="machine-type=${MACHINE},replica-count=1"
case "$GPU" in
  t4)   pool+=",accelerator-type=NVIDIA_TESLA_T4,accelerator-count=1" ;;
  none) ;;
  *)    echo "GPU must be t4 or none, got '$GPU'" >&2; exit 2 ;;
esac
pool+=",container-image-uri=${IMAGE_PINNED}"

# What the container runs: docker-entrypoint.sh train ... -> python -m twotower.train ...
# gcloud's --args is one comma-separated list, so no value may contain a comma.
train_args=(
  train
  "--data-dir=/gcs/${BUCKET}/data/${DATA_VERSION}"
  "--out=/gcs/${BUCKET}/runs"
  "--run-id=${RUN_ID}"
  "--wandb-entity=${WANDB_ENTITY}"
  "--wandb-secret=${WANDB_SECRET}"
  "$@"
)
for a in "${train_args[@]}"; do
  if [[ "$a" == *,* ]]; then echo "argument contains a comma, which --args can't carry: $a" >&2; exit 2; fi
done
args_csv="$(IFS=,; echo "${train_args[*]}")"

cmd=("$GCLOUD" ai custom-jobs create
  --project="$PROJECT" --region="$REGION"
  --display-name="twotower-train-${RUN_ID}"
  --service-account="$SA"
  --worker-pool-spec="$pool"
  --args="$args_csv"
  --labels=owner=yitong,component=m1-two-tower)

echo "run id : ${RUN_ID}"
echo "image  : ${IMAGE_PINNED}"
echo "gpu    : ${GPU} (${MACHINE})"
echo "output : gs://${BUCKET}/runs/${RUN_ID}/"
if [[ "${DRY_RUN:-0}" == "1" ]]; then
  printf '%q ' "${cmd[@]}"; echo
  exit 0
fi
"${cmd[@]}"
echo "Watch it: https://console.cloud.google.com/vertex-ai/training/custom-jobs?project=${PROJECT}"
echo "   or:    ${GCLOUD} ai custom-jobs stream-logs <JOB_ID from above> --region=${REGION} --project=${PROJECT}"
