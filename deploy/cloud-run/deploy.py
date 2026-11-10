#!/usr/bin/env python3
"""Build locally; publish explicitly after project access has been granted."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import uuid

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
SOURCE_PATHS = ('src/backend', 'frontend/prototype', 'deploy/cloud-run')
POLICY_LIMITATION = ('Project and repository policies checked; inherited folder/organization '
                     'policies are not inspected. An administrator must confirm those separately.')


def run(*args, capture=False, env=None, input=None):
    return subprocess.run(args, cwd=ROOT, check=True, text=True, env=env,
                          input=input,
                          stdout=subprocess.PIPE if capture else None).stdout


def inspect(image, expression):
    return run('docker', 'image', 'inspect', image, '--format', expression, capture=True).strip()


def source_trees():
    return {part: run('git', 'rev-parse', f'HEAD:{part}', capture=True).strip()
            for part in SOURCE_PATHS}


def source_dirty():
    return run('git', 'status', '--porcelain', '--', *SOURCE_PATHS, capture=True).strip()


def private_registry_proof(gcloud):
    """Read current policies; never infer privacy from a successful upload permission."""
    commands = {
        'project': (gcloud, 'projects', 'get-iam-policy', PROJECT, '--format=json'),
        'repository': (gcloud, 'artifacts', 'repositories', 'get-iam-policy', 'tastebridge-app',
                       '--project', PROJECT, '--location', REGION, '--format=json'),
    }
    policies = {}
    for scope, command in commands.items():
        try:
            policy = json.loads(run(*command, capture=True))
            if (not isinstance(policy, dict) or
                    ('bindings' not in policy and not isinstance(policy.get('etag'), str)) or
                    not isinstance(policy.get('bindings', []), list)):
                raise ValueError('Invalid IAM policy')
            for binding in policy.get('bindings', []):
                if (not isinstance(binding, dict) or not isinstance(binding.get('role'), str) or
                        not isinstance(binding.get('members'), list) or
                        any(not isinstance(member, str) for member in binding['members'])):
                    raise ValueError('Invalid IAM binding')
                if {'allUsers', 'allAuthenticatedUsers'}.intersection(binding['members']):
                    raise SystemExit(f'Public {scope} IAM binding found. No further images or service updates will be sent; ask an administrator to review access.')
        except (subprocess.CalledProcessError, ValueError, TypeError):
            raise SystemExit(f'Cannot verify {scope} registry access policy. No further images or service updates will be sent; obtain policy-read access or resolve the query failure.') from None
        # Preserve proof without saving private member lists.
        policies[scope] = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
    return dict(checked_at=datetime.now(timezone.utc).isoformat(), project=PROJECT,
                repository=REPOSITORY, policy_sha256=policies,
                public_bindings_found=False, inherited_policy_verified=False,
                limitation=POLICY_LIMITATION)


def rollback_plan(current):
    """Use resolved traffic, which can differ from the latest ready revision."""
    if current is None:
        return dict(available=False, reason='No service existed before this attempt; inspect the new service manually.')
    traffic = current.get('status', {}).get('traffic')
    allocations = {}
    if not isinstance(traffic, list):
        raise SystemExit('Existing service traffic could not be resolved; inspect it before publishing.')
    for target in traffic:
        if not isinstance(target, dict):
            raise SystemExit('Existing service traffic could not be resolved; inspect it before publishing.')
        percent = target.get('percent', 0)
        if isinstance(percent, bool) or not isinstance(percent, int) or not 0 <= percent <= 100:
            raise SystemExit('Existing service traffic percentages are invalid; inspect it before publishing.')
        if percent == 0:
            continue
        revision = target.get('revisionName')
        if not isinstance(revision, str) or not re.fullmatch('[a-z][a-z0-9-]*', revision):
            raise SystemExit('Existing service traffic lacks resolved revision names; inspect it before publishing.')
        allocations[revision] = allocations.get(revision, 0) + percent
    if sum(allocations.values()) != 100:
        raise SystemExit('Existing service traffic does not total 100%; inspect it before publishing.')
    command = ['gcloud', 'run', 'services', 'update-traffic', SERVICE,
               '--project', PROJECT, '--region', REGION,
               '--to-revisions=' + ','.join(f'{revision}={percent}' for revision, percent in allocations.items())]
    return dict(available=True, allocations=allocations, command=command,
                limitation='Restores revision traffic percentages only; inspect saved service configuration and tags separately.')


def save_attempt(current, release, privacy):
    attempt_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex[:8]
    directory = STATE / 'attempts' / attempt_id
    plan = rollback_plan(current)
    directory.mkdir(parents=True)
    (directory / 'release.json').write_text(json.dumps(release, indent=2) + '\n')
    (directory / 'registry-privacy.json').write_text(json.dumps([privacy], indent=2) + '\n')
    (directory / 'rollback.json').write_text(json.dumps(plan, indent=2) + '\n')
    if current is not None:
        snapshot = json.dumps(current, indent=2) + '\n'
        (directory / 'previous-service.json').write_text(snapshot)
        # Compatibility copy; the per-attempt snapshot remains unchanged on retry.
        (STATE / 'previous-service.json').write_text(snapshot)
    instructions = ('Review the saved service before running this operator command. This script does not execute rollback.\n' +
                    shlex.join(plan['command']) + '\n' + plan['limitation'] + '\n') if plan['available'] else plan['reason'] + '\n'
    (directory / 'rollback.txt').write_text(instructions)
    print(f'Publication attempt: {directory}')
    print(instructions, end='')
    return directory


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
    # Packaging and deployment files affect the bytes and behavior being verified.
    if source_dirty():
        raise SystemExit('Commit app and deployment packaging changes before building a release. No images were built.')
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


def validated_runtime_identity(value):
    pattern = r'[a-z][a-z0-9-]{4,28}[a-z0-9]@' + re.escape(PROJECT) + r'\.iam\.gserviceaccount\.com'
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError(f'Use an existing service account email in {PROJECT}; this option creates no identity or permissions.')
    return value


def service_spec(images, current=None, runtime_identity=None):
    identity = validated_runtime_identity(IDENTITY if runtime_identity is None else runtime_identity)
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
            'spec': {'serviceAccountName': identity, 'containerConcurrency': 8, 'timeoutSeconds': 60,
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


def publish(authenticated=False, allow_demo_model=False, runtime_identity=None):
    identity = validated_runtime_identity(IDENTITY if runtime_identity is None else runtime_identity)
    release = json.loads((STATE / 'release.json').read_text())
    model_kind = publication_model_kind(release, allow_demo_model)
    proof = json.loads((STATE / 'local-smoke.json').read_text())
    if (proof.get('tag') != release['tag'] or proof.get('passed') is not True
            or proof.get('image_ids') != release['image_ids']):
        raise SystemExit('Run smoke.py --local for this release first.')
    dirty = source_dirty()
    if release['source_trees'] != source_trees() or dirty:
        raise SystemExit('App or deployment packaging source changed since build; rebuild and retest (including older releases without packaging identity).')
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
    privacy = private_registry_proof(gcloud)
    if current:
        current = json.loads(run(gcloud, 'run', 'services', 'describe', SERVICE, *flags, '--format=json', capture=True))
        if current.get('metadata', {}).get('labels', {}).get('managed-by') != OWNER:
            raise SystemExit(f'{SERVICE} owner changed; inspect it before proceeding.')
    attempt = save_attempt(current, release, privacy)
    privacy_checks = [privacy]
    # The helper retrieves tokens in memory. Temporary Docker config contains no token.
    endpoint = os.environ.get('DOCKER_HOST') or run('docker', 'context', 'inspect', '--format', '{{.Endpoints.docker.Host}}', capture=True).strip()
    remote_images = {}
    with tempfile.TemporaryDirectory(prefix='tastebridge-docker-config-') as tmp:
        Path(tmp, 'config.json').write_text(json.dumps({'credHelpers': {REGISTRY: 'gcloud'}}))
        push_env = dict(os.environ, DOCKER_CONFIG=tmp, DOCKER_HOST=endpoint)
        for name in ('frontend', 'backend'):
            if remote_images:
                privacy_checks.append(private_registry_proof(gcloud))
                (attempt / 'registry-privacy.json').write_text(json.dumps(privacy_checks, indent=2) + '\n')
            remote = f'{REPOSITORY}/{name}:{release["tag"]}'
            run('docker', 'tag', release['images'][name], remote)
            run('docker', 'push', remote, env=push_env)
            digests = json.loads(inspect(remote, '{{json .RepoDigests}}'))
            remote_images[name] = next(d for d in digests if d.startswith(f'{REPOSITORY}/{name}@'))
    privacy_checks.append(private_registry_proof(gcloud))
    (attempt / 'registry-privacy.json').write_text(json.dumps(privacy_checks, indent=2) + '\n')
    spec = STATE / 'service.json'  # JSON is also a valid YAML service document.
    spec.write_text(json.dumps(service_spec(remote_images, current, runtime_identity=identity), indent=2) + '\n')
    run(gcloud, 'run', 'services', 'replace', str(spec), *flags, '--dry-run')
    status = dict(status='update_outcome_uncertain', access_policy='preserved', model_kind=model_kind,
                  project=PROJECT, region=REGION, service=SERVICE, tag=release['tag'],
                  runtime_service_account=identity,
                  attempt=str(attempt), registry_privacy=privacy_checks[-1])
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    build_command = commands.add_parser('build')
    build_command.add_argument('artifact_dir', type=Path)
    build_command.add_argument('--artifact-lock', type=Path, help='Require exact reviewed model bytes before any Docker build')
    publication = commands.add_parser('publish')
    publication.add_argument('--authenticated', action='store_true', help='Verify using the already authorized gcloud identity; no IAM changes')
    publication.add_argument('--allow-demo-model', action='store_true', help='Explicitly permit a clearly labeled synthetic/sample model; not real-data evidence')
    publication.add_argument('--runtime-service-account', type=validated_runtime_identity, default=IDENTITY,
                             help='Existing runtime service account in this project; creates no account or IAM grants')
    args = parser.parse_args(argv)
    try:
        if args.command == 'build':
            build(args.artifact_dir.resolve(), artifact_lock=args.artifact_lock)
        else:
            publish(authenticated=args.authenticated, allow_demo_model=args.allow_demo_model,
                    runtime_identity=args.runtime_service_account)
    except subprocess.CalledProcessError as error:
        raise SystemExit(f'Stopped: {error.cmd[0]} returned {error.returncode}. Resolve the error above before retrying.') from None


if __name__ == '__main__':
    main()
