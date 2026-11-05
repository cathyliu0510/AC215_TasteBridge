#!/usr/bin/env python3
"""Check an existing export against a reviewed lock and distinguish historical images.

Reads local files only. Does not stage artifacts, train, start services or call cloud APIs.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FILES = ('books.json', 'item_embeddings.npy', 'coords_2d.npy', 'meta.json')
spec = importlib.util.spec_from_file_location('artifact_format', ROOT / 'deploy/cloud-run/prepare-artifacts.py')
format_checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(format_checks)


def fingerprint(path):
    data = path.read_bytes()
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'md5': hashlib.md5(data).hexdigest()}


def compare_container(record, hashes, source_trees):
    previous = record.get('artifact_sha256', {})
    different = [name for name in FILES if previous.get(name) != hashes[name]]
    previous_trees = record.get('source_trees', {})
    parts = ('src/backend', 'frontend/prototype')
    differing_sources = [name for name in parts
                         if not source_trees.get(name) or previous_trees.get(name) != source_trees[name]]
    return {'same_artifact_bytes': not different, 'different_files': different,
            'same_app_sources': not differing_sources, 'different_source_trees': differing_sources,
            'identity_compatible_with_current_export_and_app': not different and not differing_sources,
            'note': 'Matching bytes and source trees only; this does not independently verify image execution or deployment.'}


def audit(directory, lock, dvc_index=None, container_record=None, source_trees=None):
    directory = Path(directory).resolve(strict=True)
    if lock.get('schema_version') != 1 or set(lock.get('files', {})) != set(FILES):
        raise ValueError('Lock must name exactly the four export files')
    actual = {}
    for name in FILES:
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Missing regular artifact file: {name}')
        expected = lock['files'][name]
        if not re.fullmatch('[0-9a-f]{64}', str(expected.get('sha256', ''))):
            raise ValueError(f'Missing SHA256 lock: {name}')
        actual[name] = fingerprint(path)
        if actual[name] != expected:
            raise ValueError(f'Artifact bytes differ from reviewed lock: {name}')
    if dvc_index is not None:
        data = Path(dvc_index).read_bytes()
        if hashlib.md5(data).hexdigest() != lock.get('source_dvc_directory_md5'):
            raise ValueError('DVC directory index differs from the pinned lock')
        entries = [row for row in json.loads(data) if row['relpath'].startswith('current/')]
        expected_md5 = {f'current/{name}': values['md5'] for name, values in actual.items()}
        if len(entries) != 4 or {row['relpath']: row['md5'] for row in entries} != expected_md5:
            raise ValueError('DVC current entries do not match the four locked files')
    count = format_checks.check_books(directory / 'books.json')
    meta = format_checks.read_json(directory / 'meta.json')
    for key in ('model_version', 'data_version'):
        if not isinstance(meta.get(key), str) or meta[key] != lock.get(key):
            raise ValueError(f'Metadata differs from reviewed {key}')
    if meta.get('counts', {}).get('books') != count or count != lock.get('num_books'):
        raise ValueError('Catalogue row count differs from metadata or lock')
    factors = meta.get('hyperparameters', {}).get('factors')
    if type(factors) is not int or factors <= 0:
        raise ValueError('Export must record a positive integer factor count')
    matrices = {name: format_checks.check_matrix(directory / name, count, columns=columns)
                for name, columns in [('item_embeddings.npy', factors), ('coords_2d.npy', 2)]}
    if actual != {name: fingerprint(directory / name) for name in FILES}:
        raise ValueError('Input export changed during audit')
    hashes = {name: values['sha256'] for name, values in actual.items()}
    result = {'schema_version': 1, 'checked_at': datetime.now(timezone.utc).isoformat(),
              'status': 'locked_export_verified', 'model_version': meta['model_version'],
              'data_version': meta['data_version'], 'num_books': count,
              'hyperparameters': meta['hyperparameters'], 'recorded_export_source': meta.get('code_version'),
              'files': actual, 'matrices': matrices, 'dvc_index_verified': dvc_index is not None,
              'export_fingerprint_sha256': hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(),
              'training_executed': False, 'services_started': False, 'cloud_execution': False,
              'raw_input_reproduction_verified': False, 'cloud_deployment_verified': False}
    result['deploy_model_hash'] = result['export_fingerprint_sha256'][:12]
    if container_record is not None:
        result['historical_container_comparison'] = compare_container(container_record, hashes, source_trees or {})
        result['historical_container_comparison']['same_model_version_label'] = container_record.get('model', {}).get('model_version') == meta['model_version']
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-dir', type=Path, required=True)
    parser.add_argument('--lock', type=Path, required=True)
    parser.add_argument('--dvc-index', type=Path)
    parser.add_argument('--container-verification', type=Path)
    parser.add_argument('--out', type=Path, required=True, help='New report; existing reports are never overwritten')
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Use a new report path; preserve prior evidence')
    try:
        source_trees = {part: subprocess.check_output(['git', 'rev-parse', f'HEAD:{part}'], cwd=ROOT, text=True).strip()
                        for part in ('src/backend', 'frontend/prototype')}
        record = json.loads(args.container_verification.read_text()) if args.container_verification else None
        result = audit(args.artifact_dir, json.loads(args.lock.read_text()), args.dvc_index, record, source_trees)
        result['current_app_source_trees'] = source_trees
        source = result.get('recorded_export_source')
        if source and re.fullmatch('[0-9a-f]{40}', source):
            recorded = subprocess.run(['git', 'rev-parse', f'{source}:src/evaluation/evaluation'], cwd=ROOT,
                                      text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            current = subprocess.check_output(['git', 'rev-parse', 'HEAD:src/evaluation/evaluation'], cwd=ROOT, text=True).strip()
            result['evaluation_source_comparison'] = {'recorded_tree_available': recorded.returncode == 0,
                'same_committed_tree': recorded.returncode == 0 and recorded.stdout.strip() == current,
                'recorded_tree': recorded.stdout.strip() if recorded.returncode == 0 else None, 'current_tree': current,
                'limits': 'Committed source identity only; no fresh model fit or environment reproducibility proof.'}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open('x') as output:
            json.dump(result, output, indent=2)
            output.write('\n')
        print(json.dumps({'status': result['status'], 'deploy_model_hash': result['deploy_model_hash'],
                          'historical_container_comparison': result.get('historical_container_comparison')}))
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f'Identity audit failed: {error}\n')


if __name__ == '__main__':
    main()
