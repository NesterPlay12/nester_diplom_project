"""Private PostgreSQL snapshots; never called by a web worker or app startup."""
import hashlib
import json
import os
import re
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import MetaData, create_engine, inspect, select, text
from sqlalchemy.engine import make_url

from .database_transfer import storage_bucket

RETENTION_DAYS = 30
COMMAND_TIMEOUT = 1200
RESTORE_PREFIX = 'wm_backup_verify_'
BACKUP_NAME = re.compile(r'^\d{8}T\d{12}Z-[0-9a-f]{32}\.dump$')


class BackupError(RuntimeError):
    """Safe to log: must never contain SQL, rows, credentials or child stderr."""


def identifier(value):
    if not re.fullmatch(r'[a-z_][a-z0-9_]{0,62}', value):
        raise BackupError('Invalid PostgreSQL identifier.')
    return '"' + value + '"'


def pg_environment(url):
    """Passwords stay in child environment, never argv or log messages."""
    url = make_url(url)
    if url.get_backend_name() != 'postgresql' or not url.database:
        raise BackupError('PostgreSQL connection required.')
    # Do not inherit PGOPTIONS/search_path or another database's credentials.
    env = {k: v for k, v in os.environ.items() if not k.startswith('PG')}
    for key, value in {
        'PGHOST': url.host, 'PGPORT': url.port, 'PGUSER': url.username,
        'PGPASSWORD': url.password, 'PGDATABASE': url.database,
        'PGCONNECT_TIMEOUT': '15',
    }.items():
        if value is not None:
            env[key] = str(value)
    for key, value in url.query.items():
        if key not in {'sslmode', 'sslrootcert', 'sslcert', 'sslkey', 'channel_binding'}:
            raise BackupError('Unsupported PostgreSQL connection option.')
        env['PG' + key.upper()] = str(value)
    return env


def pg_command(arguments, url):
    try:
        subprocess.run(
            arguments, env=pg_environment(url), check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            timeout=COMMAND_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        raise BackupError(f'{arguments[0]} failed or timed out; no sensitive output logged.') from None


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def schema_fingerprints(connection, schema):
    """Reflect the live schema, not the old migration's fixed list of tables."""
    metadata = MetaData()
    metadata.reflect(connection, schema=schema, views=False)
    result = {}
    for table in metadata.sorted_tables:
        # Multiset hashes also support tables without an id or primary key.
        hashes = []
        for row in connection.execution_options(stream_results=True).execute(select(table)).mappings():
            payload = json.dumps(
                dict(row), sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                default=lambda value: (
                    {'bytes_hex': bytes(value).hex()}
                    if isinstance(value, (bytes, memoryview)) else str(value)
                ),
            ).encode()
            hashes.append(hashlib.sha256(payload).digest())
        digest = hashlib.sha256()
        for value in sorted(hashes):
            digest.update(value)
        result[table.name] = {'rows': len(hashes), 'sha256': digest.hexdigest()}
    if not result:
        raise BackupError('Source schema contains no tables.')
    return result


@contextmanager
def verification_database(source_url, maintenance_url=None):
    """Create an entirely separate, disposable DB, never restore into source.

    A separate cluster can be selected with a dedicated maintenance credential.
    That credential needs CREATEDB; an existing database is never overwritten.
    """
    url = make_url(maintenance_url or source_url)
    pg_environment(url)  # Validate before contacting a server.
    name = RESTORE_PREFIX + uuid4().hex
    maintenance = create_engine(url, isolation_level='AUTOCOMMIT', hide_parameters=True)
    created = False
    try:
        with maintenance.connect() as connection:
            connection.exec_driver_sql(
                f'CREATE DATABASE {identifier(name)} TEMPLATE template0'
            )
            created = True
        target_url = url.set(database=name)
        yield target_url
    finally:
        try:
            if created:
                with maintenance.connect() as connection:
                    # Only the random database created by THIS invocation is removed.
                    connection.exec_driver_sql(
                        f'DROP DATABASE {identifier(name)} WITH (FORCE)'
                    )
        finally:
            maintenance.dispose()


def verify_archive(path, expected, source_url, schema, maintenance_url=None):
    with verification_database(source_url, maintenance_url) as target_url:
        pg_command([
            'pg_restore', '--exit-on-error', '--no-owner', '--no-privileges',
            '--dbname', target_url.database, str(path),
        ], target_url)
        engine = create_engine(target_url, hide_parameters=True)
        try:
            with engine.connect() as restored:
                restored.exec_driver_sql("SET LOCAL TIME ZONE 'UTC'")
                if schema_fingerprints(restored, schema) != expected:
                    raise BackupError('Restored database does not match snapshot.')
                if inspect(restored).get_schema_names().count(schema) != 1:
                    raise BackupError('Restored schema is missing.')
        finally:
            engine.dispose()


def prune_verified(bucket, prefix, now, current_name):
    """Prune regular objects only AFTER the current backup has been verified.

    Expired incomplete uploads are also removed, but never migration copies.
    """
    cutoff = now - timedelta(days=RETENTION_DAYS)
    deleted = 0
    for blob in bucket.list_blobs(prefix=prefix):
        basename = blob.name.removeprefix(prefix)
        if not BACKUP_NAME.fullmatch(basename) or blob.name == current_name:
            continue
        metadata = blob.metadata or {}
        if metadata.get('format') != 'postgresql-custom-v1':
            continue
        if blob.time_created is None or blob.time_created >= cutoff:
            continue
        # Generation precondition prevents deleting an object replaced since listing.
        blob.delete(if_generation_match=blob.generation)
        deleted += 1
    return deleted


def backup_scope(source_url, schema, environment):
    """Shared namespace for backup writer and independent metadata monitor."""
    identifier(schema)
    if environment not in {'development', 'staging', 'production'}:
        raise BackupError('Explicit backup environment required.')
    pg_environment(source_url)
    url = make_url(source_url)
    source_id = hashlib.sha256(
        json.dumps([url.host, url.port, url.database]).encode()
    ).hexdigest()[:20]
    return f'postgresql-backups/v1/{environment}/{source_id}/{schema}/'


def run_backup(source_url, schema='wildmarket', environment='development',
               maintenance_url=None, now=None):
    """Upload -> download -> SHA-256 -> restore in separate DB -> retention."""
    scope = backup_scope(source_url, schema, environment)
    now = now or datetime.now(timezone.utc)
    url = make_url(source_url)
    bucket, private_prefix = storage_bucket()
    prefix = f'{private_prefix}/{scope}'
    stamp = now.strftime('%Y%m%dT%H%M%S%fZ')
    name = f'{prefix}{stamp}-{uuid4().hex}.dump'
    engine = create_engine(url, hide_parameters=True, pool_pre_ping=True)
    stage = 'snapshot'
    try:
        # Session lock spans upload, restore and retention, not just the dump.
        with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as lock:
            acquired = lock.execute(text(
                'SELECT pg_try_advisory_lock(hashtext(:key))'
            ), {'key': 'wildmarket-backup:' + schema}).scalar()
            if not acquired:
                raise BackupError('Another backup is running.')
            try:
                with tempfile.TemporaryDirectory(prefix='wildmarket-backup-') as work:
                    os.chmod(work, 0o700)
                    archive = Path(work) / 'snapshot.dump'
                    # Create files with restrictive permissions before any data is written.
                    archive.touch(mode=0o600)
                    with engine.connect().execution_options(
                        isolation_level='REPEATABLE READ'
                    ) as source:
                        with source.begin():
                            source.exec_driver_sql('SET TRANSACTION READ ONLY')
                            source.exec_driver_sql("SET LOCAL TIME ZONE 'UTC'")
                            source.exec_driver_sql("SET LOCAL statement_timeout = '120s'")
                            # Protect the schema's tables from DDL during this snapshot.
                            tables = inspect(source).get_table_names(schema=schema)
                            if not tables:
                                raise BackupError('Source schema contains no tables.')
                            quoted = ', '.join(
                                f'{identifier(schema)}.{identifier(t)}' for t in tables
                            )
                            source.exec_driver_sql(f'LOCK TABLE {quoted} IN ACCESS SHARE MODE')
                            snapshot = source.exec_driver_sql('SELECT pg_export_snapshot()').scalar()
                            expected = schema_fingerprints(source, schema)
                            pg_command([
                                'pg_dump', '--format=custom', '--no-owner', '--no-privileges',
                                '--strict-names', '--schema', schema, '--snapshot', snapshot,
                                '--file', str(archive),
                            ], url)
                    checksum = file_hash(archive)
                    stage = 'private-upload'
                    blob = bucket.blob(name)
                    blob.metadata = {
                        'sha256': checksum, 'restore_verified': 'false',
                        'format': 'postgresql-custom-v1',
                    }
                    # No public ACL, signed URL, or web download endpoint is created.
                    blob.upload_from_filename(
                        str(archive), if_generation_match=0, timeout=COMMAND_TIMEOUT,
                        checksum='auto',
                    )
                    stage = 'download-verification'
                    downloaded = Path(work) / 'downloaded.dump'
                    downloaded.touch(mode=0o600)
                    blob.download_to_filename(
                        str(downloaded), if_generation_match=blob.generation,
                        timeout=COMMAND_TIMEOUT,
                    )
                    if file_hash(downloaded) != checksum:
                        raise BackupError('Downloaded backup checksum mismatch.')
                    stage = 'restore-verification'
                    verify_archive(downloaded, expected, url, schema, maintenance_url)
                    stage = 'verification-marker'
                    blob.metadata = {
                        **blob.metadata, 'restore_verified': 'true',
                        'verified_at': datetime.now(timezone.utc).isoformat(),
                    }
                    blob.patch(if_metageneration_match=blob.metageneration)
                    stage = 'retention'
                    deleted = prune_verified(bucket, prefix, now, name)
                    # No row-level hashes, personal data or credentials enter logs/Git.
                    return {
                        'status': 'ok', 'restore_verified': True,
                        'tables': len(expected), 'expired_deleted': deleted,
                        'retention_days': RETENTION_DAYS, 'environment': environment,
                    }
            finally:
                lock.execute(text('SELECT pg_advisory_unlock(hashtext(:key))'), {
                    'key': 'wildmarket-backup:' + schema,
                })
    except BackupError:
        raise
    except Exception:
        raise BackupError(f'Backup failed at {stage}; sensitive details suppressed.') from None
    finally:
        engine.dispose()
