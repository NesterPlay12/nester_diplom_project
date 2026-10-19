"""No credentials or real records: failure-path and retention regression checks."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import postgres_backups as backups


class BackupTests(unittest.TestCase):
    def test_production_requires_dedicated_restore_access_before_upload(self):
        source = 'postgresql://web:fake@db/source'
        for maintenance in [None, 'postgresql://web:other@db:5432/maintenance']:
            with self.subTest(maintenance=bool(maintenance)):
                with patch.object(backups, 'storage_bucket') as storage:
                    with self.assertRaises(backups.BackupError):
                        backups.run_backup(source, environment='production',
                                           maintenance_url=maintenance)
                    storage.assert_not_called()

    def test_dedicated_restore_role_or_server_passes_access_gate(self):
        for maintenance in ['postgresql://restore:fake@db/postgres',
                            'postgresql://web:fake@verification-server/postgres']:
            with self.subTest(target='separate'):
                # Stop at storage: this check must not create a real database.
                with patch.object(backups, 'storage_bucket', side_effect=RuntimeError('stop')) as storage:
                    with self.assertRaisesRegex(RuntimeError, '^stop$'):
                        backups.run_backup('postgresql://web:fake@db/source',
                                           environment='production', maintenance_url=maintenance)
                    storage.assert_called_once()

    def test_invalid_restore_connection_fails_before_upload(self):
        with patch.object(backups, 'storage_bucket') as storage:
            with self.assertRaises(backups.BackupError):
                backups.run_backup('postgresql://web:fake@db/source',
                                   environment='production', maintenance_url='sqlite:///unused')
            storage.assert_not_called()

    def test_manifest_matches_approved_policy(self):
        policy = json.loads(
            (Path(__file__).resolve().parents[1] / 'migration-manifest.json').read_text()
        )['regular_postgresql_backups']
        self.assertEqual(policy['retention_days'], backups.RETENTION_DAYS)
        self.assertEqual((policy['schedule'], policy['timezone']), ('0 0 * * *', 'UTC'))

    def test_password_only_in_environment_not_arguments(self):
        with patch.object(backups.subprocess, 'run') as run:
            backups.pg_command(['pg_dump', '--format=custom'], 'postgresql://u:fake-secret@db/source')
        args, kwargs = run.call_args
        self.assertNotIn('fake-secret', str(args))
        self.assertEqual(kwargs['env']['PGPASSWORD'], 'fake-secret')
        self.assertNotIn('PGOPTIONS', kwargs['env'])

    def test_child_errors_are_sanitized_and_timeout_is_bounded(self):
        for error in (
            subprocess.CalledProcessError(1, 'pg_dump', stderr=b'password=private-value'),
            subprocess.TimeoutExpired('pg_dump', 1200, stderr=b'private-value'),
        ):
            with self.subTest(error=type(error).__name__):
                with patch.object(backups.subprocess, 'run', side_effect=error):
                    with self.assertRaises(backups.BackupError) as raised:
                        backups.pg_command(['pg_dump'], 'postgresql://u:fake@db/source')
                self.assertNotIn('private-value', str(raised.exception))
                self.assertNotIn('private-value', repr(raised.exception.__cause__))

    def test_rejects_non_postgres_and_unsafe_identifiers(self):
        for url in ('sqlite:///db', 'postgresql://db/source?options=unsafe'):
            with self.assertRaises(backups.BackupError):
                backups.pg_environment(url)
        for name in ('wildmarket"; DROP SCHEMA public;--', 'public.wildmarket', ''):
            with self.assertRaises(backups.BackupError):
                backups.identifier(name)

    def test_retention_only_deletes_expired_regular_objects_from_this_prefix(self):
        now = datetime(2026, 10, 19, tzinfo=timezone.utc)
        prefix = '.private/postgresql-backups/v1/development/source/wildmarket/'
        def blob(day, suffix, verified='true', format='postgresql-custom-v1'):
            return SimpleNamespace(
                name=prefix + suffix, metadata={'restore_verified': verified, 'format': format},
                time_created=now - timedelta(days=day), generation=42, delete=MagicMock(),
            )
        filename = '20260901T000000000000Z-' + 'a' * 32 + '.dump'
        expired = blob(31, filename)
        unverified = blob(31, filename.replace('a' * 32, 'b' * 32), 'false')
        fresh = blob(29, filename.replace('a' * 32, 'c' * 32))
        boundary = blob(30, filename.replace('a' * 32, 'd' * 32))
        legacy = blob(99, 'wildmarket.sqlite')
        nested = blob(99, 'other/' + filename)
        foreign = blob(99, filename, format='other')
        current = blob(40, filename.replace('a' * 32, 'e' * 32))
        bucket = MagicMock()
        bucket.list_blobs.return_value = [expired, unverified, fresh, boundary, legacy, nested, foreign, current]
        self.assertEqual(backups.prune_verified(bucket, prefix, now, current.name), 2)
        for item in (expired, unverified):
            item.delete.assert_called_once_with(if_generation_match=42)
        for item in (fresh, boundary, legacy, nested, foreign, current):
            item.delete.assert_not_called()
        bucket.list_blobs.assert_called_once_with(prefix=prefix)

    def test_restore_uses_new_database_and_cleans_up_after_failure(self):
        maintenance = MagicMock()
        connection = maintenance.connect.return_value.__enter__.return_value
        with patch.object(backups, 'create_engine', return_value=maintenance):
            with self.assertRaisesRegex(RuntimeError, 'simulated restore failure'):
                with backups.verification_database('postgresql://u:fake@db/source') as target:
                    self.assertNotEqual(target.database, 'source')
                    self.assertTrue(target.database.startswith(backups.RESTORE_PREFIX))
                    raise RuntimeError('simulated restore failure')
        statements = [c.args[0] for c in connection.exec_driver_sql.call_args_list]
        self.assertEqual(len(statements), 2)
        self.assertTrue(statements[0].startswith('CREATE DATABASE "wm_backup_verify_'))
        self.assertTrue(statements[1].startswith('DROP DATABASE "wm_backup_verify_'))
        self.assertNotIn('"source"', ''.join(statements))
        maintenance.dispose.assert_called_once()

    def test_no_drop_if_database_creation_fails(self):
        maintenance = MagicMock()
        connection = maintenance.connect.return_value.__enter__.return_value
        connection.exec_driver_sql.side_effect = RuntimeError('no CREATEDB privilege')
        with patch.object(backups, 'create_engine', return_value=maintenance):
            with self.assertRaises(RuntimeError):
                with backups.verification_database('postgresql://u:fake@db/source'):
                    self.fail('must not yield')
        self.assertEqual(connection.exec_driver_sql.call_count, 1)

    def test_failed_verification_does_not_return_success(self):
        with patch.object(backups, 'verification_database') as database:
            database.return_value.__enter__.return_value = backups.make_url('postgresql://u:fake@db/isolated')
            with patch.object(backups, 'pg_command', side_effect=backups.BackupError('restore failed')):
                with self.assertRaises(backups.BackupError):
                    backups.verify_archive(Path('unused.dump'), {}, 'postgresql://db/source', 'wildmarket')
            database.return_value.__exit__.assert_called_once()

    def test_full_pipeline_fails_closed_before_retention(self):
        for failure in ('upload', 'checksum', 'restore', 'marker', None):
            with self.subTest(failure=failure):
                engine = MagicMock()
                connection = engine.connect.return_value.execution_options.return_value.__enter__.return_value
                connection.execute.return_value.scalar.return_value = True
                connection.exec_driver_sql.return_value.scalar.return_value = 'snapshot'
                bucket = MagicMock()
                blob = bucket.blob.return_value
                blob.generation = 9
                blob.metageneration = 4
                if failure == 'upload':
                    blob.upload_from_filename.side_effect = RuntimeError('private connection details')
                blob.download_to_filename.side_effect = lambda path, **kw: Path(path).write_bytes(
                    b'corrupted' if failure == 'checksum' else b'valid dump'
                )
                if failure == 'marker':
                    blob.patch.side_effect = RuntimeError('private connection details')
                def dump(arguments, url):
                    Path(arguments[arguments.index('--file') + 1]).write_bytes(b'valid dump')
                with (
                    patch.object(backups, 'create_engine', return_value=engine),
                    patch.object(backups, 'inspect') as inspector,
                    patch.object(backups, 'storage_bucket', return_value=(bucket, '.private')),
                    patch.object(backups, 'pg_command', side_effect=dump),
                    patch.object(backups, 'schema_fingerprints', return_value={'orders': {}}),
                    patch.object(backups, 'verify_archive') as verify,
                    patch.object(backups, 'prune_verified', return_value=0) as prune,
                ):
                    inspector.return_value.get_table_names.return_value = ['orders']
                    if failure == 'restore':
                        verify.side_effect = backups.BackupError('restore failed')
                    if failure is None:
                        result = backups.run_backup('postgresql://u:fake@db/source')
                        self.assertTrue(result['restore_verified'])
                        verify.assert_called_once()
                        blob.patch.assert_called_once_with(if_metageneration_match=4)
                        prune.assert_called_once()
                    else:
                        with self.assertRaises(backups.BackupError) as raised:
                            backups.run_backup('postgresql://u:fake@db/source')
                        self.assertNotIn('private connection details', str(raised.exception))
                        prune.assert_not_called()
                        if failure in ('upload', 'checksum', 'restore'):
                            blob.patch.assert_not_called()
                    engine.dispose.assert_called_once()

    def test_cli_config_error_is_nonzero_and_never_logs_url(self):
        env = {**os.environ, 'FLASK_DATABASE_URL': 'mysql://u:fake-sensitive@db/source'}
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1] / 'backup.py')],
            env=env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('fake-sensitive', result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertEqual(json.loads(result.stderr)['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
