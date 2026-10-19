#!/usr/bin/env python3
"""Build locally; publish explicitly after project access has been granted."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

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


def run(*args, capture=False, env=None):
    return subprocess.run(args, cwd=ROOT, check=True, text=True, env=env,
                          stdout=subprocess.PIPE if capture else None).stdout


def inspect(image, expression):
    return run('docker', 'image', 'inspect', image, '--format', expression, capture=True).strip()


def source_trees():
    return {part: run('git', 'rev-parse', f'HEAD:{part}', capture=True).strip()
            for part in ('src/backend', 'frontend/prototype')}


def build(source):
    # A reproducible release must point to committed app code.
    dirty = run('git', 'status', '--porcelain', '--', 'src/backend', 'frontend/prototype', capture=True)
    if dirty.strip():
        raise SystemExit('Commit app changes before building a release.')
    (STATE / 'local-smoke.json').unlink(missing_ok=True)
    run(sys.executable, str(HERE / 'prepare-artifacts.py'), str(source), str(HERE / '.artifacts'))
    hashes = {name: hashlib.sha256((HERE / '.artifacts' / name).read_bytes()).hexdigest() for name in FILES}
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
                   artifact_sha256=hashes, model_version=meta['model_version'], num_books=len(books))
    STATE.mkdir(exist_ok=True)
    (STATE / 'release.json').write_text(json.dumps(release, indent=2) + '\n')
    print(f'Built {tag}. No cloud resources changed. Run smoke.py --local before publishing.')


def service_spec(images):
    def probe(path, port):
        return dict(httpGet=dict(path=path, port=port), periodSeconds=5, timeoutSeconds=3, failureThreshold=24)
    def env(**values):
        return [dict(name=k, value=v) for k, v in values.items()]
    return {
        'apiVersion': 'serving.knative.dev/v1', 'kind': 'Service',
        'metadata': {'name': SERVICE, 'labels': {'managed-by': OWNER},
                     'annotations': {'run.googleapis.com/ingress': 'all', 'run.googleapis.com/maxScale': '1'}},
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
                          'env': env(HOST='0.0.0.0', API_BASE_URL='http://127.0.0.1:9000'),
                          'resources': {'limits': {'cpu': '1000m', 'memory': '256Mi'}},
                          'startupProbe': probe('/healthz', 8080)},
                         {'name': 'backend', 'image': images['backend'],
                          'env': env(PORT='9000', ARTIFACT_DIR='/artifacts/current', FEEDBACK_PATH='/dev/stdout'),
                          'resources': {'limits': {'cpu': '1000m', 'memory': '512Mi'}},
                          'startupProbe': probe('/health', 9000)}]}},
            'traffic': [{'latestRevision': True, 'percent': 100}]}}


def publish():
    release = json.loads((STATE / 'release.json').read_text())
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
    spec.write_text(json.dumps(service_spec(remote_images), indent=2) + '\n')
    run(gcloud, 'run', 'services', 'replace', str(spec), *flags, '--dry-run')
    run(gcloud, 'run', 'services', 'replace', str(spec), *flags)
    run(gcloud, 'run', 'services', 'add-iam-policy-binding', SERVICE, *flags, '--member=allUsers', '--role=roles/run.invoker')
    live = json.loads(run(gcloud, 'run', 'services', 'describe', SERVICE, *flags, '--format=json', capture=True))
    (STATE / 'live-service.json').write_text(json.dumps(live, indent=2) + '\n')
    url = live['status']['url']
    run(sys.executable, str(HERE / 'smoke.py'), '--url', url)
    (STATE / 'url.txt').write_text(url + '\n')
    print(f'Published and API-checked: {url}')
    print('Finish browser checks and confirm the feedback event in Cloud Logging before handoff.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('build').add_argument('artifact_dir', type=Path)
    commands.add_parser('publish')
    args = parser.parse_args()
    if args.command == 'build':
        build(args.artifact_dir.resolve())
    else:
        publish()
