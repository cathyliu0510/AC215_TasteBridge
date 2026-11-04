#!/usr/bin/env python3
"""Reproduce the served B2 path locally and record evidence. No cloud calls or publication."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def component_python(name: str) -> Path:
    base = ROOT / name / ".venv"
    path = base / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not path.is_file():
        raise ValueError(f"Missing environment: run uv sync --frozen --project {name}")
    return path


def reserve_output(path: Path) -> Path:
    path = path.resolve()
    if path.exists():
        raise ValueError("Output already exists. Use a fresh output directory; no previous run is overwritten.")
    path.mkdir(parents=True)
    return path


def synthetic_version(path: Path) -> dict:
    manifest = json.loads(path.read_text())
    # This only runs on the newly generated synthetic branch, never operator data.
    manifest["preprocessor_data_version"] = manifest["data_version"]
    manifest["data_version"] = "synthetic-" + manifest["data_version"].removeprefix("gr-")
    manifest["input_kind"] = "synthetic"
    write_json(path, manifest)
    return manifest


def available_port() -> int:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        return server.getsockname()[1]


def wait_for_service(process: subprocess.Popen, url: str, timeout: float = 30) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Service stopped with exit {process.returncode}; inspect its local log")
        try:
            with urllib.request.urlopen(url, timeout=1) as reply:
                return json.load(reply)
        except (OSError, ValueError):
            time.sleep(.1)
    raise RuntimeError("Service did not become healthy within the startup timeout")


def stop_owned(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def run(args: argparse.Namespace) -> Path:
    python = {key: component_python(value) for key, value in {
        "preprocess": "src/datapipeline/preprocess", "evaluation": "src/evaluation", "backend": "src/backend",
    }.items() if args.synthetic or key != "preprocess"}
    node = shutil.which("node")
    if not node:
        raise ValueError("Node 20+ is required for the actual frontend relay")
    processed_input = args.processed.resolve() if args.processed else None
    if processed_input and not all((processed_input / name).is_file() for name in
                                   ("books.parquet", "interactions.parquet", "manifest.json")):
        raise ValueError("Processed input requires books.parquet, interactions.parquet and manifest.json")
    out = reserve_output(args.out)
    children, handles = [], []
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
    env = dict(os.environ, PYTHONUNBUFFERED="1", GIT_COMMIT=commit,
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    source_paths = {Path(__file__).resolve(), ROOT / "deploy/cloud-run/smoke.py"}
    for folder in ("src/evaluation/evaluation", "src/backend/app", "src/datapipeline/preprocess"):
        source_paths.update(p for p in (ROOT / folder).rglob("*.py") if ".venv" not in p.parts)
    for folder in ("src/evaluation", "src/backend", "src/datapipeline/preprocess"):
        source_paths.update(ROOT / folder / name for name in ("pyproject.toml", "uv.lock"))
    source_paths.update(ROOT / "frontend/prototype" / name for name in
                        ("scripts/serve.mjs", "scripts/build-prototype.mjs", "tools/build-standalone.mjs"))
    record = {"schema_version": 1, "status": "running", "scope": "local integration only",
              "input_kind": "synthetic" if args.synthetic else "operator_supplied",
              "cloud_training": False, "cloud_deployment": False, "production_monitoring": False,
              "created_at": datetime.now(timezone.utc).isoformat(), "source_commit": commit,
              "source_dirty": dirty,
              "source_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in sorted(source_paths)},
              "parameters": {key: getattr(args, key) for key in
                             ("seed", "works", "users", "factors", "iterations", "n_pairs")},
              "stages": []}
    substitutions = [(str(out), "<run>"), (str(ROOT), "<checkout>")]
    if processed_input:
        substitutions.insert(0, (str(processed_input), "<processed-input>"))

    def portable(value: str) -> str:
        for before, after in substitutions:
            value = value.replace(before, after)
        return value

    def stage(name: str, command: list[str], cwd: Path, extra_env: dict | None = None) -> None:
        started = time.monotonic()
        item = {"name": name, "command": [portable(str(x)) for x in command], "status": "running"}
        record["stages"].append(item)
        write_json(out / "run.json", record)
        print(f"Starting {name}", flush=True)
        try:
            result = subprocess.run(command, cwd=cwd, env={**env, **(extra_env or {})},
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=600)
            (out / f"{name}.log").write_text(portable(result.stdout), encoding="utf-8")
            item.update(exit_code=result.returncode, status="passed" if result.returncode == 0 else "failed",
                        seconds=round(time.monotonic() - started, 3))
            if result.returncode:
                raise RuntimeError(f"{name} failed with exit {result.returncode}; inspect {name}.log")
        except (OSError, subprocess.TimeoutExpired) as error:
            item.update(status="failed", error=portable(str(error)))
            raise
        finally:
            write_json(out / "run.json", record)

    try:
        if args.synthetic:
            raw, processed = out / "raw", out / "processed"
            stage("generate", [str(python["preprocess"]), "synthetic_raw.py", "--out", str(raw),
                               "--works", str(args.works), "--users", str(args.users), "--seed", str(args.seed)],
                  ROOT / "src/datapipeline/preprocess")
            stage("preprocess", [str(python["preprocess"]), "preprocess.py"], ROOT / "src/datapipeline/preprocess",
                  {"RAW_DIR": str(raw), "PROCESSED_DIR": str(processed), "PREPROCESS_SEED": str(args.seed),
                   "PREPROCESS_MAX_WORKS": str(args.works), "PREPROCESS_MAX_INTERACTIONS": "500000",
                   "PREPROCESS_MIN_USER_LIKES": "5"})
            processed_manifest = synthetic_version(processed / "manifest.json")
        else:
            processed = processed_input
            processed_manifest = json.loads((processed / "manifest.json").read_text())
        record["data_version"] = processed_manifest["data_version"]
        record["processed_sha256"] = {name: sha256(processed / name) for name in
                                      ("books.parquet", "interactions.parquet", "manifest.json")}
        common = ["--als-factors", str(args.factors), "--als-iterations", str(args.iterations), "--seed", str(args.seed)]
        stage("train", [str(python["evaluation"]), "-m", "evaluation.export", "--processed", str(processed),
                        "--out", str(out / "artifacts"), *common], ROOT / "src/evaluation")
        stage("evaluate", [str(python["evaluation"]), "-m", "evaluation.run", "--interactions",
                           str(processed / "interactions.parquet"), "--books", str(processed / "books.parquet"),
                           "--out", str(out / "evaluation"), "--run-id", "held-out", "--models", "popularity,item_knn,als",
                           "--aggregations", "least_misery,average", "--favorite-counts", "5",
                           "--n-pairs", str(args.n_pairs), *common], ROOT / "src/evaluation")
        stage("frontend-build", [node, "scripts/build-prototype.mjs"], ROOT / "frontend/prototype")
        stage("frontend-release", [node, "scripts/verify-release.mjs"], ROOT / "frontend/prototype")
        artifact_dir = out / "artifacts/current"
        meta = json.loads((artifact_dir / "meta.json").read_text())
        books = json.loads((artifact_dir / "books.json").read_text())
        if len(books) < 15:
            raise ValueError("At least 15 exported books are required for the two-reader UI smoke")
        record["model_version"] = meta["model_version"]
        record["export_sha256"] = {name: sha256(artifact_dir / name) for name in
                                   ("books.json", "item_embeddings.npy", "coords_2d.npy", "meta.json")}
        record["frontend_sha256"] = sha256(ROOT / "frontend/prototype/dist/a/index.html")
        ports = [args.api_port or available_port(), args.ui_port or available_port()]
        if ports[0] == ports[1]:
            raise ValueError("Frontend and API ports must differ")
        api_base, ui_base = (f"http://127.0.0.1:{port}" for port in ports)
        services = [("backend", [str(python["backend"]), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                                  "--port", str(ports[0])], ROOT / "src/backend",
                     {"ARTIFACT_DIR": str(artifact_dir), "FEEDBACK_PATH": str(out / "feedback.jsonl")}),
                    ("frontend", [node, "scripts/serve.mjs"], ROOT / "frontend/prototype",
                     {"PORT": str(ports[1]), "TASTEBRIDGE_HOST": "127.0.0.1", "API_BASE_URL": api_base})]
        for name, command, cwd, overrides in services:
            handle = (out / f"{name}.log").open("w", encoding="utf-8")
            handles.append(handle)
            children.append(subprocess.Popen(command, cwd=cwd, env={**env, **overrides}, stdout=handle, stderr=subprocess.STDOUT))
        wait_for_service(children[0], api_base + "/health")
        wait_for_service(children[1], ui_base + "/healthz")
        spec = importlib.util.spec_from_file_location("cloud_run_contract_smoke", ROOT / "deploy/cloud-run/smoke.py")
        smoke = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(smoke)
        api_check = smoke.check(ui_base, {"num_books": len(books), "model_version": meta["model_version"],
                                        "tag": out.name}, feedback=False,
                                seed_ids=[books[0]["book_id"], books[5]["book_id"]])
        write_json(out / "api-check.json", api_check)
        query = {"api": "1", "a": ",".join(b["book_id"] for b in books[:5]),
                 "b": ",".join(b["book_id"] for b in books[5:10]), "view": "map"}
        from urllib.parse import urlencode
        record["preview_url"] = ui_base + "/a/?" + urlencode(query)
        record["stages"].append({"name": "http-integration", "status": "passed", "checks": api_check["checks"]})
        record.update(status="passed", services_stopped=False,
                      completed_at=datetime.now(timezone.utc).isoformat())
        write_json(out / "run.json", record)
        print(f"Local integration passed ({record['input_kind']}). Evidence: {out}", flush=True)
        print(record["preview_url"], flush=True)
        if args.serve:
            print("Keeping only this run's two loopback services alive. Ctrl-C stops them.", flush=True)
            while all(child.poll() is None for child in children):
                time.sleep(.5)
        return out
    except KeyboardInterrupt:
        if record["status"] != "passed":
            record["status"] = "interrupted"
        raise
    except Exception as error:
        record.update(status="failed", error=portable(str(error)))
        raise
    finally:
        for child in reversed(children):
            stop_owned(child)
        for handle in handles:
            handle.close()
        for name in ("backend.log", "frontend.log"):
            path = out / name
            if path.exists():
                path.write_text(portable(path.read_text()), encoding="utf-8")
        record["services_stopped"] = True
        write_json(out / "run.json", record)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--synthetic", action="store_true", help="Generate invented data, never fetch Goodreads")
    inputs.add_argument("--processed", type=Path, help="Use existing operator-authorized processed tables read-only")
    parser.add_argument("--out", type=Path, required=True, help="A fresh output directory")
    for name, default in (("seed", 42), ("works", 160), ("users", 400), ("factors", 16), ("iterations", 8), ("n-pairs", 20)):
        parser.add_argument("--" + name, type=int, default=default)
    parser.add_argument("--api-port", type=int, default=0)
    parser.add_argument("--ui-port", type=int, default=0)
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args(argv)
    if any(getattr(args, name) < 1 for name in ("works", "users", "factors", "iterations", "n_pairs")) or args.seed < 0:
        parser.error("Counts must be positive and seed must be nonnegative")
    if any(not 0 <= port <= 65535 for port in (args.api_port, args.ui_port)):
        parser.error("Ports must be 0 (automatic) or between 1 and 65535")
    if args.api_port and args.api_port == args.ui_port:
        parser.error("Frontend and API ports must differ")
    return args


if __name__ == "__main__":
    try:
        run(parse_args())
    except KeyboardInterrupt:
        print("Local services stopped.")
        sys.exit(130)
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(f"Integration failed: {error}", file=sys.stderr)
        sys.exit(1)
