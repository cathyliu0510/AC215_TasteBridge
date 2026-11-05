#!/usr/bin/env python3
"""Build locally; publish explicitly after project access has been granted."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
STATE = HERE / '.state'
PROJECT = 'tastebridge-511403'
REGION = 'us-central1'
SERVICE = 'tastebridge-staging'
REGISTRY = f'{REGION}-docker.pkg.dev'
REPOSITORY = f'{REGISTRY}/{PROJECT}/tastebridge-app'
IDENTITY = f'tastebridge-runtime@{PROJECT}.iam.gserviceaccount.com'
OWNER = 'tastebridge-frontend'
FILES = ('books.json', 'item_embeddings.npy', 'coords_2d.npy', 'meta.json')


def run(*args, capture=False, env=None, input=None):
    return subprocess.run(args, cwd=ROOT, check=True, text=True, env=env,
                          input=input,
                          stdout=subprocess.PIPE if capture else None).stdout


def inspect(image, expression):
    return run('docker', 'image', 'inspect', image, '--format', expression, capture=True).strip()


def source_trees():
    return {part: run('git', 'rev-parse', f'HEAD:{part}', capture=True).strip()
            for part in ('src/backend', 'frontend/prototype')}


def read_artifact_lock(path):
    data = path.read_bytes()
    lock = json.loads(data)
    if lock.get('schema_version') != 1 or set(lock.get('files', {})) != set(FILES):
        raise ValueError('Artifact lock must name exactly the four export files.')
    hashes = {name: lock['files'][name].get('sha256') for name in FILES}
    if any(not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value) for value in hashes.values()):
        raise ValueError('Every artifact lock entry needs a SHA256 hash.')
    return hashes, hashlib.sha256(data).hexdigest()


def build(source, artifact_lock=None):
    expected, lock_sha256 = read_artifact_lock(artifact_lock) if artifact_lock is not None else (None, None)
    # A reproducible release must point to committed app code.
    dirty = run('git', 'status', '--porcelain', '--', 'src/backend', 'frontend/prototype', capture=True)
    if dirty.strip():
        raise SystemExit('Commit app changes before building a release.')
    (STATE / 'local-smoke.json').unlink(missing_ok=True)
    run(sys.executable, str(HERE / 'prepare-artifacts.py'), str(source), str(HERE / '.artifacts'))
    hashes = {name: hashlib.sha256((HERE / '.artifacts' / name).read_bytes()).hexdigest() for name in FILES}
    if expected is not None and hashes != expected:
        raise SystemExit('Staged model differs from the reviewed artifact lock. No images were built; verify the exact export.')
    model_hash = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()[:12]
    commit = run('git', 'rev-parse', 'HEAD', capture=True).strip()
    tag = f'{commit[:12]}-{model_hash}'
    images = {part: f'tastebridge-cloud-{part}:{tag}' for part in ('frontend', 'backend-base', 'backend')}
    common = ('docker', 'buildx', 'build', '--platform', 'linux/amd64', '--load')
    run(*common, '-t', images['backend-base'], 'src/backend')
    run(*common, '-t', images['frontend'], 'frontend/prototype')
    run(*common, '--build-arg', f'BACKEND_IMAGE={images["backend-base"]}', '-f', str(HERE / 'Dockerfile.backend'), '-t', images['backend'], str(HERE))
    for image in images.values():
        if inspect(image, '{{.Os}}/{{.Architecture}}') != 'linux/amd64':
            raise SystemExit(f'Unexpected image architecture: {image}')
    meta = json.loads((HERE / '.artifacts/meta.json').read_text())
    books = json.loads((HERE / '.artifacts/books.json').read_text())
    release = dict(project=PROJECT, region=REGION, service=SERVICE, commit=commit,
                   source_trees=source_trees(), tag=tag, images=images,
                   image_ids={name: inspect(image, '{{.Id}}') for name, image in images.items()},
                   artifact_sha256=hashes, model_version=meta['model_version'],
                   data_version=meta.get('data_version'), num_books=len(books))
    if lock_sha256 is not None:
        release['reviewed_artifact_lock_sha256'] = lock_sha256
    STATE.mkdir(exist_ok=True)
    (STATE / 'release.json').write_text(json.dumps(release, indent=2) + '\n')
    print(f'Built {tag}. No cloud resources changed. Run smoke.py --local before publishing.')


def service_spec(images, current=None):
    def probe(path, port):
        return dict(httpGet=dict(path=path, port=port), periodSeconds=5, timeoutSeconds=3, failureThreshold=24)
    def env(**values):
        return [dict(name=k, value=v) for k, v in values.items()]
    access_annotations = {key: value for key, value in (current or {}).get('metadata', {}).get('annotations', {}).items()
                          if key in ('run.googleapis.com/ingress', 'run.googleapis.com/invoker-iam-disabled',
                                     'run.googleapis.com/default-url-disabled')}
    return {
        'apiVersion': 'serving.knative.dev/v1', 'kind': 'Service',
        'metadata': {'name': SERVICE, 'labels': {'managed-by': OWNER},
                     'annotations': {'run.googleapis.com/ingress': 'all', 'run.googleapis.com/maxScale': '1', **access_annotations}},
        'spec': {'template': {
            'metadata': {'annotations': {
                'run.googleapis.com/execution-environment': 'gen2',
                'run.googleapis.com/cpu-throttling': 'true',
                'autoscaling.knative.dev/minScale': '0',
                'autoscaling.knative.dev/maxScale': '1',
                'run.googleapis.com/container-dependencies': '{"frontend":["backend"]}'}},
            'spec': {'serviceAccountName': IDENTITY, 'containerConcurrency': 8, 'timeoutSeconds': 60,
                     'containers': [
                         {'name': 'frontend', 'image': images['frontend'],
                          'ports': [{'containerPort': 8080}],
                          'env': env(TASTEBRIDGE_HOST='0.0.0.0', API_BASE_URL='http://127.0.0.1:9000'),
                          'resources': {'limits': {'cpu': '1000m', 'memory': '256Mi'}},
                          'startupProbe': probe('/healthz', 8080)},
                         {'name': 'backend', 'image': images['backend'],
                          'env': env(PORT='9000', ARTIFACT_DIR='/artifacts/current', FEEDBACK_PATH='/dev/stdout'),
                          'resources': {'limits': {'cpu': '1000m', 'memory': '512Mi'}},
                          'startupProbe': probe('/health', 9000)}]}},
            'traffic': [{'latestRevision': True, 'percent': 100}]}}


def publication_model_kind(release, allow_demo_model=False):
    identity = str(release.get('model_version', ''))
    if not identity:
        raise SystemExit('Missing model identity; rebuild the release before publication.')
    description = (identity + ' ' + str(release.get('data_version', ''))).lower()
    demo = any(marker in description for marker in ('synthetic', 'sample', 'toy'))
    if demo and not allow_demo_model:
        raise SystemExit('Demo model detected. Use the approved export, or explicitly label a demo with --allow-demo-model.')
    return 'demo_model' if demo else 'operator_supplied_export_not_independently_verified'


def publish(authenticated=False, allow_demo_model=False):
    release = json.loads((STATE / 'release.json').read_text())
    model_kind = publication_model_kind(release, allow_demo_model)
    proof = json.loads((STATE / 'local-smoke.json').read_text())
    if (proof.get('tag') != release['tag'] or proof.get('passed') is not True
            or proof.get('image_ids') != release['image_ids']):
        raise SystemExit('Run smoke.py --local for this release first.')
    dirty = run('git', 'status', '--porcelain', '--', 'src/backend', 'frontend/prototype', capture=True)
    if release['source_trees'] != source_trees() or dirty.strip():
        raise SystemExit('App source changed since build; rebuild and retest.')
    for name, image in release['images'].items():
        if inspect(image, '{{.Id}}') != release['image_ids'][name]:
            raise SystemExit('A local image changed since verification; rebuild and retest.')
    gcloud = shutil.which('gcloud')
    if not gcloud:
        raise SystemExit('Add the installed Google Cloud SDK bin directory to PATH.')
    flags = ('--project', PROJECT, '--region', REGION)
    # Fail before uploading anything if Cloud Run or the private registry is inaccessible.
    services = json.loads(run(gcloud, 'run', 'services', 'list', *flags, '--format=json', capture=True))
    current = next((s for s in services if s['metadata']['name'] == SERVICE), None)
    if current and current['metadata'].get('labels', {}).get('managed-by') != OWNER:
        raise SystemExit(f'{SERVICE} already exists with another owner label. Inspect it before proceeding.')
    run(gcloud, 'artifacts', 'repositories', 'describe', 'tastebridge-app', '--project', PROJECT, '--location', REGION, '--format=value(name)')
    if current:
        (STATE / 'previous-service.json').write_text(json.dumps(current, indent=2) + '\n')
    # The helper retrieves tokens in memory. Temporary Docker config contains no token.
    endpoint = os.environ.get('DOCKER_HOST') or run('docker', 'context', 'inspect', '--format', '{{.Endpoints.docker.Host}}', capture=True).strip()
    remote_images = {}
    with tempfile.TemporaryDirectory(prefix='tastebridge-docker-config-') as tmp:
        Path(tmp, 'config.json').write_text(json.dumps({'credHelpers': {REGISTRY: 'gcloud'}}))
        push_env = dict(os.environ, DOCKER_CONFIG=tmp, DOCKER_HOST=endpoint)
        for name in ('frontend', 'backend'):
            remote = f'{REPOSITORY}/{name}:{release["tag"]}'
            run('docker', 'tag', release['images'][name], remote)
            run('docker', 'push', remote, env=push_env)
            digests = json.loads(inspect(remote, '{{json .RepoDigests}}'))
            remote_images[name] = next(d for d in digests if d.startswith(f'{REPOSITORY}/{name}@'))
    spec = STATE / 'service.json'  # JSON is also a valid YAML service document.
    spec.write_text(json.dumps(service_spec(remote_images, current), indent=2) + '\n')
    run(gcloud, 'run', 'services', 'replace', str(spec), *flags, '--dry-run')
    status = dict(status='update_outcome_uncertain', access_policy='preserved', model_kind=model_kind,
                  project=PROJECT, region=REGION, service=SERVICE, tag=release['tag'])
    (STATE / 'deployment.json').write_text(json.dumps(status, indent=2) + '\n')
    try:
        run(gcloud, 'run', 'services', 'replace', str(spec), *flags)
    except subprocess.CalledProcessError:
        raise SystemExit('Service update command failed; its outcome is uncertain. Inspect the service before retrying; IAM was not changed.') from None
    status['status'] = 'deployed_unverified'
    (STATE / 'deployment.json').write_text(json.dumps(status, indent=2) + '\n')
    (STATE / 'url.txt').unlink(missing_ok=True)
    try:
        live = json.loads(run(gcloud, 'run', 'services', 'describe', SERVICE, *flags, '--format=json', capture=True))
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        raise SystemExit('Service update succeeded, but its description could not be verified. Inspect .state/deployment.json; IAM was not changed.') from None
    (STATE / 'live-service.json').write_text(json.dumps(live, indent=2) + '\n')
    url = live.get('status', {}).get('url')
    status.update(url=url, revision=live.get('status', {}).get('latestReadyRevisionName'))
    (STATE / 'deployment.json').write_text(json.dumps(status, indent=2) + '\n')
    parsed = urllib.parse.urlsplit(url if isinstance(url, str) else '')
    if (parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith('.run.app')
            or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
        raise SystemExit('Service updated, but its returned Cloud Run origin is unexpected. Verify manually; IAM is unchanged.')
    (STATE / 'url.txt').write_text(url + '\n')
    command = [sys.executable, str(HERE / 'smoke.py'), '--url', url]
    token = None
    try:
        if authenticated:
            token = run(gcloud, 'auth', 'print-identity-token', capture=True).strip()
            if not token:
                raise SystemExit('Service updated, but the existing identity returned no token. IAM is unchanged; verify access separately.')
            command.append('--identity-token-stdin')
        run(*command, input=token + '\n' if token else None)
    except subprocess.CalledProcessError:
        raise SystemExit('Service updated, but verification failed. Inspect .state/deployment.json and existing invocation access; IAM was not changed.') from None
    finally:
        token = None
    status['status'] = 'deployed_and_api_verified'
    (STATE / 'deployment.json').write_text(json.dumps(status, indent=2) + '\n')
    print(f'Published and API-checked: {url}')
    print('Existing IAM was preserved. Finish browser checks and confirm logs before handoff.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    build_command = commands.add_parser('build')
    build_command.add_argument('artifact_dir', type=Path)
    build_command.add_argument('--artifact-lock', type=Path, help='Require exact reviewed model bytes before any Docker build')
    publication = commands.add_parser('publish')
    publication.add_argument('--authenticated', action='store_true', help='Verify using the already authorized gcloud identity; no IAM changes')
    publication.add_argument('--allow-demo-model', action='store_true', help='Explicitly permit a clearly labeled synthetic/sample model; not real-data evidence')
    args = parser.parse_args()
    try:
        if args.command == 'build':
            build(args.artifact_dir.resolve(), artifact_lock=args.artifact_lock)
        else:
            publish(authenticated=args.authenticated, allow_demo_model=args.allow_demo_model)
    except subprocess.CalledProcessError as error:
        raise SystemExit(f'Stopped: {error.cmd[0]} returned {error.returncode}. Resolve the error above before retrying.') from None
