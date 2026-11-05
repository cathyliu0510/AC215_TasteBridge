#!/usr/bin/env python3
"""Compare two successful synthetic runs and copy a small local evidence allowlist."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.evidence_contracts import EXPORTS, canonical_sha256, file_sha256, read_json, regular_within

SELECTED = {
    "run.json": "run.json", "api-check.json": "api-check.json", "api-examples.json": "api-examples.json",
    "processed/manifest.json": "processed-manifest.json", "artifacts/current/meta.json": "export-meta.json",
    "evaluation/held-out/config.json": "evaluation-config.json",
    "evaluation/held-out/summary.csv": "evaluation-summary.csv",
    "train.log": "train.log", "evaluate.log": "evaluate.log",
    "backend.log": "backend.log", "frontend.log": "frontend.log",
}


def read(path):
    return read_json(path)


def digest(path):
    return file_sha256(path)


# These are path-specific exceptions, not a recursive timestamp/duration blacklist.
# A field with the same name in a request, score, explanation or configuration is retained.
VOLATILE_JSON_FIELDS = {
    'raw/manifest.json': [('created_at',)],
    'processed/manifest.json': [('created_at',), ('inputs', 'created_at')],
    'artifacts/current/meta.json': [('created_at',), ('seconds',)],
    'evaluation/held-out/config.json': [('seconds',)],
}
CONFIG_PATHS = [('arguments', name) for name in ('interactions', 'books', 'out')]
CONFIG_PATHS += [('data', name, 'path') for name in ('interactions', 'books')]


def normalized_document(name: str, value, folder: Path):
    """Remove only documented volatile fields and normalize known run-relative paths."""
    value = json.loads(json.dumps(value, allow_nan=False))
    for path in VOLATILE_JSON_FIELDS.get(name, []):
        parent = value
        for part in path[:-1]:
            parent = parent.get(part, {}) if isinstance(parent, dict) else {}
        if isinstance(parent, dict):
            parent.pop(path[-1], None)
    if name == 'evaluation/held-out/config.json':
        for path in CONFIG_PATHS:
            parent = value
            for part in path[:-1]:
                parent = parent.get(part, {}) if isinstance(parent, dict) else {}
            if isinstance(parent, dict):
                current = parent.get(path[-1])
                if isinstance(current, str) and Path(current).is_absolute():
                    try:
                        relative = Path(current).resolve().relative_to(folder.resolve())
                    except ValueError:
                        continue
                    parent[path[-1]] = '<run>' + ('/' + relative.as_posix() if relative.parts else '')
    return value


def valid_api_examples(value) -> bool:
    if not isinstance(value, dict) or value.get('input_kind') != 'synthetic':
        return False
    examples = value.get('examples')
    if not isinstance(examples, list) or len(examples) != 2:
        return False
    modes = []
    for example in examples:
        if not isinstance(example, dict):
            return False
        request, response = example.get('request'), example.get('response')
        if not isinstance(request, dict) or not isinstance(response, dict):
            return False
        for reader in ('reader_a', 'reader_b'):
            picks = request.get(reader)
            if (not isinstance(picks, list) or len(picks) != 5 or
                    not all(isinstance(pick, str) and pick for pick in picks) or len(set(picks)) != 5):
                return False
        mode = request.get('aggregation')
        if mode not in ('least_misery', 'average') or response.get('aggregation') != mode:
            return False
        if not isinstance(response.get('model_version'), str) or not response['model_version']:
            return False
        recommendations = response.get('recommendations')
        if (request.get('k') != 5 or not isinstance(recommendations, list) or len(recommendations) != 5 or
                not all(isinstance(item, dict) and isinstance(item.get('book'), dict) and
                        isinstance(item['book'].get('book_id'), str) and item['book']['book_id']
                        for item in recommendations)):
            return False
        for item in recommendations:
            if not all(isinstance(item.get(key), (int, float)) and not isinstance(item[key], bool) and
                       math.isfinite(item[key]) for key in ('score', 'fit_a', 'fit_b')):
                return False
            reasons = item.get('reasons')
            if not isinstance(reasons, dict):
                return False
            for reader in ('reader_a', 'reader_b'):
                reason = reasons.get(reader)
                if (not isinstance(reason, dict) or not isinstance(reason.get('seed_id'), str) or
                        not reason['seed_id'] or not isinstance(reason.get('text'), str) or not reason['text']):
                    return False
        modes.append(mode)
    return sorted(modes) == ['average', 'least_misery']


def compare(a: Path, b: Path) -> dict:
    a, b = a.resolve(), b.resolve()
    left, right = read(a / "run.json"), read(b / "run.json")
    if any(run.get("input_kind") != "synthetic" or run.get("status") != "passed" for run in (left, right)):
        raise ValueError("Only two successful, explicitly synthetic runs can enter this shareable evidence package")
    problems = []

    def raw_names(folder):
        return {path.relative_to(folder).as_posix() for path in (folder / 'raw').rglob('*')
                if path.is_file() or path.is_symlink()}

    raw_a, raw_b = raw_names(a), raw_names(b)
    names = raw_a | raw_b | {'processed/books.parquet', 'processed/interactions.parquet',
                             'artifacts/current/books.json', 'artifacts/current/item_embeddings.npy',
                             'artifacts/current/coords_2d.npy', 'evaluation/held-out/summary.csv'}
    hashes, normalized = {}, {}
    for name in sorted(names | set(VOLATILE_JSON_FIELDS)):
        entry = {}
        for label, folder in (('a', a), ('b', b)):
            try:
                path = regular_within(folder, name)
                if name in VOLATILE_JSON_FIELDS:
                    value = read(path)
                    if not isinstance(value, dict) or not value:
                        raise ValueError('Expected a nonempty metadata object')
                    entry[label + '_sha256'] = canonical_sha256(normalized_document(name, value, folder))
                else:
                    entry[label + '_sha256'] = digest(path)
            except (OSError, ValueError) as error:
                entry[label + '_sha256'] = None
                problems.append(f'{label}: {name}: {type(error).__name__}')
        entry['equal'] = entry['a_sha256'] is not None and entry['a_sha256'] == entry['b_sha256']
        (normalized if name in VOLATILE_JSON_FIELDS else hashes)[name] = entry

    examples = []
    for label, folder in (('a', a), ('b', b)):
        try:
            examples.append(read(regular_within(folder, 'api-examples.json')))
        except (OSError, ValueError):
            examples.append(None)
            problems.append(f'{label}: missing or invalid api-examples.json')
    valid_examples = all(valid_api_examples(value) for value in examples)
    rank = lambda value: [{'aggregation': e['request']['aggregation'],
                           'ids': [r['book']['book_id'] for r in e['response']['recommendations']]}
                          for e in value['examples']]

    def recorded_hashes_match(run, folder, key, directory, filenames):
        declared = run.get(key)
        if not isinstance(declared, dict) or set(declared) != set(filenames):
            return False
        try:
            return all(declared[name] == digest(regular_within(folder, directory + '/' + name)) for name in filenames)
        except (OSError, ValueError):
            return False

    checks = {"same_source_commit_and_files": bool(left.get('source_commit')) and bool(left.get('source_sha256')) and
               left.get("source_commit") == right.get("source_commit") and left.get("source_sha256") == right.get("source_sha256"),
              "clean_sources": not left["source_dirty"] and not right["source_dirty"],
              "same_data_version": bool(left.get('data_version')) and left.get("data_version") == right.get("data_version"),
              "same_model_version": bool(left.get('model_version')) and left.get('model_version') == right.get('model_version'),
              "same_parameters": bool(left.get('parameters')) and left.get('parameters') == right.get('parameters'),
              "same_frontend_bytes": bool(left.get('frontend_sha256')) and left.get('frontend_sha256') == right.get('frontend_sha256'),
              "same_raw_file_set": bool(raw_a) and any(name.endswith('.gz') for name in raw_a) and raw_a == raw_b,
              "nonempty_full_shelf_api_examples": valid_examples,
              "api_examples_match_recorded_model": valid_examples and all(
                  example['response']['model_version'] == run.get('model_version')
                  for run, value in ((left, examples[0]), (right, examples[1])) for example in value['examples']),
              "same_full_shelf_api_rankings": valid_examples and rank(examples[0]) == rank(examples[1]),
              "same_full_shelf_api_requests_and_responses": valid_examples and examples[0] == examples[1],
              "all_recorded_export_hashes_match_bytes": all(recorded_hashes_match(run, folder, 'export_sha256',
                   'artifacts/current', EXPORTS) for run, folder in ((left, a), (right, b))),
              "all_recorded_processed_hashes_match_bytes": all(recorded_hashes_match(run, folder, 'processed_sha256',
                   'processed', ('books.parquet', 'interactions.parquet', 'manifest.json')) for run, folder in ((left, a), (right, b))),
              "all_compared_content_hashes_match": bool(hashes) and all(v["equal"] for v in hashes.values()),
              "all_normalized_metadata_match": all(value['equal'] for value in normalized.values())}
    return {"checked_at": datetime.now(timezone.utc).isoformat(), "scope": "two local synthetic runs on this environment",
            "passed": all(checks.values()), "source_commit": left["source_commit"],
            "data_version": left["data_version"], "checks": checks, "content_hashes": hashes,
            "normalized_metadata_sha256": normalized, "problems": problems,
            "cloud_training_evidence": False, "production_quality_evidence": False,
            "excluded_from_exact_comparison": {name: ['.'.join(path) for path in paths]
                                                for name, paths in VOLATILE_JSON_FIELDS.items()},
            "path_normalization": "Only known evaluation config input/output paths inside each run become <run>.",
            "runtime_record_scope": "Run parameters, model/data/source identities, frontend hash and recorded artifact hashes are checked. "
                                    "Lifecycle timestamps, stage timings, preview port and services_stopped observation are not output comparisons.",
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
