#!/usr/bin/env python3
"""Check recorded MS3 evidence coverage without reading credentials or calling cloud APIs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED = {
    "tracked_serverless_training", "deployed_model_api", "automated_ml_workflow",
    "production_monitoring", "working_api", "milestone3_branch", "presentation",
}
STATUSES = {"verified", "pending", "local_only", "historical_only"}


def check(manifest: dict, root: Path) -> dict:
    root = root.resolve()
    errors, gaps, seen = [], [], set()
    for item in manifest.get("requirements", []):
        key = item.get("id")
        if key not in REQUIRED or key in seen:
            errors.append(f"Unknown or duplicate requirement: {key}")
            continue
        seen.add(key)
        state, evidence = item.get("status"), item.get("evidence", [])
        if state not in STATUSES:
            errors.append(f"{key}: invalid status")
        if not isinstance(evidence, list) or any(not isinstance(p, str) for p in evidence):
            errors.append(f"{key}: evidence must be a list of repository-relative paths")
            continue
        for name in evidence:
            path = (root / name).resolve()
            if Path(name).is_absolute() or not path.is_relative_to(root):
                errors.append(f"{key}: evidence must stay inside the repository")
            elif not path.is_file():
                errors.append(f"{key}: missing evidence file {name}")
        if state != "verified" or not evidence:
            gaps.append({"id": key, "status": state, "note": item.get("note", "")})
    for key in sorted(REQUIRED - seen):
        errors.append(f"Missing requirement: {key}")
    return {"recorded_evidence_complete": not errors and not gaps, "errors": errors, "gaps": gaps,
            "scope": "Manifest coverage and file presence only; not cloud execution, content quality or Canvas submission verification."}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=root / "docs/ms3/evidence/index.json")
    args = parser.parse_args()
    try:
        result = check(json.loads(args.manifest.read_text()), root)
    except (OSError, ValueError, TypeError, AttributeError) as error:
        print(json.dumps({"recorded_evidence_complete": False, "error": str(error)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0 if result["recorded_evidence_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
