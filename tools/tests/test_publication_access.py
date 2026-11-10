import importlib.util
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.request import Request


def load(name, filename):
    path = Path(__file__).resolve().parents[2] / 'deploy/cloud-run' / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PublicationAccess(unittest.TestCase):
    def setUp(self):
        self.deploy = load('publication_access', 'deploy.py')
        self.directory = tempfile.TemporaryDirectory()
        self.state = Path(self.directory.name)
        self.deploy.STATE = self.state
        self.release = dict(tag='test-release', model_version='b2-als-gr-test', source_trees={'backend': 'tree'},
                            images={'frontend': 'local-front', 'backend': 'local-back', 'backend-base': 'local-base'},
                            image_ids={'frontend': 'id-front', 'backend': 'id-back', 'backend-base': 'id-base'})
        (self.state / 'release.json').write_text(json.dumps(self.release))
        (self.state / 'local-smoke.json').write_text(json.dumps(dict(tag='test-release', passed=True,
                                                               image_ids=self.release['image_ids'])))
        self.calls = []
        self.url = 'https://tastebridge-staging-test.us-central1.run.app'
        self.policies = {'project': {'bindings': []}, 'repository': {'bindings': []}}
        self.current_service = None
        self.updated = False

    def tearDown(self):
        self.directory.cleanup()

    def command(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        scope = ('project' if args[:3] == ('gcloud', 'projects', 'get-iam-policy') else
                 'repository' if args[:4] == ('gcloud', 'artifacts', 'repositories', 'get-iam-policy') else None)
        if scope:
            if getattr(self, 'fail_policy', None) == scope:
                raise subprocess.CalledProcessError(1, args)
            policy = self.policies[scope]
            return policy if isinstance(policy, str) else json.dumps(policy)
        if args[:4] == ('gcloud', 'run', 'services', 'list'):
            return json.dumps([self.current_service] if self.current_service else [])
        if args[:4] == ('gcloud', 'run', 'services', 'describe'):
            if getattr(self, 'fail_describe', False):
                raise subprocess.CalledProcessError(1, args)
            if self.current_service and not self.updated:
                return json.dumps(self.current_service)
            return json.dumps({'status': {'url': self.url, 'latestReadyRevisionName': 'test-revision'}})
        if args[:4] == ('gcloud', 'run', 'services', 'replace') and '--dry-run' not in args:
            self.updated = True
        if args[:3] == ('gcloud', 'auth', 'print-identity-token'):
            return 'dummy-test-identity-token'
        if args[:3] == ('docker', 'context', 'inspect'):
            return 'unix:///test/socket'
        if any(str(argument).endswith('smoke.py') for argument in args) and getattr(self, 'fail_smoke', False):
            raise subprocess.CalledProcessError(1, args)
        return ''

    def image(self, image, expression):
        if expression == '{{.Id}}':
            return dict(zip(self.release['images'].values(), self.release['image_ids'].values()))[image]
        return json.dumps([image.rsplit(':', 1)[0] + '@sha256:test'])

    def publish(self, **kwargs):
        with patch.object(self.deploy, 'run', side_effect=self.command), \
                patch.object(self.deploy, 'inspect', side_effect=self.image), \
                patch.object(self.deploy, 'source_trees', return_value=self.release['source_trees']), \
                patch.object(self.deploy.shutil, 'which', return_value='gcloud'):
            with redirect_stdout(io.StringIO()):
                self.deploy.publish(**kwargs)

    def test_publication_preserves_iam_and_records_verified_deployment(self):
        self.publish()
        commands = ' '.join(str(argument) for args, _ in self.calls for argument in args)
        for forbidden in ('add-iam-policy-binding', 'set-iam-policy', 'allUsers', 'allow-unauthenticated'):
            self.assertNotIn(forbidden, commands)
        record = json.loads((self.state / 'deployment.json').read_text())
        self.assertEqual(record['status'], 'deployed_and_api_verified')
        self.assertEqual(record['access_policy'], 'preserved')

    def test_existing_ingress_and_authentication_settings_are_preserved(self):
        current = {'metadata': {'annotations': {'run.googleapis.com/ingress': 'internal',
                    'run.googleapis.com/invoker-iam-disabled': 'false',
                    'run.googleapis.com/default-url-disabled': 'true'}}}
        service = self.deploy.service_spec({'frontend': 'front', 'backend': 'back'}, current)
        for key, value in current['metadata']['annotations'].items():
            self.assertEqual(service['metadata']['annotations'][key], value)

    def test_existing_runtime_account_reaches_spec_and_deployment_receipt(self):
        identity = 'tastebridge-api@tastebridge-511403.iam.gserviceaccount.com'
        self.publish(runtime_identity=identity)
        service = json.loads((self.state / 'service.json').read_text())
        self.assertEqual(service['spec']['template']['spec']['serviceAccountName'], identity)
        record = json.loads((self.state / 'deployment.json').read_text())
        self.assertEqual(record['runtime_service_account'], identity)
        commands = ' '.join(str(argument) for args, _ in self.calls for argument in args)
        for forbidden in ('add-iam-policy-binding', 'set-iam-policy', 'service-accounts create'):
            self.assertNotIn(forbidden, commands)

    def test_default_runtime_identity_remains_compatible(self):
        service = self.deploy.service_spec({'frontend': 'front', 'backend': 'back'})
        self.assertEqual(service['spec']['template']['spec']['serviceAccountName'],
                         'tastebridge-runtime@tastebridge-511403.iam.gserviceaccount.com')

    def test_cli_dispatches_selected_existing_identity_without_executing_publication(self):
        identity = 'tastebridge-api@tastebridge-511403.iam.gserviceaccount.com'
        with patch.object(self.deploy, 'publish') as publish:
            self.deploy.main(['publish', '--authenticated', '--runtime-service-account', identity])
        publish.assert_called_once_with(authenticated=True, allow_demo_model=False, runtime_identity=identity)

    def test_cli_rejects_an_identity_in_another_project_before_publication(self):
        with patch.object(self.deploy, 'publish') as publish, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                self.deploy.main(['publish', '--runtime-service-account',
                                  'tastebridge-api@other-project.iam.gserviceaccount.com'])
        self.assertEqual(error.exception.code, 2)
        publish.assert_not_called()

    def test_invalid_runtime_identity_stops_before_subprocesses_or_state_changes(self):
        for identity in ('', 'tastebridge-api', 'tastebridge-api@other-project.iam.gserviceaccount.com',
                         'tastebridge-api@tastebridge-511403.iam.gserviceaccount.com\n'):
            with self.subTest(identity=identity), patch.object(self.deploy, 'run') as command:
                before = {p.name: p.read_bytes() for p in self.state.iterdir()}
                with self.assertRaisesRegex(ValueError, 'existing service account'):
                    self.deploy.publish(runtime_identity=identity)
                command.assert_not_called()
                self.assertEqual({p.name: p.read_bytes() for p in self.state.iterdir()}, before)

    def test_authorized_token_uses_stdin_and_is_absent_from_argv_and_files(self):
        self.publish(authenticated=True)
        verification = next((args, kwargs) for args, kwargs in self.calls if '--identity-token-stdin' in args)
        self.assertEqual(verification[1]['input'], 'dummy-test-identity-token\n')
        self.assertNotIn('dummy-test-identity-token', str(verification[0]))
        for file in self.state.rglob('*'):
            if file.is_file():
                self.assertNotIn('dummy-test-identity-token', file.read_text())

    def assert_no_publication(self):
        self.assertFalse(any(args[:2] == ('docker', 'push') for args, _ in self.calls))
        self.assertFalse(any(args[:4] == ('gcloud', 'run', 'services', 'replace') for args, _ in self.calls))

    def test_public_project_or_repository_policy_stops_before_upload_or_update(self):
        for scope in ('project', 'repository'):
            for member in ('allUsers', 'allAuthenticatedUsers'):
                with self.subTest(scope=scope, member=member):
                    self.calls.clear()
                    self.policies = {'project': {'bindings': []}, 'repository': {'bindings': []}}
                    self.policies[scope] = {'bindings': [{'role': 'roles/artifactregistry.reader', 'members': [member]}]}
                    with self.assertRaisesRegex(SystemExit, 'Public ' + scope):
                        self.publish()
                    self.assert_no_publication()

    def test_denied_or_unverifiable_policy_stops_before_upload_or_update(self):
        for scope in ('project', 'repository'):
            for value in ('denied', '', '{}', '[]', '{"bindings":null}', '{"bindings":[{}]}'):
                with self.subTest(scope=scope, policy=value):
                    self.calls.clear()
                    self.policies = {'project': {'bindings': []}, 'repository': {'bindings': []}}
                    self.fail_policy = scope if value == 'denied' else None
                    if value != 'denied':
                        self.policies[scope] = value
                    with self.assertRaisesRegex(SystemExit, 'Cannot verify ' + scope):
                        self.publish()
                    self.assert_no_publication()

    def test_policies_are_reread_before_each_push_and_before_service_replace(self):
        self.publish()
        project_reads = [i for i, (args, _) in enumerate(self.calls) if args[:3] == ('gcloud', 'projects', 'get-iam-policy')]
        repository_reads = [i for i, (args, _) in enumerate(self.calls) if args[:4] == ('gcloud', 'artifacts', 'repositories', 'get-iam-policy')]
        pushes = [i for i, (args, _) in enumerate(self.calls) if args[:2] == ('docker', 'push')]
        update = next(i for i, (args, _) in enumerate(self.calls) if args[:4] == ('gcloud', 'run', 'services', 'replace'))
        self.assertEqual(len(project_reads), 3)
        self.assertEqual(len(repository_reads), 3)
        self.assertLess(project_reads[0], pushes[0])
        self.assertLess(repository_reads[0], pushes[0])
        self.assertTrue(pushes[0] < project_reads[1] < repository_reads[1] < pushes[1])
        self.assertTrue(pushes[1] < project_reads[2] < repository_reads[2] < update)
        proof = json.loads((self.state / 'deployment.json').read_text())['registry_privacy']
        self.assertFalse(proof['inherited_policy_verified'])
        self.assertIn('folder/organization', proof['limitation'])

    def test_new_public_binding_after_first_push_blocks_remaining_push_and_service_update(self):
        command = self.command
        reads = 0

        def change_policy(*args, **kwargs):
            nonlocal reads
            if args[:4] == ('gcloud', 'artifacts', 'repositories', 'get-iam-policy'):
                reads += 1
                if reads == 2:
                    self.policies['repository'] = {'bindings': [
                        {'role': 'roles/artifactregistry.reader', 'members': ['allUsers']}]}
            return command(*args, **kwargs)

        self.command = change_policy
        with self.assertRaisesRegex(SystemExit, 'Public repository'):
            self.publish()
        self.assertEqual(sum(args[:2] == ('docker', 'push') for args, _ in self.calls), 1)
        self.assertFalse(any(args[:4] == ('gcloud', 'run', 'services', 'replace') for args, _ in self.calls))

    def test_existing_service_snapshot_uses_active_allocations_before_update(self):
        self.current_service = dict(metadata={'name': self.deploy.SERVICE, 'labels': {'managed-by': self.deploy.OWNER}},
                                    status={'latestReadyRevisionName': 'revision-b',
                                            'traffic': [{'revisionName': 'revision-a', 'percent': 100}]})
        self.publish()
        attempt = Path(json.loads((self.state / 'deployment.json').read_text())['attempt'])
        self.assertEqual(json.loads((attempt / 'rollback.json').read_text())['allocations'], {'revision-a': 100})
        self.assertEqual(json.loads((attempt / 'previous-service.json').read_text()), self.current_service)

    def test_failed_verification_keeps_the_actual_deployment_outcome(self):
        self.fail_smoke = True
        with self.assertRaisesRegex(SystemExit, 'Service updated, but verification failed'):
            self.publish()
        self.assertEqual(json.loads((self.state / 'deployment.json').read_text())['status'], 'deployed_unverified')
        self.assertEqual((self.state / 'url.txt').read_text().strip(), self.url)

    def test_failed_description_still_records_that_update_succeeded(self):
        self.fail_describe = True
        with self.assertRaisesRegex(SystemExit, 'Service update succeeded'):
            self.publish()
        self.assertEqual(json.loads((self.state / 'deployment.json').read_text())['status'], 'deployed_unverified')

    def test_absent_or_unexpected_default_url_never_loses_the_update_record(self):
        for url in (None, 'https://unrelated.example.com'):
            self.url = url
            with self.assertRaisesRegex(SystemExit, 'origin is unexpected'):
                self.publish()
            self.assertEqual(json.loads((self.state / 'deployment.json').read_text())['status'], 'deployed_unverified')
            self.assertFalse((self.state / 'url.txt').exists())

    def test_demo_model_requires_explicit_permission_before_any_upload(self):
        for identity in ('b2-als-synthetic-example', 'sample-shelf-toy-v1'):
            release = {**self.release, 'model_version': identity}
            with self.assertRaisesRegex(SystemExit, 'Demo model detected'):
                self.deploy.publication_model_kind(release)
            self.assertEqual(self.deploy.publication_model_kind(release, True), 'demo_model')
        self.assertIn('not_independently_verified', self.deploy.publication_model_kind(self.release))
        (self.state / 'release.json').write_text(json.dumps({**self.release, 'model_version': 'b2-als-synthetic-test'}))
        with patch.object(self.deploy, 'run') as command:
            with self.assertRaisesRegex(SystemExit, 'Demo model detected'):
                self.deploy.publish()
            command.assert_not_called()


class IdentityScope(unittest.TestCase):
    def setUp(self):
        self.smoke = load('identity_scope', 'smoke.py')

    def test_invalid_origin_or_token_is_rejected(self):
        for url in ('http://example.com', 'https://user@example.com', 'https://example.com/path', 'https://example.com?q=x'):
            with self.assertRaises(ValueError):
                self.smoke.configure_identity_token(url, 'dummy-token')
        for token in ('', 'two tokens', 'a\nb', 'x' * 16385):
            with self.assertRaises(ValueError):
                self.smoke.configure_identity_token('https://example.com', token)

    def test_token_is_sent_only_to_the_explicit_https_origin(self):
        self.smoke.configure_identity_token('https://example.com', 'dummy-token')
        response = MagicMock()
        response.__enter__.return_value = response
        response.geturl.return_value = 'https://example.com/api/health'
        response.read.return_value = b'{}'
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(self.smoke.urllib.request, 'build_opener', return_value=opener):
            self.smoke.request('https://example.com', '/api/health')
            request = opener.open.call_args.args[0]
            self.assertEqual(request.get_header('Authorization'), 'Bearer dummy-token')
            with self.assertRaisesRegex(ValueError, 'restricted'):
                self.smoke.request('https://other.example.com', '/api/health')

    def test_cross_origin_redirect_cannot_receive_the_token(self):
        self.smoke.configure_identity_token('https://example.com', 'dummy-token')
        handler = self.smoke.SameOriginRedirect()
        request = Request('https://example.com', headers={'Authorization': 'Bearer dummy-token'})
        for target in ('https://other.example.com/a', 'http://example.com/a'):
            with self.assertRaisesRegex(ValueError, 'Cross-origin'):
                handler.redirect_request(request, None, 302, 'Found', {}, target)


if __name__ == '__main__':
    unittest.main()
