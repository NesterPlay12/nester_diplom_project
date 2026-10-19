"""Explicit development-only, lossless SQLite -> PostgreSQL transfer.

Never called by web startup or deployment. Backup objects have no public ACL.
Current PostgreSQL backups live in postgres_backups.py, not this legacy snapshot:
they reflect the live schema and never use migration-manifest's old table list.
"""
import hashlib
import json
import os
import secrets
from pathlib import Path
import sqlite3
from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect, select, text
from werkzeug.security import generate_password_hash

from ..models import db

DEMO_EMAILS = (
    'admin@wildmarket.ru', 'moder@wildmarket.ru', 'seller1@wildmarket.ru',
    'seller2@wildmarket.ru', 'ivan@example.ru',
)


def deactivate_demo_accounts(connection):
    """Retain all rows and relationships; irreversibly disable known demo access.

    The caller owns the transaction. No passwords or account data are logged.
    Already secured records are unchanged on subsequent runs.
    """
    users = db.metadata.tables['users']
    candidates = connection.execute(select(users.c.id).where(
        db.func.lower(db.func.trim(users.c.email)).in_(DEMO_EMAILS),
        db.or_(users.c.is_active.is_not(False), users.c.has_local_password.is_not(False)),
    )).scalars().all()
    for user_id in candidates:
        connection.execute(users.update().where(users.c.id == user_id).values(
            is_active=False,
            has_local_password=False,
            password_hash=generate_password_hash(secrets.token_urlsafe(48)),
        ))
    return len(candidates)


def assert_safe_production_accounts():
    from ..models import User

    known_demo = db.func.lower(db.func.trim(User.email)).in_(DEMO_EMAILS)
    if User.query.filter(known_demo, User.is_active.is_(True)).first():
        raise RuntimeError(
            'Active demo accounts exist. Secure or deactivate them before production.'
        )
    if not User.query.filter(
        ~known_demo, User.is_active.is_(True), User.role == 'admin',
        db.or_(User.has_local_password.is_(True), db.func.length(User.google_id) > 0),
    ).first():
        raise RuntimeError(
            'An active non-demo administrator is required before production. '
            'Create one with manage.py create-admin in development.'
        )


def require_development():
    if os.environ.get('APP_ENV', 'development') != 'development':
        raise RuntimeError('This command may only modify the development database.')


def fingerprints(connection):
    result = {}
    for table in db.metadata.sorted_tables:
        rows = [
            dict(row) for row in connection.execute(
                select(table).order_by(table.c.id)
            ).mappings()
        ]
        payload = json.dumps(
            rows, sort_keys=True, ensure_ascii=False,
            default=lambda value: value.isoformat(), separators=(',', ':'),
        ).encode()
        result[table.name] = {
            'rows': len(rows), 'sha256': hashlib.sha256(payload).hexdigest(),
        }
    return result


def check_sqlite(path):
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as connection:
        if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise RuntimeError('SQLite integrity check failed.')
        if connection.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('SQLite contains broken foreign keys.')


def storage_bucket():
    from google.cloud import storage
    from google.auth import identity_pool
    credentials = identity_pool.Credentials.from_info({
        'audience': 'replit',
        'subject_token_type': 'access_token',
        'token_url': 'http://127.0.0.1:1106/token',
        'type': 'external_account',
        'credential_source': {
            'url': 'http://127.0.0.1:1106/credential',
            'format': {'type': 'json', 'subject_token_field_name': 'access_token'},
        },
    }, scopes=['https://www.googleapis.com/auth/devstorage.read_write'])
    client = storage.Client(
        credentials=credentials,
        project='',
    )
    private_path = os.environ['PRIVATE_OBJECT_DIR'].strip('/')
    bucket_name, prefix = private_path.split('/', 1)
    return client.bucket(bucket_name), prefix


def make_backup(source, directory):
    """Snapshot, upload privately, download and test actual restoration."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = directory / f'wildmarket-{stamp}.sqlite'
    with sqlite3.connect(f'file:{source}?mode=ro', uri=True) as original:
        with sqlite3.connect(backup) as copy:
            original.backup(copy)
    os.chmod(backup, 0o600)
    check_sqlite(backup)
    checksum = hashlib.sha256(backup.read_bytes()).hexdigest()
    bucket, prefix = storage_bucket()
    object_name = f'{prefix}/database-backups/{backup.name}'
    blob = bucket.blob(object_name)
    blob.upload_from_filename(str(backup), if_generation_match=0)
    restored = directory / f'restored-{backup.name}'
    blob.download_to_filename(str(restored))
    os.chmod(restored, 0o600)
    if hashlib.sha256(restored.read_bytes()).hexdigest() != checksum:
        raise RuntimeError('Downloaded backup checksum mismatch.')
    check_sqlite(restored)
    return backup, {
        'backup_object': object_name, 'backup_sha256': checksum,
        'backup_download_restore_verified': True,
    }


def copy_rows(source, target):
    expected = fingerprints(source)
    actual = fingerprints(target)
    if expected == actual:
        return expected, False
    if any(value['rows'] for value in actual.values()):
        raise RuntimeError('Target is not empty and differs from source; refusing to overwrite.')
    for table in db.metadata.sorted_tables:
        rows = list(source.execute(select(table).order_by(table.c.id)).mappings())
        # Row-by-row also preserves self-referencing category parent ordering.
        for row in rows:
            target.execute(table.insert().values(**dict(row)))
        target.execute(text(
            'SELECT setval(pg_get_serial_sequence(:table, :column), '
            'COALESCE((SELECT MAX(id) FROM "' + table.name + '"), 1), '
            'EXISTS(SELECT 1 FROM "' + table.name + '"))'
        ), {'table': table.name, 'column': 'id'})
    if fingerprints(target) != expected:
        raise RuntimeError('Field-level verification failed; transfer rolled back.')
    return expected, True


def transfer_sqlite(source, directory):
    require_development()
    if db.engine.dialect.name != 'postgresql':
        raise RuntimeError('Transfer target must be PostgreSQL.')
    source = Path(source).resolve(strict=True)
    backup, report = make_backup(source, directory)
    source_engine = create_engine(f'sqlite:///{backup}')
    try:
        source_inspector = inspect(source_engine)
        names = set(source_inspector.get_table_names()) - {'sqlite_sequence'}
        if names != set(db.metadata.tables):
            raise RuntimeError('Source has unknown or missing tables; refusing partial transfer.')
        for table in db.metadata.sorted_tables:
            if {c['name'] for c in source_inspector.get_columns(table.name)} != set(table.c.keys()):
                raise RuntimeError(f'Column mismatch in {table.name}; refusing data loss.')
        with source_engine.connect() as source_connection:
            with db.engine.begin() as target:
                # Serialize transfers and reject accidental concurrent writes.
                target.execute(text('SELECT pg_advisory_xact_lock(740345612)'))
                tables = ', '.join('"' + t.name + '"' for t in db.metadata.sorted_tables)
                target.exec_driver_sql(f'LOCK TABLE {tables} IN ACCESS EXCLUSIVE MODE')
                report['tables'], report['inserted'] = copy_rows(source_connection, target)
            # Independent restoration into an isolated PostgreSQL schema.
            with db.engine.begin() as restore:
                schema = 'restore_' + os.urandom(8).hex()
                restore.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
                restore.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
                db.metadata.create_all(restore)
                copy_rows(source_connection, restore)
                restore.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
            report['postgres_restore_verified'] = True
        report_path = Path(directory) / 'migration-report.json'
        report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
        os.chmod(report_path, 0o600)
        print(json.dumps(report, indent=2))
    finally:
        source_engine.dispose()
    return report


def restore_development(manifest_path):
    """Restore the verified private snapshot on task merge if dev PG is empty.

    Never runs during build, web startup or Publish, never overwrites live rows.
    """
    require_development()
    if db.engine.dialect.name != 'postgresql':
        raise RuntimeError('Restore target must be PostgreSQL.')
    manifest = json.loads(Path(manifest_path).read_text())
    with db.engine.connect() as connection:
        if any(value['rows'] for value in fingerprints(connection).values()):
            print('Existing PostgreSQL data retained; bootstrap restore skipped.')
            return
    directory = Path(__file__).resolve().parents[3] / 'generated-artifacts' / 'database-backups'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    downloaded = directory / 'merge-restore.sqlite'
    bucket, _ = storage_bucket()
    bucket.blob(manifest['backup_object']).download_to_filename(str(downloaded))
    os.chmod(downloaded, 0o600)
    if hashlib.sha256(downloaded.read_bytes()).hexdigest() != manifest['backup_sha256']:
        raise RuntimeError('Development restore backup checksum mismatch.')
    check_sqlite(downloaded)
    engine = create_engine(f'sqlite:///{downloaded}')
    try:
        with engine.connect() as source:
            if fingerprints(source) != manifest['tables']:
                raise RuntimeError('Development restore field fingerprints mismatch.')
            with db.engine.begin() as target:
                target.execute(text('SELECT pg_advisory_xact_lock(740345612)'))
                names = ', '.join('"' + t.name + '"' for t in db.metadata.sorted_tables)
                target.exec_driver_sql(f'LOCK TABLE {names} IN ACCESS EXCLUSIVE MODE')
                copy_rows(source, target)
                # Verify the lossless copy first, then apply the owner-approved
                # access restriction before restored records become visible.
                secured = deactivate_demo_accounts(target)
        print(
            'Development database restored and verified from private backup. '
            f'Demo accounts secured: {secured}. Confirm a real administrator before production.'
        )
    finally:
        engine.dispose()
        downloaded.unlink(missing_ok=True)
