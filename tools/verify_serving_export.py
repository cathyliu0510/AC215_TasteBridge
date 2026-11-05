#!/usr/bin/env python3
"""Verify an existing model export through the current API and UI; never retrain or deploy."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.verify_local_integration import available_port, reserve_output, sha256, stop_owned, wait_for_service, write_json

EXPORTS = ('books.json', 'item_embeddings.npy', 'coords_2d.npy', 'meta.json')


def input_kind(meta):
    identity = (str(meta.get('model_version', '')) + ' ' + str(meta.get('data_version', ''))).lower()
    if 'synthetic' in identity:
        return 'trained_synthetic'
    if any(marker in identity for marker in ('sample', 'toy')):
        return 'fixed_fixture'
    return 'operator_supplied_unverified_provenance'


def inspect_export(directory):
    directory = directory.resolve(strict=True)
    for name in EXPORTS:
        if (directory / name).is_symlink() or not (directory / name).is_file():
            raise ValueError(f'Missing regular model export: {name}')
    meta = json.loads((directory / 'meta.json').read_text())
    books = json.loads((directory / 'books.json').read_text())
    if not isinstance(meta.get('model_version'), str) or not meta['model_version']:
        raise ValueError('The model export needs an explicit model_version')
    if not isinstance(books, list) or len(books) < 15:
        raise ValueError('At least 15 exported books are needed for two five-book shelves and a shortlist')
    return directory, meta, books


def verify(args):
    artifact_dir, meta, books = inspect_export(args.artifact_dir)
    # Preserve the venv invocation path; resolving its interpreter symlink loses the environment.
    python = args.backend_python.expanduser().absolute()
    if not python.is_file():
        raise ValueError('Missing backend environment; run uv sync --frozen --project src/backend')
    node = shutil.which('node')
    if not node:
        raise ValueError('Node 20+ is required for the actual frontend relay')
    out = reserve_output(args.out)
    record = dict(status='running', started_at=datetime.now(timezone.utc).isoformat(),
                  input_kind=input_kind(meta), model_version=meta['model_version'], data_version=meta.get('data_version'),
                  books=len(books), training_executed=False, cloud_execution=False, feedback_sent=False,
                  artifact_sha256={name: sha256(artifact_dir / name) for name in EXPORTS},
                  source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  source_dirty=bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip()))
    children, handles = [], []
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1')
    write_json(out / 'run.json', record)
    try:
        with (out / 'frontend-build.log').open('w') as log:
            for script in ('build-prototype.mjs', 'verify-release.mjs'):
                subprocess.run([node, 'scripts/' + script], cwd=ROOT / 'frontend/prototype', env=env,
                               stdout=log, stderr=subprocess.STDOUT, check=True)
        record['frontend_release'] = json.loads((ROOT / 'frontend/prototype/release.json').read_text())['release']
        files = [*sorted((ROOT / 'src/backend/app').glob('*.py')), ROOT / 'frontend/prototype/dist/a/index.html',
                 Path(__file__), ROOT / 'deploy/cloud-run/smoke.py']
        record['source_sha256'] = {str(path.relative_to(ROOT)): sha256(path) for path in files}
        api_port, ui_port = available_port(), available_port()
        while api_port == ui_port:
            ui_port = available_port()
        api_base, ui_base = f'http://127.0.0.1:{api_port}', f'http://127.0.0.1:{ui_port}'
        services = [
            ('backend', [str(python), '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(api_port)],
             ROOT / 'src/backend', {'ARTIFACT_DIR': str(artifact_dir), 'FEEDBACK_PATH': str(out / 'feedback.jsonl')}),
            ('frontend', [node, 'scripts/serve.mjs'], ROOT / 'frontend/prototype',
             {'PORT': str(ui_port), 'TASTEBRIDGE_HOST': '127.0.0.1', 'API_BASE_URL': api_base}),
        ]
        for name, command, cwd, overrides in services:
            handle = (out / (name + '.log')).open('w')
            handles.append(handle)
            children.append(subprocess.Popen(command, cwd=cwd, env={**env, **overrides}, stdout=handle, stderr=subprocess.STDOUT))
        wait_for_service(children[0], api_base + '/health')
        wait_for_service(children[1], ui_base + '/healthz')
        spec = importlib.util.spec_from_file_location('serving_contract', ROOT / 'deploy/cloud-run/smoke.py')
        smoke = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(smoke)
        proof = smoke.check(ui_base, {'num_books': len(books), 'model_version': meta['model_version'], 'tag': out.name},
                            feedback=False, seed_ids=[books[0]['book_id'], books[5]['book_id']])
        write_json(out / 'api-check.json', proof)
        query = {'api': '1', 'a': json.dumps([book['book_id'] for book in books[:5]]),
                 'b': json.dumps([book['book_id'] for book in books[5:10]]), 'mode': 'least-misery'}
        record.update(status='verified', ui_url=ui_base + '/a/?' + urlencode(query),
                      checks=proof['checks'], completed_at=datetime.now(timezone.utc).isoformat())
        if record['artifact_sha256'] != {name: sha256(artifact_dir / name) for name in EXPORTS}:
            raise RuntimeError('The input export changed during verification')
        write_json(out / 'run.json', record)
        print(json.dumps({'status': record['status'], 'input_kind': record['input_kind'], 'model': meta['model_version'],
                          'frontend_release': record['frontend_release'], 'ui_url': record['ui_url'],
                          'training_executed': False, 'cloud_execution': False}), flush=True)
        if args.serve:
            try:
                while all(child.poll() is None for child in children):
                    time.sleep(1)
                raise RuntimeError('An owned service exited while the preview was open')
            except KeyboardInterrupt:
                pass
    except BaseException as error:
        record.update(status='failed', error=type(error).__name__ + ': ' + str(error))
        write_json(out / 'run.json', record)
        raise
    finally:
        for child in reversed(children):
            stop_owned(child)
        for handle in handles:
            handle.close()
    return out


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-dir', type=Path, required=True, help='Existing export; read only, no download')
    parser.add_argument('--backend-python', type=Path,
                        default=ROOT / 'src/backend/.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python'))
    parser.add_argument('--out', type=Path, required=True, help='New evidence directory; never overwrite prior runs')
    parser.add_argument('--serve', action='store_true', help='Keep only this run’s loopback services open until Ctrl-C')
    return parser.parse_args(argv)


if __name__ == '__main__':
    verify(parse_args())
