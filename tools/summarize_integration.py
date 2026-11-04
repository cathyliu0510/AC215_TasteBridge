#!/usr/bin/env python3
"""Compare two successful synthetic runs and copy a small local evidence allowlist."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELECTED = {
    "run.json": "run.json", "api-check.json": "api-check.json", "api-examples.json": "api-examples.json",
    "processed/manifest.json": "processed-manifest.json", "artifacts/current/meta.json": "export-meta.json",
    "evaluation/held-out/config.json": "evaluation-config.json",
    "evaluation/held-out/summary.csv": "evaluation-summary.csv",
    "train.log": "train.log", "evaluate.log": "evaluate.log",
    "backend.log": "backend.log", "frontend.log": "frontend.log",
}


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare(a: Path, b: Path) -> dict:
    left, right = read(a / "run.json"), read(b / "run.json")
    if any(run.get("input_kind") != "synthetic" or run.get("status") != "passed" for run in (left, right)):
        raise ValueError("Only two successful, explicitly synthetic runs can enter this shareable evidence package")
    names = ["raw/" + p.name for p in sorted((a / "raw").glob("*.gz"))]
    names += ["processed/books.parquet", "processed/interactions.parquet", "artifacts/current/item_embeddings.npy",
              "artifacts/current/coords_2d.npy", "evaluation/held-out/summary.csv"]
    hashes = {name: {"a_sha256": digest(a / name), "b_sha256": digest(b / name),
                     "equal": digest(a / name) == digest(b / name)} for name in names}
    rank = lambda folder: [{"aggregation": e["request"]["aggregation"],
                           "ids": [r["book"]["book_id"] for r in e["response"]["recommendations"]]}
                          for e in read(folder / "api-examples.json")["examples"]]
    checks = {"same_source_commit_and_files": left["source_commit"] == right["source_commit"] and
               left["source_sha256"] == right["source_sha256"],
              "clean_sources": not left["source_dirty"] and not right["source_dirty"],
              "same_data_version": left["data_version"] == right["data_version"],
              "same_full_shelf_api_rankings": rank(a) == rank(b),
              "all_compared_content_hashes_match": bool(hashes) and all(v["equal"] for v in hashes.values())}
    return {"checked_at": datetime.now(timezone.utc).isoformat(), "scope": "two local synthetic runs on this environment",
            "passed": all(checks.values()), "source_commit": left["source_commit"],
            "data_version": left["data_version"], "checks": checks, "content_hashes": hashes,
            "cloud_training_evidence": False, "production_quality_evidence": False,
            "excluded_from_exact_comparison": ["timestamps", "duration", "manifest creation fields", "service ports"],
            "limits": "No cross-platform determinism, Goodreads quality, cloud execution or deployment claim."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_a", type=Path)
    parser.add_argument("run_b", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    a, b, out = args.run_a.resolve(), args.run_b.resolve(), args.out.resolve()
    result = compare(a, b)
    targets = [out / "reproducibility.json"] + [out / label / name for label in ("run-a", "run-b") for name in SELECTED.values()]
    if any(path.exists() for path in targets):
        raise ValueError("Evidence target already exists; choose a fresh output directory")
    out.mkdir(parents=True, exist_ok=True)
    for run, label in ((a, "run-a"), (b, "run-b")):
        (out / label).mkdir()
        for source, target in SELECTED.items():
            text = (run / source).read_text()
            text = text.replace(str(run), "<run>").replace(str(ROOT), "<checkout>")
            (out / label / target).write_text(text)
    (out / "reproducibility.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"passed": result["passed"], "checks": result["checks"], "evidence": str(out)}, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
