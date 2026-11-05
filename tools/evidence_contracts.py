"""Content identities for local serving evidence; never include model or reader contents."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

EXPORTS = ('books.json', 'item_embeddings.npy', 'coords_2d.npy', 'meta.json')
SOURCE_SCOPE = 'tastebridge-local-serving-v1'
SOURCE_REQUIRED = (
    'src/backend/app/main.py', 'src/backend/pyproject.toml', 'src/backend/uv.lock',
    'frontend/prototype/scripts/serve.mjs', 'frontend/prototype/scripts/build-prototype.mjs',
    'frontend/prototype/scripts/verify-release.mjs', 'frontend/prototype/tools/build-standalone.mjs',
    'frontend/prototype/pages/project.html', 'frontend/prototype/release.json',
    'frontend/prototype/dist/index.html', 'frontend/prototype/dist/a/index.html',
    'frontend/prototype/dist/b/index.html', 'frontend/prototype/dist/project/index.html',
    'tools/verify_serving_export.py', 'tools/verify_local_integration.py',
    'tools/evidence_contracts.py', 'tools/bind_serving_evidence.py', 'deploy/cloud-run/smoke.py',
)
SOURCE_TREES = {
    'src/backend/app': '*.py',
    'frontend/prototype/src': '*',
    'frontend/prototype/scripts': '*.mjs',
    'frontend/prototype/pages': '*.html',
    'frontend/prototype/dist': '*.html',
}
FRONTEND_DEPENDENCIES = ('package.json', 'package-lock.json', 'npm-shrinkwrap.json', 'pnpm-lock.yaml', 'yarn.lock')


def canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def canonical_sha256(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def read_json(path: Path):
    def reject(value):
        raise ValueError(f'Non-finite JSON number: {value}')
    return json.loads(path.read_text(encoding='utf-8'), parse_constant=reject)


def regular_within(root: Path, path: Path) -> Path:
    """Reject traversal and symlinks before reading a bounded evidence/source file."""
    root = root.resolve(strict=True)
    path = Path(path)
    if not path.is_absolute():
        path = root / path
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise ValueError('File must be inside its declared root') from error
    if not relative.parts or '..' in relative.parts:
        raise ValueError('File must be inside its declared root without traversal')
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f'Symlinks are not evidence inputs: {relative.as_posix()}')
    if not current.is_file():
        raise ValueError(f'Missing regular file: {relative.as_posix()}')
    return current


def capture_serving_sources(root: Path) -> dict:
    root = root.resolve(strict=True)
    files = {regular_within(root, name) for name in SOURCE_REQUIRED}
    for name, pattern in SOURCE_TREES.items():
        directory = root / name
        # Files below symlinked directories must not escape the declared source tree.
        for path in directory.rglob('*'):
            if path.is_symlink():
                raise ValueError(f'Symlinks are not serving source inputs: {path.relative_to(root)}')
            if path.is_file() and path.match(pattern):
                files.add(regular_within(root, path))
    for name in FRONTEND_DEPENDENCIES:
        path = root / 'frontend/prototype' / name
        if path.exists() or path.is_symlink():
            files.add(regular_within(root, path))
    payload = {
        'schema_version': 1, 'scope': SOURCE_SCOPE, 'hash_algorithm': 'sha256',
        'files': {path.relative_to(root).as_posix(): file_sha256(path) for path in sorted(files)},
    }
    return {**payload, 'sha256': canonical_sha256(payload)}


def validate_source_manifest(manifest: dict) -> str:
    if not isinstance(manifest, dict):
        raise ValueError('Source manifest must be an object')
    payload = {key: value for key, value in manifest.items() if key != 'sha256'}
    if (set(payload) != {'schema_version', 'scope', 'hash_algorithm', 'files'} or
            payload.get('schema_version') != 1 or payload.get('scope') != SOURCE_SCOPE or
            payload.get('hash_algorithm') != 'sha256'):
        raise ValueError('Unrecognized source manifest contract')
    hashes = payload.get('files')
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError('Source manifest has no file hashes')
    if not set(SOURCE_REQUIRED).issubset(hashes):
        raise ValueError('Source manifest omits required serving inputs')
    for name, value in hashes.items():
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or not path.parts or not valid_hash(value):
            raise ValueError('Source manifest has an invalid path or SHA256')
    digest = canonical_sha256(payload)
    if manifest.get('sha256') != digest:
        raise ValueError('Source manifest digest does not match its content')
    return digest


def valid_hash(value) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def bind_serving_evidence(run_path: Path, artifact_dir: Path, evidence=(), *, source_root: Path) -> dict:
    """Bind supplied files to a recorded run, after checking source and all four model bytes.

    Screenshot and test-output hashes establish identity only. They do not establish
    capture time, test execution, or that an operator performed any browser action.
    """
    bundle = run_path.parent.resolve(strict=True)
    run_path = regular_within(bundle, run_path.name)
    source_path = regular_within(bundle, 'source-manifest.json')
    record, source = read_json(run_path), read_json(source_path)
    source_digest = validate_source_manifest(source)
    if not isinstance(record, dict) or record.get('status') not in ('verified', 'passed'):
        raise ValueError('Only a successful recorded serving run can be bound')
    if record.get('services_stopped') is not True:
        raise ValueError('Stop this run\'s services before binding final logs')
    if record.get('source_manifest_sha256') != source_digest or record.get('source_sha256') != source['files']:
        raise ValueError('Run and source manifest do not identify the same source bytes; rerun verification')
    if capture_serving_sources(source_root) != source:
        raise ValueError('Serving source changed after the recorded run; rerun verification')
    artifact_dir = artifact_dir.resolve(strict=True)
    artifacts = {name: file_sha256(regular_within(artifact_dir, name)) for name in EXPORTS}
    if record.get('artifact_sha256') != artifacts:
        raise ValueError('Recorded run does not match all four supplied model artifact hashes')
    meta = read_json(artifact_dir / 'meta.json')
    if (not isinstance(meta, dict) or not record.get('model_version') or record.get('model_version') != meta.get('model_version') or
            record.get('data_version') != meta.get('data_version')):
        raise ValueError('Recorded model/data identity does not match the model metadata')
    api_path = regular_within(bundle, 'api-check.json')
    api = read_json(api_path)
    if (not isinstance(api, dict) or not isinstance(api.get('health'), dict) or
            api.get('passed') is not True or api['health'].get('model_version') != record['model_version'] or
            api.get('health', {}).get('data_version') != record.get('data_version') or
            api.get('health', {}).get('num_books') != record.get('books')):
        raise ValueError('API record does not report a passing result for this exact model/data identity')
    selected = [('run', Path(run_path.name)), ('source', Path(source_path.name)), ('api', Path('api-check.json'))]
    selected += [('log', Path(name)) for name in ('frontend-build.log', 'backend.log', 'frontend.log')]
    selected += list(evidence)
    roles = {'run', 'source', 'api', 'log', 'screenshot', 'test', 'browser_report', 'report'}
    entries, seen = [], set()
    for role, path in selected:
        if role not in roles:
            raise ValueError(f'Unknown evidence role: {role}')
        path = regular_within(bundle, path)
        relative = path.relative_to(bundle).as_posix()
        if relative in seen:
            raise ValueError(f'Duplicate evidence path: {relative}')
        seen.add(relative)
        entries.append({'path': relative, 'role': role, 'bytes': path.stat().st_size, 'sha256': file_sha256(path)})
    payload = {
        'schema_version': 1, 'scope': 'local serving evidence identity only',
        'source_manifest_sha256': source_digest,
        'source_commit': record.get('source_commit'), 'source_dirty': record.get('source_dirty'),
        'model_version': record['model_version'], 'data_version': record.get('data_version'),
        'artifact_sha256': artifacts,
        'evidence': sorted(entries, key=lambda item: item['path']),
        'browser_actions_verified': False, 'test_execution_verified': False,
        'limits': 'Hashes bind supplied bytes to the recorded source/model identity. They do not prove when or how '
                  'a screenshot, log or test output was captured, nor independently verify its assertions. '
                  'No training, cloud execution or deployment is established by this binding.',
    }
    return {**payload, 'sha256': canonical_sha256(payload)}


def verify_evidence_binding(binding: dict, bundle: Path) -> None:
    """Reject changed/missing evidence or an altered binding without running any service."""
    if not isinstance(binding, dict):
        raise ValueError('Evidence binding must be an object')
    payload = {key: value for key, value in binding.items() if key != 'sha256'}
    if binding.get('schema_version') != 1 or binding.get('sha256') != canonical_sha256(payload):
        raise ValueError('Evidence binding digest does not match its content')
    if (not isinstance(binding.get('artifact_sha256'), dict) or set(binding['artifact_sha256']) != set(EXPORTS) or
            not all(valid_hash(value) for value in binding['artifact_sha256'].values()) or
            binding.get('browser_actions_verified') is not False or binding.get('test_execution_verified') is not False):
        raise ValueError('Evidence binding must identify all four artifacts without claiming observed browser/test actions')
    entries = binding.get('evidence')
    if not isinstance(entries, list) or not entries:
        raise ValueError('Evidence binding is empty')
    seen = set()
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) != {'path', 'role', 'bytes', 'sha256'} or
                not isinstance(entry['path'], str) or not valid_hash(entry['sha256']) or
                not isinstance(entry['bytes'], int) or entry['bytes'] < 0):
            raise ValueError('Malformed bound evidence entry')
        path = regular_within(bundle, entry['path'])
        if entry['path'] in seen or path.stat().st_size != entry['bytes'] or file_sha256(path) != entry['sha256']:
            raise ValueError(f'Bound evidence changed or repeats: {entry["path"]}')
        seen.add(entry['path'])
    roles = {entry['path']: entry['role'] for entry in entries}
    if (sum(entry['role'] == 'run' for entry in entries) != 1 or roles.get('source-manifest.json') != 'source' or
            roles.get('api-check.json') != 'api' or
            any(roles.get(name) != 'log' for name in ('frontend-build.log', 'backend.log', 'frontend.log'))):
        raise ValueError('Evidence binding omits its run, source manifest, API record or serving logs')
    source = read_json(regular_within(bundle, 'source-manifest.json'))
    run_name = next(entry['path'] for entry in entries if entry['role'] == 'run')
    run = read_json(regular_within(bundle, run_name))
    api = read_json(regular_within(bundle, 'api-check.json'))
    if (not isinstance(run, dict) or not isinstance(api, dict) or not isinstance(api.get('health'), dict) or
            validate_source_manifest(source) != binding.get('source_manifest_sha256') or
            run.get('source_manifest_sha256') != binding.get('source_manifest_sha256') or
            run.get('source_sha256') != source['files'] or run.get('artifact_sha256') != binding['artifact_sha256'] or
            run.get('model_version') != binding.get('model_version') or run.get('data_version') != binding.get('data_version') or
            run.get('source_commit') != binding.get('source_commit') or run.get('source_dirty') != binding.get('source_dirty') or
            run.get('status') not in ('verified', 'passed') or run.get('services_stopped') is not True or api.get('passed') is not True or
            api.get('health', {}).get('model_version') != binding.get('model_version') or
            api.get('health', {}).get('data_version') != binding.get('data_version') or
            api.get('health', {}).get('num_books') != run.get('books')):
        raise ValueError('Bound run, source manifest and API record have inconsistent identities')
