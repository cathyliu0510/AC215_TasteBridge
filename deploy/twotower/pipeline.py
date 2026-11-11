"""The shared TasteBridge training pipeline on Vertex AI Pipelines (KFP v2): the lecture-15 workflow.

    check_data ──► train[model] ──► evaluate ──► gate: least-misery Min-Recall@10 ≥ threshold ──► publish
                   ├─ twotower: the twotower image, T4 GPU   (Yitong)
                   └─ als:      Cathy's ALS image, CPU        (Cathy)

- Only the train step differs per model. check_data, evaluate, the gate and publish are shared and
  run in the twotower image (it holds the team evaluator and `python -m twotower.steps`).
- The train step runs as a Vertex AI CustomJob (on a T4 for M1), as the twotower-trainer service account.
- Every step reads and writes gs://tastebridge-twotower through the /gcs FUSE mount. The run id is
  the pipeline job's own name, so each pipeline run gets fresh folders and its own W&B run.
- No deploy step: the app keeps serving B2 ALS (MS3-collaboration.md). A published model lands in
  gs://tastebridge-twotower/models/<model_version>/ in the backend's 4-file format.

Run from deploy/twotower/ (its own small environment; nothing here goes into the image):

    uv run python pipeline.py                                  # compile only -> train_pipeline_twotower.yaml
    uv run python pipeline.py --run                            # compile + submit the M1 pipeline
    uv run python pipeline.py --model als --als-image IMG@sha256:... --run     # Cathy's ALS branch

Submitting needs Application Default Credentials once: `gcloud auth application-default login`.
"""

# No `from __future__ import annotations`: KFP reads the component signatures (dsl.OutputPath)
# at runtime, and postponed (string) annotations break that.
import argparse
import datetime as dt
from pathlib import Path

from kfp import compiler, dsl

PROJECT = "tastebridge-511403"
REGION = "us-central1"  # Harvard's org policy forbids "global"
BUCKET = "tastebridge-twotower"
SA = f"twotower-trainer@{PROJECT}.iam.gserviceaccount.com"
# The twotower image: M1 training and every shared step (commit b0cbaee: steps + export + UMAP +
# T4 driver path). Update after each rebuild, together with IMAGE_PINNED in vertex-train.sh.
TWOTOWER_IMAGE = (
    "us-central1-docker.pkg.dev/tastebridge-511403/twotower/twotower-train"
    "@sha256:94e4c1212112a79bc46f6133b9d756ede4e64c95ab6508780fcf8df9ee429f68"
)
WANDB_ENTITY = "TasteBridge"
WANDB_SECRET = f"projects/{PROJECT}/secrets/wandb-api-key/versions/latest"
DEFAULTS = {
    "data_dir": f"/gcs/{BUCKET}/data/gr-317756d1a1ad",
    "runs_dir": f"/gcs/{BUCKET}/runs",
    "models_dir": f"/gcs/{BUCKET}/models",
    "pipeline_root": f"gs://{BUCKET}/pipeline_root",
}
# Gate threshold on TEST least-misery Min-Recall@10, fixed before the runs: "no worse than the
# strongest baseline", B1 item-kNN least misery = 0.0421 (Cathy's preference; B2 ALS is 0.0236).
THRESHOLD = 0.042
ENTRY = ["/docker-entrypoint.sh"]


def build_pipeline(
    model: str = "twotower",
    *,
    twotower_image: str = TWOTOWER_IMAGE,
    als_image: str | None = None,
    gpu: bool = True,
):
    """Return the pipeline function for one model branch (the train image is fixed at compile time)."""
    if model not in ("twotower", "als"):
        raise ValueError(f"model must be twotower or als, got {model!r}")
    if model == "als" and not als_image:
        raise ValueError("the als branch needs --als-image (Cathy's ALS train image, pinned by digest)")
    for image in (twotower_image, als_image):
        if image and "@sha256:" not in image:
            raise ValueError(f"pin images by digest (…@sha256:…), got {image}")

    @dsl.container_component
    def check_data(
        data_dir: str,
        job_name: str,
        data_version: dsl.OutputPath(str),  # type: ignore[valid-type]
        run_id: dsl.OutputPath(str),  # type: ignore[valid-type]
    ):
        # Also turns the pipeline job name into an ordinary output value (`run_id`). The GPU train
        # step is wrapped by create_custom_training_job_from_component, which resolves normal inputs
        # but NOT the special {{$.pipeline_job_name}} placeholder: the first pipeline run trained
        # into runs/{{$.pipeline_job_name}}/ while evaluate looked in runs/<job name>/. Every later
        # step therefore takes run_id from this output.
        return dsl.ContainerSpec(
            image=twotower_image,
            command=["sh", "-c"],
            args=[
                '/docker-entrypoint.sh steps check-data --data-dir "$0" --data-version-out "$1"'
                ' && mkdir -p "$(dirname "$3")" && printf %s "$2" > "$3"',
                data_dir, data_version, job_name, run_id,
            ],
        )  # fmt: skip

    if model == "twotower":

        @dsl.container_component
        def train(data_dir: str, runs_dir: str, run_id: str, wandb_entity: str, wandb_secret: str):
            return dsl.ContainerSpec(
                image=twotower_image,
                command=ENTRY,
                args=[
                    "train", "--data-dir", data_dir, "--out", runs_dir, "--run-id", run_id,
                    "--wandb-entity", wandb_entity, "--wandb-secret", wandb_secret,
                    "--no-evaluate",  # the shared evaluate step scores it
                    "--device", "cuda" if gpu else "cpu",  # fail fast if the T4 isn't visible
                ],
            )  # fmt: skip

    else:

        @dsl.container_component
        def train(data_dir: str, runs_dir: str, run_id: str, wandb_entity: str, wandb_secret: str):
            # The shared train interface (MS3-collaboration.md section 3): the image's entrypoint
            # takes `train --data-dir --out --run-id` plus the W&B flags, and writes the 4-file
            # contract to <out>/<run-id>/model/.
            return dsl.ContainerSpec(
                image=als_image,
                command=ENTRY,
                args=[
                    "train", "--data-dir", data_dir, "--out", runs_dir, "--run-id", run_id,
                    "--wandb-entity", wandb_entity, "--wandb-secret", wandb_secret,
                ],
            )  # fmt: skip

    @dsl.container_component
    def evaluate(
        model: str,
        data_dir: str,
        runs_dir: str,
        run_id: str,
        wandb_entity: str,
        wandb_secret: str,
        min_recall_lm: dsl.OutputPath(float),  # type: ignore[valid-type]
        min_recall_avg: dsl.OutputPath(float),  # type: ignore[valid-type]
    ):
        return dsl.ContainerSpec(
            image=twotower_image,
            command=ENTRY,
            args=[
                "steps", "evaluate", "--model", model, "--data-dir", data_dir,
                "--runs-dir", runs_dir, "--run-id", run_id,
                "--min-recall-lm-out", min_recall_lm, "--min-recall-avg-out", min_recall_avg,
                "--wandb-entity", wandb_entity, "--wandb-secret", wandb_secret,
            ],
        )  # fmt: skip

    @dsl.container_component
    def publish(runs_dir: str, run_id: str, models_dir: str, model_version: dsl.OutputPath(str)):  # type: ignore[valid-type]
        return dsl.ContainerSpec(
            image=twotower_image,
            command=ENTRY,
            args=[
                "steps", "publish", "--runs-dir", runs_dir, "--run-id", run_id,
                "--models-dir", models_dir, "--model-version-out", model_version,
            ],
        )  # fmt: skip

    # Lecture 15 / Vertex docs: turn the train component into a CustomJob with the machine we want.
    from google_cloud_pipeline_components.v1.custom_job import create_custom_training_job_from_component

    resources = {"machine_type": "n1-standard-4"}
    if gpu and model == "twotower":
        resources |= {"accelerator_type": "NVIDIA_TESLA_T4", "accelerator_count": 1}
    train_job = create_custom_training_job_from_component(
        train,
        display_name=f"train-{model}",
        service_account=SA,
        labels={"owner": "team", "component": f"pipeline-{model}"},  # shared pipeline: both branches
        **resources,
    )

    @dsl.pipeline(
        name=f"tastebridge-train-{model}",
        description=f"check_data -> train ({model}) -> evaluate -> gate -> publish",
    )
    def train_pipeline(
        data_dir: str = DEFAULTS["data_dir"],
        runs_dir: str = DEFAULTS["runs_dir"],
        models_dir: str = DEFAULTS["models_dir"],
        threshold: float = THRESHOLD,
        wandb_entity: str = WANDB_ENTITY,
        wandb_secret: str = WANDB_SECRET,
    ):
        # The pipeline job name (unique per run) becomes the run id, resolved once in check_data.
        checked = check_data(data_dir=data_dir, job_name=dsl.PIPELINE_JOB_NAME_PLACEHOLDER).set_display_name(
            "Check data"
        )
        run_id = checked.outputs["run_id"]
        trained = (
            train_job(
                location=REGION,
                data_dir=data_dir,
                runs_dir=runs_dir,
                run_id=run_id,
                wandb_entity=wandb_entity,
                wandb_secret=wandb_secret,
            )
            .set_display_name(f"Train ({model}{', T4' if gpu and model == 'twotower' else ', CPU'})")
            .after(checked)
        )
        scored = (
            evaluate(
                model=model,
                data_dir=data_dir,
                runs_dir=runs_dir,
                run_id=run_id,
                wandb_entity=wandb_entity,
                wandb_secret=wandb_secret,
            )
            .set_display_name("Evaluate (team evaluator, TEST)")
            .set_cpu_limit("4")
            .set_memory_limit("16G")
            .after(trained)
        )
        with dsl.If(scored.outputs["min_recall_lm"] >= threshold, name="gate-least-misery"):
            publish(runs_dir=runs_dir, run_id=run_id, models_dir=models_dir).set_display_name(
                "Publish model (4-file contract)"
            )

    return train_pipeline


def compile_pipeline(model: str, out: str | Path, **kwargs) -> Path:
    out = Path(out)
    compiler.Compiler().compile(build_pipeline(model, **kwargs), package_path=str(out))
    return out


def submit(template: Path, model: str, *, enable_caching: bool, parameters: dict) -> str:
    import google.cloud.aiplatform as aip

    # Known, harmless log on submit: 'ValueError: Output artifacts bucket "tastebridge-twotower" exists
    # but does not belong to project ...'. PipelineJob.submit() always runs an anti-bucket-squatting
    # check on pipeline_root (gcs_utils._verify_bucket_ownership). That check returns False on ANY error,
    # e.g. a submitter without project-level Resource Manager / Storage read access (we only hold
    # bucket-level roles), and submit() catches and logs the ValueError, then submits anyway. The bucket
    # is ours. Not fixable via aip.init(): in google-cloud-aiplatform 1.165.1 init() has no
    # output_artifacts_gcs_dir parameter (passing it raises TypeError), and pipeline_root is already
    # explicit below.
    aip.init(project=PROJECT, location=REGION)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")
    job = aip.PipelineJob(
        display_name=f"tastebridge-train-{model}-{stamp}",
        template_path=str(template),
        pipeline_root=DEFAULTS["pipeline_root"],
        parameter_values=parameters,
        enable_caching=enable_caching,
        labels={"owner": "team", "component": f"pipeline-{model}"},  # shared pipeline: both branches
    )
    job.submit(service_account=SA)  # returns once submitted; the run continues on Vertex
    return job.resource_name


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", choices=("twotower", "als"), default="twotower")
    ap.add_argument("--twotower-image", default=TWOTOWER_IMAGE, help="twotower image @sha256 (train + shared steps)")
    ap.add_argument("--als-image", default=None, help="Cathy's ALS train image @sha256 (model=als)")
    ap.add_argument("--gpu", choices=("t4", "none"), default="t4", help="twotower branch only")
    ap.add_argument("--threshold", type=float, default=THRESHOLD, help="gate: least-misery Min-Recall@10")
    ap.add_argument("--out", default=None, help="compiled YAML (default: train_pipeline_<model>.yaml)")
    ap.add_argument("--run", action="store_true", help="also submit to Vertex AI Pipelines")
    ap.add_argument("--cache", action="store_true", help="reuse finished steps of identical earlier runs")
    a = ap.parse_args(argv)

    if "REPLACE_WITH" in a.twotower_image:
        ap.error("set TWOTOWER_IMAGE in pipeline.py (or pass --twotower-image) to the pushed digest")
    out = Path(a.out or Path(__file__).with_name(f"train_pipeline_{a.model}.yaml"))
    compile_pipeline(a.model, out, twotower_image=a.twotower_image, als_image=a.als_image, gpu=a.gpu == "t4")
    print(f"compiled {out}")
    if a.run:
        name = submit(out, a.model, enable_caching=a.cache, parameters={"threshold": a.threshold})
        print(f"submitted {name}")
        print(f"watch: https://console.cloud.google.com/vertex-ai/pipelines/runs?project={PROJECT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
