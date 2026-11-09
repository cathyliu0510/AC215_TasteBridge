# M1 two-tower: serverless training on Vertex AI (MS3)

*Owner: Yitong Li. Model code: [`src/models/twotower/`](../../src/models/twotower/README.md). Pipeline: section "ML pipeline" below (in progress).*

## In plain words

This folder holds what's needed to train TasteBridge's new learned recommender, **M1**, on Google's computers instead of a laptop:
- The program is packed into one sealed container image, the same one used locally.
- Google rents a machine with a graphics card (an NVIDIA T4), runs the program, and switches the machine off when it finishes. We pay only for those minutes.
- The program reads the book data from a private Google storage bucket. It writes the trained model and its test scores back there.
- It records every training curve in Weights & Biases (W&B), so each run can be inspected and compared later.

One command starts a run: `bash deploy/twotower/vertex-train.sh`.

## Technical overview

| Piece | Value |
|---|---|
| GCP project / region | `tastebridge-511403` / `us-central1`. Harvard's org policy forbids `global`, so every resource and command names the region. |
| Training image | `us-central1-docker.pkg.dev/tastebridge-511403/twotower/twotower-train`, pinned by digest (see "Reproducibility record") |
| Machine | `n1-standard-4` + 1× `NVIDIA_TESLA_T4` (CPU-only fallback: `GPU=none`) |
| Identity | service account `twotower-trainer@tastebridge-511403.iam.gserviceaccount.com`: objectAdmin on the bucket, Secret Accessor on `wandb-api-key`, Vertex AI User, Logs Writer |
| Data in | `gs://tastebridge-twotower/data/gr-317756d1a1ad/{processed,embeddings}`, read as `/gcs/tastebridge-twotower/data/gr-317756d1a1ad` (Cloud Storage FUSE) |
| Runs out | `gs://tastebridge-twotower/runs/<run_id>/` |
| Tracking | W&B entity `TasteBridge`, project `tastebridge-two-tower` (private, on CoreWeave Forge). The API key comes from Secret Manager `wandb-api-key` and is never in the image, the job spec or Git. |
| Submission | [`vertex-train.sh`](vertex-train.sh): `gcloud ai custom-jobs create` with a custom container (the lecture-13 `cli.sh` step) |

## Reproduce a training run

Prerequisites (one time):
- access granted by the project owner;
- `gcloud auth login` as your project account;
- Docker Desktop;
- the repo's data pulled with `dvc pull`.

All commands run from the repo root in Git Bash (Windows) or bash (macOS/Linux).

1. **Data into the bucket** (once per data version):
   ```bash
   gcloud storage cp -r data/processed data/embeddings gs://tastebridge-twotower/data/gr-317756d1a1ad/
   ```
2. **W&B key into Secret Manager** (once). The key file sits in `../secrets/`, outside the repo:
   ```bash
   gcloud secrets versions add wandb-api-key --data-file=../secrets/wandb.key --project=tastebridge-511403
   ```
3. **Build and push the image** (after any code change), from a clean, committed tree:
   ```bash
   gcloud auth configure-docker us-central1-docker.pkg.dev
   GIT_SHA=$(git rev-parse --short HEAD)
   IMAGE=us-central1-docker.pkg.dev/tastebridge-511403/twotower/twotower-train:$GIT_SHA
   docker build --platform linux/amd64 --build-arg TORCH=cu128 --build-arg GIT_COMMIT=$GIT_SHA \
       -f src/models/twotower/Dockerfile -t $IMAGE src
   docker push $IMAGE        # note the "digest: sha256:..." line
   ```
   Then put the new digest into `IMAGE_PINNED` in `vertex-train.sh`, or pass it as `IMAGE_PINNED=...@sha256:... bash deploy/twotower/vertex-train.sh`.
4. **Submit:**
   ```bash
   DRY_RUN=1 bash deploy/twotower/vertex-train.sh    # print the exact command, submit nothing
   bash deploy/twotower/vertex-train.sh              # T4 GPU
   GPU=none bash deploy/twotower/vertex-train.sh     # CPU only (no GPU quota needed)
   bash deploy/twotower/vertex-train.sh --epochs=5 --seed=1   # extra train.py flags, as --flag=value
   ```
5. **Watch:** Console → Vertex AI → Training → Custom jobs → the job → Logs. Or:
   ```bash
   gcloud ai custom-jobs stream-logs projects/790138140892/locations/us-central1/customJobs/<JOB_ID>
   ```
   The log prints `W&B run: https://forge.coreweave.com/wandb/TasteBridge/tastebridge-two-tower/runs/<id>` within seconds of the job starting.
   - The first job in a project spends a few minutes in `PENDING` (provisioning) and pulling the image (about 4.4 GB compressed). Later runs start faster.

### What a run writes (`gs://tastebridge-twotower/runs/<run_id>/`)

| Path | Content |
|---|---|
| `config.json` | every setting, data lineage (`data_version`, embedding model), git commit, torch/CUDA/GPU, Vertex job id |
| `tracking.jsonl`, `summary.json` | per-epoch log and final summary (the same values as W&B) |
| `checkpoints/last.pt` | resumable state (`--resume`) |
| `model/` | the shared **4-file contract** (`books.json`, `item_embeddings.npy`, `coords_2d.npy` with a UMAP map, `meta.json` with `model_version`, `data_version`, `wandb_run_id`) plus M1's `two_tower.pt`, `items.json`, `params.json`. Check it with `python -m twotower.export check <dir>`. |
| `test-eval/`, `headline.csv`, `metrics.json` | TEST scores from the team evaluator (`src/evaluation`), M1 next to B0/B1/B2 |

`test-eval/per_pair.csv` contains reader IDs. It stays in the private bucket and is never committed or uploaded elsewhere.

## Reproducibility record

**Reference run (T4 GPU), 2026-11-09:**

| Item | Value |
|---|---|
| Git commit (code in the image) | `68971cb` |
| Image digest | `us-central1-docker.pkg.dev/tastebridge-511403/twotower/twotower-train@sha256:fc885eda0e7397d0b874e6a196cb7ee45ee2ac08918efad36c6bb4b280b2bf3f` (linux/amd64 manifest `sha256:cfbfbccd…`) |
| Data version | `gr-317756d1a1ad` |
| Command | `bash deploy/twotower/vertex-train.sh` (defaults: T4, seed 42, `--device=cuda`; script at commit `93d226d`) |
| Vertex job | `projects/790138140892/locations/us-central1/customJobs/3911991530436427776`, `JOB_STATE_SUCCEEDED` |
| Run id / output | `m1-vertex-20261109T145047Z-c936ba` → `gs://tastebridge-twotower/runs/m1-vertex-20261109T145047Z-c936ba/` |
| Model version | `m1-tt-gr-317756d1a1ad-m1-vertex-20261109T145047Z-c936ba` (contract check OK, 5,000 books, UMAP map) |
| W&B run | <https://forge.coreweave.com/wandb/TasteBridge/tastebridge-two-tower/runs/zijfiixh> |
| Hardware / time | `n1-standard-4` + Tesla T4 (confirmed by `device: cuda (Tesla T4)` and `config.json`); fit 248 s, 115 epochs (early stop; best TUNE 0.0574 at epoch 85), about 1.6 s/epoch, 145 MB peak GPU memory; job running 14:54–15:04 UTC |

TEST Min-Recall@10 (300 pairs, team evaluator, ± = 95% CI):

| Model | Average | Least misery |
|---|---|---|
| **M1 two-tower (this run)** | **0.0642** ± 0.0067 | **0.0476** ± 0.0060 |
| B1 item-kNN | 0.0706 ± 0.0078 | 0.0421 ± 0.0062 |
| B2 ALS (served by the app) | 0.0432 ± 0.0070 | 0.0236 ± 0.0051 |
| B0 popularity | 0.0378 ± 0.0062 | 0.0378 ± 0.0062 |

**Reproducibility.** Re-running the same command with the same digest and seed reproduces the run within the 95% CI, though not bit for bit, because GPU kernels aren't deterministic. Three runs of the same configuration show it:

| Run | Where | Avg | Least misery |
|---|---|---|---|
| `m1-vertex-20261109T145047Z-c936ba` | Vertex, T4 | 0.0642 | 0.0476 |
| `m1-vertex-20261109T081535Z-bba9dd` | Vertex, CPU (see note) | 0.0636 | 0.0490 |
| `m1-defaults-s42` | local RTX 5090 container | 0.0629 | 0.0494 |

*Note:* the first job, `6137552598636429312` (image `@sha256:552558448e01…`, commit `72945c2`, W&B `7el4iyuq`), requested a T4 but trained on the CPU, because the container couldn't see the NVIDIA driver. It succeeded but took 1,434 s to fit. Commit `68971cb` fixed the driver path (`LD_LIBRARY_PATH=/usr/local/nvidia/lib64`) and made `--device=cuda` fail fast.

## Why one GPU, not several

- *Plain words:* the model is so small that a second graphics card would mostly spend its time talking to the first.
- *Technical:* M1 has 1.04 M parameters (about 4 MB of weights, about 12 MB of Adam state), and one optimiser step takes milliseconds on a T4. Lecture 13 measured 2×T4 slower than 1×T4 (41.5 s vs 25.5 s) for a small model, because gradient all-reduce dominates. Multi-GPU (DDP via `torchrun`) is therefore not applicable.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `can't open file 'E:/c/Users/.../gcloud.py'` | Git Bash's `gcloud` wrapper with `MSYS_NO_PATHCONV=1`. `vertex-train.sh` uses `gcloud.cmd` on Windows for this reason. |
| `URLs matched no objects or files` on upload | run from the repo root; `data/...` is a relative path |
| job stuck in `PENDING` or a quota error | T4 quota for `us-central1` is 0 or pending (IAM & Admin → Quotas); use `GPU=none` |
| an error mentioning `global` / `resourceLocations` | a command without `--region=us-central1` / `--location=us-central1` |
| `no W&B key found` in the job log | the secret has no version, or the service account lacks Secret Accessor |

## ML pipeline (Vertex AI Pipelines)

_In progress._ One shared KFP pipeline for all models: check_data → train(`model=twotower|als`) → evaluate → gate(least-misery ≥ threshold) → export to `gs://tastebridge-twotower/models/<model_version>/`. `pipeline.py` and run instructions will be added here. The ALS branch uses the same interface: the same arguments, and the same 4 output files.

## Cost and cleanup

- A T4 run of about 15 minutes costs well under $1; the bucket costs cents per month. Nothing bills while idle: no endpoint is deployed.
- After grading, delete old runs: `gcloud storage rm -r gs://tastebridge-twotower/runs/<run_id>`. Delete old image tags in Artifact Registry.
