"""Deployment checks use fake subprocesses and HTTP responses, never cloud or Docker."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / 'deploy/cloud-run'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, DEPLOY / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RollbackTraffic(unittest.TestCase):
    def setUp(self):
        self.deploy = load('rollback_traffic', 'deploy.py')

    def service(self, traffic):
        return {'status': {'latestReadyRevisionName': 'revision-b', 'traffic': traffic}}

    def test_active_revision_wins_over_newer_ready_revision(self):
        plan = self.deploy.rollback_plan(self.service([{'revisionName': 'revision-a', 'percent': 100}]))
        self.assertEqual(plan['allocations'], {'revision-a': 100})
        self.assertIn('--to-revisions=revision-a=100', plan['command'])
        self.assertNotIn('revision-b', ' '.join(plan['command']))

    def test_split_traffic_and_resolved_latest_revision_are_preserved(self):
        plan = self.deploy.rollback_plan(self.service([
            {'revisionName': 'revision-a', 'percent': 90},
            {'revisionName': 'revision-b', 'latestRevision': True, 'percent': 10},
            {'revisionName': 'revision-preview', 'tag': 'preview', 'percent': 0},
        ]))
        self.assertEqual(plan['allocations'], {'revision-a': 90, 'revision-b': 10})
        self.assertIn('--to-revisions=revision-a=90,revision-b=10', plan['command'])

    def test_unresolved_or_incomplete_allocations_stop_before_publication(self):
        for traffic in (None, [], [{'latestRevision': True, 'percent': 100}],
                        [{'revisionName': 'revision-a', 'percent': 90}],
                        [{'revisionName': 'revision-a', 'percent': True}]):
            with self.subTest(traffic=traffic), self.assertRaises(SystemExit):
                self.deploy.rollback_plan(self.service(traffic))

    def test_retries_keep_independent_snapshots_and_only_print_rollback(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.deploy.STATE = Path(temporary)
            first = self.service([{'revisionName': 'revision-a', 'percent': 100}])
            second = self.service([{'revisionName': 'revision-a', 'percent': 90},
                                   {'revisionName': 'revision-b', 'percent': 10}])
            with patch.object(self.deploy, 'run') as command, redirect_stdout(io.StringIO()) as printed:
                attempt_a = self.deploy.save_attempt(first, {'tag': 'first'}, {'checked': True})
                attempt_b = self.deploy.save_attempt(second, {'tag': 'retry'}, {'checked': True})
            command.assert_not_called()
            self.assertNotEqual(attempt_a, attempt_b)
            self.assertEqual(json.loads((attempt_a / 'previous-service.json').read_text()), first)
            self.assertEqual(json.loads((attempt_b / 'previous-service.json').read_text()), second)
            self.assertIn('--to-revisions=revision-a=100', (attempt_a / 'rollback.txt').read_text())
            self.assertIn('--to-revisions=revision-a=90,revision-b=10', (attempt_b / 'rollback.txt').read_text())
            self.assertIn('does not execute rollback', printed.getvalue())


class PackagingIdentity(unittest.TestCase):
    def setUp(self):
        self.deploy = load('packaging_identity', 'deploy.py')

    def test_source_identity_includes_deployment_packaging_tree(self):
        def revision(*args, **kwargs):
            return args[-1] + '-tree\n'
        with patch.object(self.deploy, 'run', side_effect=revision):
            trees = self.deploy.source_trees()
        self.assertEqual(set(trees), {'src/backend', 'frontend/prototype', 'deploy/cloud-run'})

    def test_dirty_packaging_stops_build_before_preparation_docker_or_cloud(self):
        for filename in ('Dockerfile.backend', '.dockerignore', 'prepare-artifacts.py', 'deploy.py'):
            with self.subTest(filename=filename):
                with patch.object(self.deploy, 'run', return_value=' M deploy/cloud-run/' + filename) as command:
                    with self.assertRaisesRegex(SystemExit, 'packaging changes'):
                        self.deploy.build(Path('/unused-model-export'))
                self.assertEqual(command.call_count, 1)
                self.assertEqual(command.call_args.args[:4], ('git', 'status', '--porcelain', '--'))
                self.assertIn('deploy/cloud-run', command.call_args.args)

    def test_dirty_or_old_packaging_identity_stops_publish_before_docker_or_cloud(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.deploy.STATE = Path(temporary)
            trees = {path: path + '-tree' for path in self.deploy.SOURCE_PATHS}
            release = dict(tag='test', model_version='real-model', image_ids={'frontend': 'image-id'},
                           source_trees=trees)
            (self.deploy.STATE / 'local-smoke.json').write_text(json.dumps(
                dict(tag='test', passed=True, image_ids=release['image_ids'])))
            for dirty, recorded in ((' M deploy/cloud-run/Dockerfile.backend', trees),
                                    ('', {k: v for k, v in trees.items() if k != 'deploy/cloud-run'})):
                (self.deploy.STATE / 'release.json').write_text(json.dumps({**release, 'source_trees': recorded}))
                with patch.object(self.deploy, 'run', return_value=dirty) as command, \
                        patch.object(self.deploy, 'source_trees', return_value=trees):
                    with self.assertRaisesRegex(SystemExit, 'packaging source changed'):
                        self.deploy.publish()
                self.assertEqual(command.call_count, 1)
                self.assertEqual(command.call_args.args[0], 'git')


class AdministratorLookups(unittest.TestCase):
    def run_setup(self, repository='found', account='found'):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            fake = directory / 'gcloud'
            fake.write_text('#!' + sys.executable + '\n' + '''import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with Path(os.environ['TB_TEST_CALLS']).open('a') as output:
    output.write(json.dumps(args) + '\\n')
if 'get-iam-policy' in args:
    print('{"bindings": []}')
elif 'describe' in args:
    scope = 'REPOSITORY' if args[:2] == ['artifacts', 'repositories'] else 'ACCOUNT'
    result = os.environ['TB_TEST_' + scope]
    if result != 'found':
        reason = {'not_found': 'NOT_FOUND: Requested entity was not found.',
                  'denied': 'PERMISSION_DENIED: 403 caller cannot query; NOT_FOUND: is not evidence.',
                  'transient': 'UNAVAILABLE: service temporarily unavailable.'}[result]
        print('ERROR: (gcloud.' + '.'.join(args[:3]) + ') ' + reason, file=sys.stderr)
        sys.exit(1)
''')
            fake.chmod(0o755)
            calls = directory / 'calls.jsonl'
            environment = dict(os.environ, PATH=str(directory) + os.pathsep + os.environ['PATH'],
                               TB_TEST_CALLS=str(calls), TB_TEST_REPOSITORY=repository, TB_TEST_ACCOUNT=account)
            result = subprocess.run(['bash', str(DEPLOY / 'admin-setup.sh'), 'operator@example.invalid'],
                                    env=environment, text=True, capture_output=True)
            return result, [json.loads(line) for line in calls.read_text().splitlines()]

    def test_only_confirmed_not_found_creates_resources(self):
        result, calls = self.run_setup(repository='not_found', account='not_found')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([args[:3] for args in calls if 'create' in args],
                         [['artifacts', 'repositories', 'create'], ['iam', 'service-accounts', 'create']])

    def test_permission_and_transient_failures_do_not_create_or_grant(self):
        for scope in ('repository', 'account'):
            for failure in ('denied', 'transient'):
                with self.subTest(scope=scope, failure=failure):
                    result, calls = self.run_setup(**{scope: failure})
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('no create will be attempted', result.stderr)
                    self.assertFalse(any('create' in args or 'add-iam-policy-binding' in args for args in calls))


class CatalogueTitleSmoke(unittest.TestCase):
    def test_long_catalogue_title_stays_within_search_query_limit(self):
        smoke = load('catalogue_title_smoke', 'smoke.py')
        title = 'A very long catalogue title ' * 8
        queries = []
        release = dict(tag='test', num_books=7, model_version='test-model')

        def read_json(base, path, data=None):
            if path == '/api/health':
                return dict(status='ok', num_books=7, model_version='test-model')
            if path == '/healthz':
                return dict(status='ok')
            if path.startswith('/api/books/search?'):
                query = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)['q'][0]
                queries.append(query)
                if len(query) > 100:
                    raise AssertionError('API would reject a query longer than 100 characters')
                return [{'book_id': 'reader-a'}]
            if path.startswith('/api/books/'):
                return dict(book_id=path.rsplit('/', 1)[1], title=title)
            if path == '/api/recommend':
                recommendations = []
                for index in range(5):
                    recommendations.append(dict(book={'book_id': str(index)}, fit_a=.8, fit_b=.6,
                        score=.6 if data['aggregation'] == 'least_misery' else .7,
                        position=dict(x=index, y=index),
                        reasons={'reader_a': {'seed_id': 'reader-a'}, 'reader_b': {'seed_id': 'reader-b'}}))
                return dict(model_version='test-model', aggregation=data['aggregation'], recommendations=recommendations,
                            galaxy={'bridges': [dict(book_id=str(index), x=index, y=index) for index in range(5)]})
            raise AssertionError(path)

        def request(base, path, data=None):
            if path == '/':
                return base + '/a/?api=1', b'TasteBridge'
            raise urllib.error.HTTPError(base + path, 404, 'Not found', {}, None)

        with patch.object(smoke, 'read_json', side_effect=read_json), patch.object(smoke, 'request', side_effect=request):
            result = smoke.check('http://local.test', release, feedback=False, seed_ids=['reader-a', 'reader-b'])
        self.assertTrue(result['passed'])
        self.assertEqual(queries, [title[:100], title[:100]])


if __name__ == '__main__':
    unittest.main()
