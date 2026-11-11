# M1 two-tower: serverless training on Vertex AI (MS3)

*Owner: Yitong Li. Model code: [`src/models/twotower/`](../../src/models/twotower/README.md). Pipeline: section "ML pipeline" below. Evidence screenshots: [`docs/ms3/two-tower/`](../../docs/ms3/two-tower/) (training) and [`docs/ms3/pipeline/`](../../docs/ms3/pipeline/) (pipeline).*

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

*Owners: Yitong (pipeline, shared steps, M1 branch), Cathy (ALS branch). Code: [`pipeline.py`](pipeline.py) (KFP v2, the lecture-15 workflow), the shared steps in [`src/models/twotower/twotower/steps.py`](../../src/models/twotower/twotower/steps.py), and the ALS train step in `src/evaluation/evaluation/pipeline_train.py`.*

### In plain words

Training a model by hand means doing five chores in order: check the data, train, score the model, decide whether it is good enough, and file it away. The pipeline is a written recipe for those chores. We hand the recipe to Google (Vertex AI Pipelines), which runs each chore on a rented machine as soon as the one before it finishes, records what every chore produced, and draws the whole run as a graph with a green tick per finished step.

The recipe has one interchangeable station: the training step can cook either of two models, our new **M1 two-tower** or the app's current **ALS** model. Every other station is shared, so both models are checked, scored and filed by exactly the same rules.

There is one safety rule: **a model is only filed for use if it scores at least as well as a bar we set in advance.** The bar is the score of our strongest simple baseline (item-kNN). M1 clears it and gets filed. ALS doesn't clear it, so its run stops before filing. That's the safety rule doing its job, and it's the expected outcome.

### Technical

```text
check_data ──► train[model] ──► evaluate ──► gate: TEST least-misery Min-Recall@10 ≥ 0.042 ──► publish
               ├─ model=twotower: twotower image, Vertex CustomJob, n1-standard-4 + 1× T4   (Yitong)
               └─ model=als:      als-train image, Vertex CustomJob, n1-standard-4, CPU     (Cathy)
```

| Step | Runs in | What it does | Outputs |
|---|---|---|---|
| `check_data` | twotower image | checks every input file exists, reads `data_version` from `processed/manifest.json`, and checks every book has a description vector. It also turns the pipeline job name into an ordinary output, `run_id` (see the note below). | `data_version`, `run_id` |
| `train` | the branch's image, as a Vertex **CustomJob** (`create_custom_training_job_from_component`), as `twotower-trainer` | `train --data-dir --out --run-id --wandb-entity --wandb-secret` writes `runs/<run_id>/model/` in the shared 4-file format. M1 also logs its training curves to W&B; `--no-evaluate` leaves scoring to the next step. | files in `gs://tastebridge-twotower/runs/<run_id>/` |
| `evaluate` | twotower image (4 CPU, 16 GB) | the **team evaluator** (`src/evaluation`), unchanged, on the TEST split: 300 pairs, K = 10, 5 favourites, seed 42. TEST metrics go into the training W&B run (M1) or a new W&B run (ALS). | `min_recall_lm`, `min_recall_avg` |
| gate `gate-least-misery` | KFP `dsl.If` | runs `publish` only if `min_recall_lm ≥ threshold` | — |
| `publish` | twotower image | checks the 4-file format and copies it to `gs://tastebridge-twotower/models/<model_version>/`, `meta.json` last. A published version is never overwritten. | `model_version` |

- **Threshold 0.042** is B1 item-kNN's TEST least-misery Min-Recall@10 (0.0421), fixed before any pipeline run: "never publish something worse than the strongest baseline". We gate on least misery because it is the rule that protects the less-served reader of a pair.
- **The ALS branch stopping at the gate is intended.** ALS scores 0.024 least misery, below 0.042, so its run shows 4/5 steps and a skipped gate. That demonstrates the gate blocking a weaker model. The app still serves that ALS export; publishing here is a separate, quality-gated channel.
- **What evaluate scores for `model=als`.** For M1, evaluate loads the trained model from `runs/<run_id>/model/` and scores exactly that file. For ALS, the team evaluator **refits** ALS (with the same tuned settings) on the TRAIN readers and scores that, together with B0 and B1. This is how B2 was scored in MS2, and it keeps test readers out of training. The train step, by contrast, exports ALS fitted on all readers, the version the app serves. So for ALS the gate judges a train-split refit with identical settings, not the exact exported file. Both use the same deterministic settings, which is why the scores match MS2 to the last digit.
- **Run id.** The run id is the pipeline job's own name, so every run writes to fresh folders. The GPU train step is wrapped as a CustomJob, which does not resolve KFP's `{{$.pipeline_job_name}}` placeholder. The first run, `tastebridge-train-twotower-20261109112116`, failed at evaluate for that reason. Since commit `d05a6be`, `check_data` resolves the name once and every later step takes `run_id` from it.
- **Images are pinned by digest** (`pipeline.py` refuses a tag), so a run can always be traced to the exact code.

### Run it

From `deploy/twotower/`, which has its own small environment (KFP, pipeline components, the Vertex AI SDK); nothing in it goes into an image. Submitting needs `gcloud auth application-default login` once, and Service Account User on `twotower-trainer`.

```bash
cd deploy/twotower
uv sync
uv run pytest -q                                   # compile-only tests: no cloud, no Docker

# M1 two-tower branch (T4). The twotower image digest is TWOTOWER_IMAGE in pipeline.py.
uv run python pipeline.py                          # compile only -> train_pipeline_twotower.yaml
uv run python pipeline.py --run                    # compile + submit to Vertex AI Pipelines
uv run python pipeline.py --gpu none --run         # same branch on CPU (no GPU quota needed)

# ALS branch (Cathy's image, CPU)
uv run python pipeline.py --model als \
  --als-image us-central1-docker.pkg.dev/tastebridge-511403/twotower/als-train@sha256:6d8aed0e68727db2373aa75e093fe7bf9c7f2a5d806777217e8d0d5df1d53edb \
  --run

# Optional flags: --threshold 0.042   --cache (reuse finished steps of an identical earlier run)
```

Watch the run under Console → Vertex AI → Pipelines → Runs. Click a node to see its inputs and outputs, and use **View logs** for its Cloud Logging output.

**Known harmless warning.** Submitting logs `ValueError: Output artifacts bucket "tastebridge-twotower" exists but does not belong to project ...`, and the job is created anyway:
- *Cause.* `PipelineJob.submit()` always runs the SDK's anti-bucket-squatting check on the pipeline root. That check reports "not ours" on **any** error, such as a submitter who has only bucket-level roles and no project-wide read access. `submit()` then logs the error and continues.
- *Why there's no fix.* The bucket is ours. `aip.init()` in google-cloud-aiplatform 1.165.1 has no `output_artifacts_gcs_dir` parameter (passing it raises `TypeError`), and `pipeline_root` is already explicit. A test (`test_submit_uses_only_supported_init_arguments`) guards this.

### Completed runs (evidence)

| | M1 two-tower | ALS |
|---|---|---|
| Pipeline run | `tastebridge-train-twotower-20261109172259` | `tastebridge-train-als-20261110212016` |
| Result | **5/5 steps**: gate passed, model published | **4/5 steps**: gate not triggered (intended) |
| Duration | 23 min 21 s (train on T4; evaluate 9 min 1 s) | 23 min |
| Train image | `twotower-train@sha256:94e4c121…` (commit `b0cbaee`) | `als-train@sha256:6d8aed0e…` (commit `3d292f9`) |
| Pipeline code | commit `d05a6be` | commit `d05a6be` + PR #14 |
| TEST Min-Recall@10, least misery / average | **0.0468** / 0.062 | 0.0236 / 0.0432 (identical to MS2) |
| Published | `models/m1-tt-gr-317756d1a1ad-tastebridge-train-twotower-20261109172259/` | — (blocked by the gate) |
| Screenshots | [run graph](../../docs/ms3/pipeline/twotower-pipeline-run.png) · [evaluate outputs](../../docs/ms3/pipeline/twotower-pipeline-evaluate.png) · [publish output](../../docs/ms3/pipeline/twotower-pipeline-publish.png) · W&B [loss](../../docs/ms3/pipeline/twotower-pipeline-wandb-train-loss.png), [TUNE metric](../../docs/ms3/pipeline/twotower-pipeline-wandb-tune-min-recall.png) | [run graph](../../docs/ms3/pipeline/als-pipeline-run.png) · [evaluate outputs](../../docs/ms3/pipeline/als-pipeline-evaluate.png) (PR #14) |

In both runs the baselines (B0 0.0378, B1 0.0706 / 0.0421, B2 0.0432 / 0.0236) are identical to the standalone runs, so the evaluator is deterministic across machines and runs. M1's pipeline score is within the 95% CI of the three standalone runs in "Reproducibility record" above. All runs use the same `data_version`, `gr-317756d1a1ad`.

**Standalone training evidence** (section "Reproducibility record"): [Vertex custom jobs](../../docs/ms3/two-tower/vertex-custom-jobs.png) · [T4 job details](../../docs/ms3/two-tower/vertex-t4-job-details.png) · W&B [loss](../../docs/ms3/two-tower/wandb-t4-train-loss.png), [TUNE metric](../../docs/ms3/two-tower/wandb-t4-tune-min-recall.png).

**Not in the pipeline (future work).**
- The CPU-only steps run in the 4.4 GB CUDA training image. A slim CPU image would start them faster.
- There is no deploy step: the app keeps serving B2 ALS, and switching models is a team decision.

## Cost and cleanup

- A T4 run of about 15 minutes costs well under $1; the bucket costs cents per month. Nothing bills while idle: no endpoint is deployed.
- After grading, delete old runs: `gcloud storage rm -r gs://tastebridge-twotower/runs/<run_id>`. Delete old image tags in Artifact Registry.
