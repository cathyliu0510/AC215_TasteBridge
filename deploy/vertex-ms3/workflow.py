#!/usr/bin/env python3
"""Offline MS3 candidate: plan -> verify processed inputs -> B2 export -> evaluation.

No cloud client, downloader, credential reader, submitter, or tracking SDK is used.
The default worker mode validates provenance only. See README before activation.
"""
from __future__ import annotations

import argparse
import base64
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
INPUTS = ("books.parquet", "interactions.parquet", "manifest.json")
EXPORTS = ("books.json", "item_embeddings.npy", "coords_2d.npy", "meta.json")
PARAMETERS = {
    "als": {"factors": 128, "regularization": 50.0, "alpha": 20.0,
            "iterations": 15, "seed": 42},
    "evaluation": {"models": ["popularity", "item_knn", "als"],
                   "aggregations": ["average", "least_misery", "merged_seeds"],
                   "favorite_counts": [5], "n_pairs": 300, "k": 10,
                   "knn_neighbors": 100, "split": "test"},
}
SHA = re.compile(r"[0-9a-f]{64}\Z")
SLUG = re.compile(r"[a-z][a-z0-9-]{2,62}\Z")
VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")


class CandidateError(ValueError):
    """Invalid candidate or provenance; no downstream stage may continue."""


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise CandidateError(f"Expected a regular, non-symlink file: {path.name}")
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, value: Any) -> None:
    # Direct close is deliberate: a future /gcs persistence path has no POSIX rename guarantee.
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def storage_path(uri: str) -> Path:
    if not isinstance(uri, str) or not re.fullmatch(
        r"gs://[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]/[A-Za-z0-9._/-]+", uri
    ):
        raise CandidateError("Use an explicit gs://bucket/nonempty-prefix URI; no query or credentials")
    parts = uri[5:].split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise CandidateError("Storage URI contains an empty or traversing path component")
    return Path("/gcs", *parts)


def source_files(root: Path) -> dict[str, str]:
    folders = root / "src/evaluation/evaluation"
    files = sorted(folders.rglob("*.py"))
    if folders.is_symlink() or not files or any(p.is_symlink() for p in folders.rglob("*")):
        raise CandidateError("Missing evaluation source or symlink in evaluation package")
    files += [root / "src/evaluation" / name for name in
              ("pyproject.toml", "uv.lock", ".python-version", "Dockerfile")]
    files += [root / "deploy/vertex-ms3" / name for name in ("workflow.py", "Dockerfile")]
    return {p.relative_to(root).as_posix(): sha256(p) for p in files}


def manifest_identity(path: Path) -> dict[str, Any]:
    manifest_hash = sha256(path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    version = manifest.get("data_version", "")
    if manifest.get("stage") != "preprocess" or not isinstance(version, str) or not VERSION.fullmatch(version):
        raise CandidateError("Expected an existing preprocess manifest with a safe data_version")
    files = manifest.get("files", {})
    if not isinstance(files, dict) or any(
        not isinstance(files.get(name), str) or not SHA.fullmatch(files[name]) for name in INPUTS[:2]
    ):
        raise CandidateError("Preprocess manifest must pin both table SHA256 hashes")
    synthetic = (version.startswith("synthetic-") or manifest.get("input_kind") == "synthetic"
                 or manifest.get("inputs", {}).get("mode") == "synthetic")
    return {"data_version": version,
            "input_kind": "synthetic" if synthetic else "operator_supplied_processed",
            "files_sha256": {name: files[name] for name in INPUTS[:2]} | {"manifest.json": manifest_hash}}


def validate_plan(plan: dict[str, Any]) -> None:
    try:
        if set(plan) != {"schema_version", "status", "run_id", "created_at", "source", "input",
                         "parameters", "parameters_sha256", "vertex", "tracking"}:
            raise CandidateError("Unknown or missing plan fields")
        if plan["schema_version"] != 1 or plan["status"] != "unexecuted_candidate":
            raise CandidateError("Only an unexecuted schema-1 candidate is accepted")
        if not SLUG.fullmatch(plan["run_id"]):
            raise CandidateError("run_id must be a 3–63 character lowercase slug")
        if canonical(plan["parameters"]) != canonical(PARAMETERS) or plan["parameters_sha256"] != digest(PARAMETERS):
            raise CandidateError("Candidate must preserve the existing tuned ALS and evaluation defaults")
        source = plan["source"]
        if set(source) != {"base_commit", "files_sha256", "fingerprint_sha256"}:
            raise CandidateError("Unknown source provenance fields")
        if not re.fullmatch(r"[0-9a-f]{40}", source["base_commit"]):
            raise CandidateError("base_commit must be a full 40-character Git SHA")
        if not source["files_sha256"] or any(not SHA.fullmatch(v) for v in source["files_sha256"].values()):
            raise CandidateError("Invalid source hashes")
        if source["fingerprint_sha256"] != digest(source["files_sha256"]):
            raise CandidateError("Source fingerprint mismatch")
        inp = plan["input"]
        if set(inp) != {"data_version", "input_kind", "files_sha256", "processed_uri", "approval_reference"}:
            raise CandidateError("Unknown input fields")
        if not VERSION.fullmatch(inp["data_version"]) or inp["input_kind"] not in (
            "synthetic", "operator_supplied_processed"
        ):
            raise CandidateError("Invalid input identity")
        if set(inp["files_sha256"]) != set(INPUTS) or any(
            not SHA.fullmatch(v) for v in inp["files_sha256"].values()
        ):
            raise CandidateError("Input must pin exactly the two processed tables and manifest")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}", inp["approval_reference"]):
            raise CandidateError("Use a short non-secret input approval/evidence reference")
        input_path = storage_path(inp["processed_uri"])
        vertex = plan["vertex"]
        if set(vertex) != {"project", "region", "image_uri", "service_account", "machine_type",
                           "timeout_seconds", "output_uri"}:
            raise CandidateError("Unknown cloud configuration fields")
        project = vertex["project"]
        if not re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", project):
            raise CandidateError("Invalid explicit project ID")
        if not re.fullmatch(r"[a-z]+-[a-z]+[0-9]+", vertex["region"]):
            raise CandidateError("Invalid region")
        if not re.fullmatch(r"(?:[a-z0-9-]+-docker\.pkg\.dev|gcr\.io)/[a-z0-9._/-]+@sha256:[0-9a-f]{64}",
                            vertex["image_uri"]):
            raise CandidateError("Image must be an immutable Artifact Registry/GCR SHA256 digest")
        if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]@" + re.escape(project) +
                            r"\.iam\.gserviceaccount\.com", vertex["service_account"]):
            raise CandidateError("Use an explicit service account in the selected project")
        if vertex["machine_type"] not in ("n1-standard-4", "n1-standard-8", "n2-standard-4", "n2-standard-8"):
            raise CandidateError("Candidate supports only the reviewed CPU machine sizes")
        if type(vertex["timeout_seconds"]) is not int or not 300 <= vertex["timeout_seconds"] <= 7200:
            raise CandidateError("Use a bounded timeout between 300 and 7200 seconds")
        output_path = storage_path(vertex["output_uri"])
        if (input_path == output_path or input_path in output_path.parents
                or output_path in input_path.parents):
            raise CandidateError("Input and output storage prefixes must be disjoint")
        if plan["tracking"] != {"backend": "local_structured_receipts", "acceptance": "pending_team_tf",
                                "external_run_url": None, "cloud_job_name": None}:
            raise CandidateError("Candidate cannot claim an external tracker or a completed cloud job")
    except (KeyError, TypeError, AttributeError) as exc:
        raise CandidateError("Malformed plan") from exc


def make_plan(*, root: Path, manifest: Path, base_commit: str, run_id: str,
              processed_uri: str, approval_reference: str, project: str, region: str,
              image_uri: str, service_account: str, output_uri: str,
              machine_type: str = "n1-standard-4", timeout_seconds: int = 3600) -> dict[str, Any]:
    files = source_files(root)
    plan = {"schema_version": 1, "status": "unexecuted_candidate", "run_id": run_id, "created_at": now(),
            "source": {"base_commit": base_commit, "files_sha256": files, "fingerprint_sha256": digest(files)},
            "input": manifest_identity(manifest) | {"processed_uri": processed_uri,
                                                     "approval_reference": approval_reference},
            "parameters": json.loads(canonical(PARAMETERS)), "parameters_sha256": digest(PARAMETERS),
            "vertex": {"project": project, "region": region, "image_uri": image_uri,
                       "service_account": service_account, "machine_type": machine_type,
                       "timeout_seconds": timeout_seconds, "output_uri": output_uri},
            "tracking": {"backend": "local_structured_receipts", "acceptance": "pending_team_tf",
                         "external_run_url": None, "cloud_job_name": None}}
    validate_plan(plan)
    return plan


def custom_job_request(plan: dict[str, Any]) -> dict[str, Any]:
    validate_plan(plan)
    vertex = plan["vertex"]
    encoded = base64.urlsafe_b64encode(canonical(plan)).decode()
    # Deliberately lacks --execute / --persist-output. Activation is a separate review decision.
    args = ["run", "--plan-base64", encoded, "--processed", str(storage_path(plan["input"]["processed_uri"])),
            "--out", f"/tmp/tastebridge-ms3/{plan['run_id']}"]
    return {"displayName": f"tastebridge-{plan['run_id']}",
            "labels": {"project": "tastebridge", "ms3-status": "unexecuted-candidate"},
            "jobSpec": {"serviceAccount": vertex["service_account"],
                        "baseOutputDirectory": {"outputUriPrefix": vertex["output_uri"]},
                        "scheduling": {"timeout": f"{vertex['timeout_seconds']}s"},
                        "workerPoolSpecs": [{"machineSpec": {"machineType": vertex["machine_type"]},
                                             "replicaCount": "1",
                                             "containerSpec": {"imageUri": vertex["image_uri"],
                                                               "command": ["python", "/app/source/deploy/vertex-ms3/workflow.py"],
                                                               "args": args}}]}}


def verify_inputs(plan: dict[str, Any], processed: Path) -> dict[str, str]:
    if processed.is_symlink() or not processed.is_dir():
        raise CandidateError("Processed input must be an existing non-symlink directory")
    hashes = {name: sha256(processed / name) for name in INPUTS}
    if hashes != plan["input"]["files_sha256"]:
        raise CandidateError("Processed input content does not match the pinned snapshot")
    identity = manifest_identity(processed / "manifest.json")
    if any(identity[key] != plan["input"][key] for key in identity):
        raise CandidateError("Processed manifest identity differs from the plan")
    return hashes


def commands(plan: dict[str, Any], processed: Path, out: Path) -> list[tuple[str, list[str]]]:
    als, ev = plan["parameters"]["als"], plan["parameters"]["evaluation"]
    common = ["--als-factors", str(als["factors"]), "--als-reg", str(als["regularization"]),
              "--als-alpha", str(als["alpha"]), "--als-iterations", str(als["iterations"]),
              "--seed", str(als["seed"])]
    return [("export", [sys.executable, "-m", "evaluation.export", "--processed", str(processed),
                        "--out", str(out / "artifacts"), *common]),
            ("evaluate", [sys.executable, "-m", "evaluation.run", "--interactions", str(processed / INPUTS[1]),
                          "--books", str(processed / INPUTS[0]), "--out", str(out / "evaluation"),
                          "--run-id", "held-out", "--models", ",".join(ev["models"]),
                          "--aggregations", ",".join(ev["aggregations"]), "--favorite-counts", "5",
                          "--n-pairs", str(ev["n_pairs"]), "--k", str(ev["k"]),
                          "--knn-neighbors", str(ev["knn_neighbors"]), "--split", ev["split"], *common])]


def verify_outputs(plan: dict[str, Any], out: Path) -> tuple[dict[str, str], list[dict[str, Any]]]:
    artifact = out / "artifacts/current"
    for relative in ("artifacts", "artifacts/current", "evaluation", "evaluation/held-out"):
        if (out / relative).is_symlink():
            raise CandidateError("Output directories cannot be symlinks")
    for name in EXPORTS:
        sha256(artifact / name)
    meta = json.loads((artifact / "meta.json").read_text())
    if (meta.get("data_version") != plan["input"]["data_version"]
            or meta.get("model_version") != "b2-als-" + plan["input"]["data_version"]
            or meta.get("hyperparameters") != plan["parameters"]["als"]
            or meta.get("code_version") != "source-sha256:" + plan["source"]["fingerprint_sha256"]):
        raise CandidateError("Export metadata does not match input, parameters or source")
    evdir = out / "evaluation/held-out"
    for name in ("config.json", "summary.csv", "summary.md"):
        sha256(evdir / name)
    config = json.loads((evdir / "config.json").read_text())
    if config.get("git_commit") != "source-sha256:" + plan["source"]["fingerprint_sha256"]:
        raise CandidateError("Evaluation source does not match the plan")
    if any(config.get("data", {}).get(key, {}).get("sha256") != plan["input"]["files_sha256"][name]
           for key, name in (("books", INPUTS[0]), ("interactions", INPUTS[1]))):
        raise CandidateError("Evaluation used different input tables")
    args = config.get("arguments", {})
    expected = {"synthetic": False, "als_factors": 128, "als_reg": 50.0, "als_alpha": 20.0,
                "als_iterations": 15, "seed": 42, **plan["parameters"]["evaluation"]}
    if any(args.get(k) != v for k, v in expected.items()):
        raise CandidateError("Evaluation parameters do not match the plan")
    with (evdir / "summary.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    metrics = []
    for row in rows:
        if row.get("pair_kind") != "all":
            continue
        entry = {k: row[k] for k in ("model", "aggregation", "n_favorites")}
        for key in ("min_recall", "mean_ndcg", "long_tail_coverage"):
            value = float(row[key])
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise CandidateError("Invalid aggregate evaluation metric")
            entry[key] = value
        metrics.append(entry)
    expected_groups = {(m, a, "5") for m in plan["parameters"]["evaluation"]["models"]
                       for a in plan["parameters"]["evaluation"]["aggregations"]}
    groups = {(m["model"], m["aggregation"], m["n_favorites"]) for m in metrics}
    if groups != expected_groups or len(metrics) != len(expected_groups):
        raise CandidateError("Evaluation summary is incomplete or duplicated")
    # Reader-level per_pair.csv and sample_recommendations.json are intentionally excluded.
    selected = [artifact / name for name in EXPORTS] + [evdir / name for name in
                ("config.json", "summary.csv", "summary.md")]
    return {p.relative_to(out).as_posix(): sha256(p) for p in selected}, metrics


def run_worker(plan: dict[str, Any], *, root: Path, processed: Path, out: Path,
               execute: bool = False, persist_output: bool = False,
               runner: Any = subprocess.run, clock: Any = None) -> dict[str, Any]:
    clock = clock or time.monotonic
    started = clock()
    validate_plan(plan)
    total_budget = plan["vertex"]["timeout_seconds"]
    finalize_reserve = min(120, total_budget // 5)
    deadline = started + total_budget
    processed, root = processed.absolute(), root.resolve()
    out = out.absolute()
    if out.is_symlink() or out.exists():
        raise CandidateError("Choose a new output directory; existing runs are never overwritten")
    resolved = out.resolve()
    if resolved == processed.resolve() or resolved in processed.resolve().parents or processed.resolve() in resolved.parents:
        raise CandidateError("Input and output directories must be disjoint")
    if resolved == root or resolved in root.parents or root / "src/evaluation" == resolved or root / "src/evaluation" in resolved.parents:
        raise CandidateError("Output may not overwrite source")
    if persist_output and not execute:
        raise CandidateError("A dry run cannot persist outputs to Cloud Storage")
    out.mkdir(parents=True, exist_ok=False)
    receipt = {"schema_version": 1, "status": "validating", "candidate_status": "unexecuted_candidate",
               "created_at": now(), "plan_sha256": digest(plan), "run_id": plan["run_id"],
               "parameters": plan["parameters"], "parameters_sha256": plan["parameters_sha256"], "source": plan["source"],
               "input": plan["input"], "stages": [], "outputs_sha256": {},
               "cloud_execution_verified": False, "external_tracking_verified": False,
               "budget": {"total_seconds": total_budget, "finalization_reserve_seconds": finalize_reserve,
                          "terminal_receipt_reserve_seconds": 5,
                          "scope": "one shared monotonic budget across validation, children and finalization"},
               "validation_scope": "file/config/provenance; dry run does not read parquet tables or fit models"}

    def remaining_budget(*, finalizing: bool = False) -> float:
        remaining = deadline - clock() - (5 if finalizing else finalize_reserve)
        if remaining <= 0:
            raise CandidateError("Shared job budget exhausted; stopping before the platform timeout")
        return remaining

    def checkpoint(status: str) -> None:
        receipt["status"] = status
        receipt["updated_at"] = now()
        write_json(out / "receipt.json", receipt)
        event = {"at": now(), "run_id": plan["run_id"], "status": status,
                 "plan_sha256": receipt["plan_sha256"], "stages": receipt["stages"]}
        with (out / "tracking.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(canonical(event).decode() + "\n")

    snapshot = None
    try:
        write_json(out / "plan.json", plan)
        checkpoint("validating")
        if source_files(root) != plan["source"]["files_sha256"]:
            raise CandidateError("Source or locked environment differs from the plan")
        receipt["stages"].append({"stage": "source_provenance", "status": "verified"})
        receipt["verified_inputs_sha256"] = verify_inputs(plan, processed)
        receipt["stages"].append({"stage": "input_provenance", "status": "verified"})
        steps = commands(plan, processed.resolve(), out.resolve())
        receipt["commands"] = {name: command for name, command in steps}
        if not execute:
            checkpoint("dry_run_validated")
            return receipt
        # Only approved processed files enter this private, disposable snapshot. Hash the copies
        # so a mutable shared/FUSE input cannot silently change what each child reads.
        snapshot = Path(tempfile.mkdtemp(prefix="tastebridge-ms3-processed-"))
        for name in INPUTS:
            shutil.copyfile(processed / name, snapshot / name)
        verify_inputs(plan, snapshot)
        steps = commands(plan, snapshot, out.resolve())
        receipt["commands"] = {name: command for name, command in steps}
        receipt["stages"].append({"stage": "private_processed_snapshot", "status": "verified"})
        # These modules need the existing locked evaluation environment; never auto-install it.
        env = dict(os.environ, PYTHONPATH=str(root / "src/evaluation"),
                   GIT_COMMIT="source-sha256:" + plan["source"]["fingerprint_sha256"],
                   WANDB_MODE="disabled", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
        for stage, command in steps:
            if source_files(root) != plan["source"]["files_sha256"]:
                raise CandidateError("Source changed before a stage")
            stage_timeout = remaining_budget()
            record = {"stage": stage, "status": "running", "started_at": now(),
                      "timeout_seconds": round(stage_timeout, 3)}
            receipt["stages"].append(record)
            checkpoint("running")
            with (out / f"{stage}.log").open("w", encoding="utf-8") as log:
                result = runner(command, cwd=root / "src/evaluation", env=env, stdout=log,
                                stderr=subprocess.STDOUT, check=False,
                                timeout=stage_timeout)
            record["returncode"] = result.returncode
            record["status"] = "completed" if result.returncode == 0 else "failed"
            record["ended_at"] = now()
            if result.returncode != 0:
                raise CandidateError(f"{stage} failed; see private local log")
            checkpoint("running")
        remaining_budget(finalizing=True)
        receipt["outputs_sha256"], metrics = verify_outputs(plan, out)
        write_json(out / "metrics.json", {"scope": "held-out fits, separate from all-user serving export",
                                          "input_kind": plan["input"]["input_kind"], "metrics": metrics})
        receipt["outputs_sha256"]["metrics.json"] = sha256(out / "metrics.json")
        receipt["outputs_sha256"]["plan.json"] = sha256(out / "plan.json")
        verify_inputs(plan, snapshot)
        if verify_inputs(plan, processed) != receipt["verified_inputs_sha256"]:
            raise CandidateError("Input changed during execution")
        if source_files(root) != plan["source"]["files_sha256"]:
            raise CandidateError("Source changed during execution")
        remaining_budget(finalizing=True)
        receipt["stages"].append({"stage": "output_provenance", "status": "verified"})
        checkpoint("completed_local")
        if persist_output:
            destination = storage_path(plan["vertex"]["output_uri"]) / plan["run_id"]
            if not Path("/gcs").is_dir():
                raise CandidateError("Expected a prepared /gcs filesystem; this worker does not create or mount it")
            destination.mkdir(parents=True, exist_ok=False)
            for name, expected_hash in receipt["outputs_sha256"].items():
                remaining_budget(finalizing=True)
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(out / name, target)
                if sha256(target) != expected_hash:
                    raise CandidateError("Persisted output hash mismatch")
            # Completion receipt is written last; incomplete copies have no success receipt.
            remaining_budget(finalizing=True)
            shutil.copyfile(out / "tracking.jsonl", destination / "tracking.jsonl")
            write_json(destination / "receipt.json", receipt | {"persistence_status": "copied_and_hash_verified"})
        return receipt
    except BaseException as exc:
        if receipt["stages"] and receipt["stages"][-1].get("status") == "running":
            receipt["stages"][-1]["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        # Do not serialize exception strings: they can contain private data or environment values.
        receipt["failure_type"] = type(exc).__name__
        checkpoint("interrupted" if isinstance(exc, KeyboardInterrupt) else "failed")
        raise
    finally:
        if snapshot is not None:
            shutil.rmtree(snapshot)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("plan", help="Generate offline JSON; no cloud call")
    for name in ("manifest", "base-commit", "run-id", "processed-uri", "approval-reference", "project",
                 "region", "image-uri", "service-account", "output-uri", "out"):
        p.add_argument("--" + name, required=True)
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--machine-type", default="n1-standard-4")
    p.add_argument("--timeout-seconds", type=int, default=3600)
    p = sub.add_parser("context", help="Stage only pinned source/lock files for a later image build")
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("run", help="Validate locally by default; fitting needs --execute")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--plan", type=Path)
    group.add_argument("--plan-base64")
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--processed", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--persist-output", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "plan":
            kwargs = vars(args).copy()
            kwargs.pop("action")
            out = Path(kwargs.pop("out"))
            kwargs["manifest"] = Path(kwargs["manifest"])
            plan = make_plan(**kwargs)
            out.mkdir(parents=True, exist_ok=False)
            write_json(out / "plan.json", plan)
            write_json(out / "custom-job-request.json", custom_job_request(plan))
            write_json(out / "review.json", {"status": "unexecuted_candidate", "submitted": False,
                       "worker_default": "dry_run", "actual_tables_verified": False,
                       "required_decisions": ["reconcile existing team workflow/runs", "input approval and staged hashes",
                                              "built image digest and source match", "service account/access and cost approval",
                                              "TF acceptance of workflow and experiment tracking", "authorized execution and evidence capture"]})
            print("Generated unexecuted candidate; no cloud submission or training occurred.")
        elif args.action == "context":
            files = source_files(args.root)
            args.out.mkdir(parents=True, exist_ok=False)
            for name, expected in files.items():
                target = args.out / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(args.root / name, target)
                if sha256(target) != expected:
                    raise CandidateError("Build context source changed during staging")
            write_json(args.out / "source-files.sha256.json", files)
            print("Staged source-only context; no image build or upload occurred.")
        else:
            raw = args.plan.read_bytes() if args.plan else base64.b64decode(args.plan_base64, altchars=b"-_", validate=True)
            plan = json.loads(raw)
            receipt = run_worker(plan, root=args.root, processed=args.processed, out=args.out,
                                 execute=args.execute, persist_output=args.persist_output)
            print(receipt["status"])
        return 0
    except (CandidateError, OSError, json.JSONDecodeError) as exc:
        print(f"Candidate stopped: {type(exc).__name__}. Inspect local receipt/configuration.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
