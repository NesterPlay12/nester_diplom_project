"""Metadata-only watchdog, durable incident policy and safe CLI regressions."""
import contextlib
import hashlib
import io
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from uuid import uuid4
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import backup_monitor as monitor
from app.services.postgres_backups import backup_scope

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
SOURCE = 'postgresql://u:do-not-log@db/source'
SCOPE = backup_scope(SOURCE, 'wildmarket', 'production')
PREFIX = '.private/' + SCOPE


def blob(age=1, verified=True, **overrides):
    snapshot = NOW - timedelta(hours=age)
    values = {
        'name': PREFIX + snapshot.strftime('%Y%m%dT%H%M%S%fZ') + '-' + 'a' * 32 + '.dump',
        'time_created': snapshot,
        'metadata': {
            'format': 'postgresql-custom-v1',
            'restore_verified': 'true' if verified else 'false',
            'verified_at': (snapshot + timedelta(minutes=10)).isoformat(),
        },
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class MetadataTests(unittest.TestCase):
    def check(self, objects):
        bucket = MagicMock()
        bucket.list_blobs.return_value = objects
        with patch.object(monitor, 'storage_bucket', return_value=(bucket, '.private')):
            result = monitor.inspect_freshness(SOURCE, 'wildmarket', 'production', NOW)
        bucket.blob.assert_not_called()
        bucket.list_blobs.assert_called_once_with(
            prefix=PREFIX, timeout=20, retry=None,
            fields='items(name,metadata,timeCreated),nextPageToken',
        )
        return result

    def test_no_backups_or_only_unverified_is_missing(self):
        self.assertEqual(self.check([])['status'], 'missing')
        self.assertEqual(self.check([blob(verified=False)])['status'], 'missing')

    def test_fresh_stale_and_exact_boundary(self):
        for age, status in [(1, 'ok'), (36, 'ok'), (36.001, 'stale'), (72, 'stale')]:
            with self.subTest(age=age):
                result = self.check([blob(age)])
                self.assertEqual(result['status'], status)

    def test_latest_valid_snapshot_wins_not_listing_order(self):
        self.assertEqual(self.check([blob(40), blob(2), blob(60)])['age_hours'], 2)
        self.assertEqual(self.check([blob(60), blob(2), blob(40)])['age_hours'], 2)

    def test_dev_other_source_and_invalid_names_do_not_mask_missing(self):
        objects = [
            blob(name=blob().name.replace('/production/', '/development/')),
            blob(name=blob().name.replace('/' + SCOPE.split('/')[3] + '/', '/other-source/')),
            blob(name=PREFIX + 'nested/' + blob().name.split('/')[-1]),
            blob(name=PREFIX + 'migration.sqlite'),
            blob(name=PREFIX + '20269999T999999000000Z-' + 'a' * 32 + '.dump'),
        ]
        self.assertEqual(self.check(objects)['status'], 'missing')

    def test_invalid_verification_metadata_and_future_times_ignored(self):
        for bad in [None, '', 'not-a-date', NOW.replace(tzinfo=None).isoformat(),
                    (NOW + timedelta(hours=3)).isoformat()]:
            item = blob()
            item.metadata['verified_at'] = bad
            self.assertEqual(self.check([item])['status'], 'missing')
        self.assertEqual(self.check([blob(time_created=None)])['status'], 'missing')
        self.assertEqual(self.check([blob(-1)])['status'], 'missing')
        item = blob()
        item.metadata['format'] = 'not-a-backup'
        self.assertEqual(self.check([item])['status'], 'missing')

    def test_reverified_old_snapshot_remains_stale(self):
        item = blob(72)
        item.metadata['verified_at'] = NOW.isoformat()
        self.assertEqual(self.check([item])['status'], 'stale')
        # Even re-uploading an old snapshot must not reset the RPO clock.
        item.time_created = NOW
        self.assertEqual(self.check([item])['status'], 'stale')

    def test_storage_errors_are_redacted_including_pagination(self):
        def broken_iterator():
            yield blob()
            raise RuntimeError('private bucket/path and secret password')
        for objects in [broken_iterator()]:
            self.assertEqual(self.check(objects), {'status': 'storage_error'})
        with patch.object(monitor, 'storage_bucket', side_effect=RuntimeError('secret')):
            self.assertEqual(
                monitor.inspect_freshness(SOURCE, 'wildmarket', 'production', NOW),
                {'status': 'storage_error'},
            )

    def test_writer_and_monitor_share_scope_and_isolate_environment_schema_source(self):
        for url, schema, env in [
            (SOURCE, 'wildmarket', 'development'),
            (SOURCE, 'other', 'production'),
            ('postgresql://db/other', 'wildmarket', 'production'),
        ]:
            self.assertNotEqual(backup_scope(url, schema, env), SCOPE)
        self.assertEqual(
            backup_scope('postgresql://other:changed-password@db/source', 'wildmarket', 'production'),
            SCOPE,
        )

    def test_manifest_matches_approved_policy(self):
        manifest = json.loads(
            (Path(__file__).resolve().parents[1] / 'migration-manifest.json').read_text()
        )['backup_freshness_monitor']
        self.assertEqual(manifest['max_age_hours'], monitor.MAX_AGE_HOURS)
        self.assertEqual(manifest['schedule'], '0 * * * *')
        self.assertEqual(manifest['notification_policy'], 'one_failure_per_continuous_incident')

    def test_optional_watchdog_table_cannot_block_website_startup(self):
        from app.models import db
        self.assertNotIn('backup_monitor_states', db.metadata.tables)
        self.assertEqual(monitor.state_table('wildmarket').schema, 'wildmarket')


class LatchTests(unittest.TestCase):
    def run_check(self, status, previous=False, lock=True):
        connection = MagicMock()
        engine = MagicMock()
        engine.begin.return_value.__enter__.return_value = connection
        connection.execute.return_value.scalar.return_value = lock
        connection.execute.return_value.mappings.return_value.one.return_value = {
            'incident_open': previous,
        }
        with patch.object(monitor, 'inspect_freshness', return_value={'status': status}) as inspect:
            result = monitor.run_monitor(engine, SOURCE, 'wildmarket', 'production', NOW)
        return result, engine, connection, inspect

    def test_missing_stale_storage_error_first_alert_only(self):
        for status in ['missing', 'stale', 'storage_error']:
            with self.subTest(status=status):
                (result, code), engine, _, _ = self.run_check(status)
                self.assertEqual(code, 1)
                self.assertTrue(result['alert'])
                engine.begin.return_value.__exit__.assert_called_once_with(None, None, None)
                (result, code), _, _, _ = self.run_check(status, previous=True)
                self.assertEqual(code, 0)
                self.assertFalse(result['alert'])

    def test_recovery_rearms_next_incident_without_email(self):
        (result, code), _, connection, _ = self.run_check('ok', previous=True)
        self.assertEqual(code, 0)
        self.assertTrue(result['recovered'])
        update = connection.execute.call_args.args[0]
        self.assertFalse(update.compile().params['incident_open'])
        (result, code), _, _, _ = self.run_check('stale', previous=False)
        self.assertEqual(code, 1)

    def test_concurrent_check_does_not_alert_or_probe_storage(self):
        (result, code), _, _, inspect = self.run_check('stale', lock=False)
        self.assertEqual((result['status'], code), ('check_in_progress', 0))
        inspect.assert_not_called()

    def test_commit_failure_cannot_return_successful_claim(self):
        engine = MagicMock()
        connection = engine.begin.return_value.__enter__.return_value
        connection.execute.return_value.scalar.return_value = True
        connection.execute.return_value.mappings.return_value.one.return_value = {'incident_open': False}
        engine.begin.return_value.__exit__.side_effect = RuntimeError('commit failed')
        with patch.object(monitor, 'inspect_freshness', return_value={'status': 'stale'}):
            with self.assertRaises(RuntimeError):
                monitor.run_monitor(engine, SOURCE, 'wildmarket', 'production', NOW)


class CliTests(unittest.TestCase):
    def test_missing_config_redacted_without_repeated_failure_email(self):
        env = {k: v for k, v in os.environ.items()
               if k not in {'FLASK_DATABASE_SOURCE', 'FLASK_DATABASE_URL'}}
        process = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1] / 'monitor_backups.py')],
            env=env, capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(process.returncode, 0)
        self.assertEqual(json.loads(process.stderr)['status'], 'monitor_unavailable')
        self.assertNotIn('Traceback', process.stderr)

    def test_cli_exit_codes_and_safe_output(self):
        path = Path(__file__).resolve().parents[1] / 'monitor_backups.py'
        spec = importlib.util.spec_from_file_location('watchdog_cli', path)
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        for status, expected in [('missing', 1), ('stale', 1), ('storage_error', 1), ('ok', 0)]:
            with (
                patch('app.config._get_db_url', return_value=SOURCE),
                patch('sqlalchemy.create_engine') as engine,
                patch.object(monitor, 'run_monitor', return_value=({'status': status}, expected)),
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                self.assertEqual(cli.main(), expected)
                self.assertEqual(json.loads(output.getvalue())['status'], status)
                engine.return_value.dispose.assert_called_once()


@unittest.skipUnless(os.environ.get('TEST_BACKUP_MONITOR_POSTGRES') == '1',
                     'Opt-in development PostgreSQL check')
class PostgresLatchTests(unittest.TestCase):
    def test_durable_latch_recovery_and_overlapping_process(self):
        from sqlalchemy import create_engine, text
        from app.config import _get_db_url
        self.assertEqual(os.environ.get('APP_ENV'), 'development')
        engine = create_engine(_get_db_url(), hide_parameters=True)
        schema = os.environ.get('FLASK_DATABASE_SCHEMA', 'wildmarket')
        # Random synthetic scope isolates this check from actual monitor incidents.
        source = 'postgresql://watchdog-check/' + uuid4().hex
        scope = backup_scope(source, schema, 'development')
        key = hashlib.sha256(scope.encode()).hexdigest()
        # Identifier validation performed by backup_scope above.
        table = f'"{schema}".backup_monitor_states'
        try:
            for status, expected, recovered in [
                ('missing', 1, False),
                ('stale', 0, False),
                ('storage_error', 0, False),
                ('ok', 0, True),
                ('ok', 0, False),
                ('storage_error', 1, False),
                ('storage_error', 0, False),
            ]:
                with patch.object(monitor, 'inspect_freshness', return_value={'status': status}):
                    # Each invocation starts and commits a new transaction.
                    result, code = monitor.run_monitor(engine, source, schema, 'development', NOW)
                self.assertEqual(code, expected)
                self.assertEqual(result['recovered'], recovered)
            with engine.begin() as holder:
                holder.execute(text('SELECT pg_advisory_xact_lock(hashtext(:key))'), {
                    'key': 'backup-monitor:' + key,
                })
                with patch.object(monitor, 'inspect_freshness') as inspect:
                    result, code = monitor.run_monitor(engine, source, schema, 'development', NOW)
                self.assertEqual(result['status'], 'check_in_progress')
                self.assertEqual(code, 0)
                inspect.assert_not_called()
            with engine.connect() as connection:
                row = connection.execute(text(
                    f'SELECT incident_open, last_status FROM {table} WHERE scope_key=:key'
                ), {'key': key}).one()
                self.assertEqual(tuple(row), (True, 'storage_error'))
        finally:
            with engine.begin() as connection:
                connection.execute(text(f'DELETE FROM {table} WHERE scope_key=:key'), {'key': key})
            engine.dispose()


if __name__ == '__main__':
    unittest.main()
