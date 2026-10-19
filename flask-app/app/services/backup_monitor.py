"""Independent, metadata-only backup watchdog. Never imported by web routes."""
import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import Boolean, Column, DateTime, MetaData, String, Table, select, text, update
from sqlalchemy.dialects.postgresql import insert

from .postgres_backups import BACKUP_NAME, backup_scope, identifier, storage_bucket

MAX_AGE_HOURS = 36
STORAGE_TIMEOUT = 20


def state_table(schema):
    """Operational metadata, deliberately separate from web readiness/ORM tables.

    Publishing the website must not require activating an optional watchdog.
    Initialization is explicit and offline; runtime never creates this table.
    """
    identifier(schema)
    return Table(
        'backup_monitor_states', MetaData(),
        Column('scope_key', String(64), primary_key=True),
        Column('incident_open', Boolean, nullable=False),
        Column('last_status', String(32), nullable=False),
        Column('checked_at', DateTime(timezone=True), nullable=False),
        schema=schema,
    )


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError, OverflowError):
        pass
    return None


def inspect_freshness(source_url, schema, environment, now=None):
    """List metadata only. Ignore other sources, incomplete and invalid objects.

    Use both snapshot creation time and restore completion: re-verifying an old
    dump must not make old data fresh. No blob download/reload/public URL.
    """
    scope = backup_scope(source_url, schema, environment)
    now = now or datetime.now(timezone.utc)
    latest = None
    try:
        bucket, private_prefix = storage_bucket()
        prefix = f'{private_prefix}/{scope}'
        for blob in bucket.list_blobs(
            prefix=prefix, timeout=STORAGE_TIMEOUT, retry=None,
            fields='items(name,metadata,timeCreated),nextPageToken',
        ):
            if not blob.name.startswith(prefix):
                continue
            basename = blob.name[len(prefix):]
            if not BACKUP_NAME.fullmatch(basename):
                continue
            metadata = blob.metadata or {}
            if (metadata.get('format') != 'postgresql-custom-v1'
                    or metadata.get('restore_verified') != 'true'):
                continue
            verified = _timestamp(metadata.get('verified_at'))
            try:
                snapshot = datetime.strptime(
                    basename.split('-')[0], '%Y%m%dT%H%M%S%fZ',
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            created = blob.time_created
            if (verified is None or created is None or created.tzinfo is None
                    or snapshot > now or verified > now or created > now
                    or verified < snapshot or verified < created):
                continue
            # Metadata time_created is server-controlled; filename is snapshot time.
            fresh_at = min(snapshot, created, verified)
            if latest is None or fresh_at > latest:
                latest = fresh_at
    except Exception:
        # Exceptions may include bucket names, connection URLs or credentials.
        return {'status': 'storage_error'}
    if latest is None:
        return {'status': 'missing'}
    age = now - latest
    return {
        'status': 'stale' if age > timedelta(hours=MAX_AGE_HOURS) else 'ok',
        'age_hours': round(age.total_seconds() / 3600, 2),
    }


def run_monitor(engine, source_url, schema, environment, now=None):
    """Commit a single alert latch BEFORE returning the scheduler failure.

    A durable PostgreSQL latch is independent of the object storage being
    monitored. Serializing checks prevents duplicate alerts from overlapping jobs.
    No DDL: provision the operational table using offline schema management.
    """
    scope = backup_scope(source_url, schema, environment)
    key = hashlib.sha256(scope.encode()).hexdigest()
    now = now or datetime.now(timezone.utc)
    table = state_table(schema)
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL statement_timeout = '90s'"))
        acquired = connection.execute(text(
            'SELECT pg_try_advisory_xact_lock(hashtext(:key))'
        ), {'key': 'backup-monitor:' + key}).scalar()
        if not acquired:
            return {'status': 'check_in_progress', 'alert': False}, 0
        connection.execute(insert(table).values(
            scope_key=key, incident_open=False, last_status='initial',
            checked_at=now,
        ).on_conflict_do_nothing(index_elements=['scope_key']))
        previous = connection.execute(
            select(table).where(table.c.scope_key == key).with_for_update()
        ).mappings().one()
        result = inspect_freshness(source_url, schema, environment, now)
        unhealthy = result['status'] != 'ok'
        alert = unhealthy and not previous['incident_open']
        recovered = not unhealthy and previous['incident_open']
        connection.execute(update(table).where(table.c.scope_key == key).values(
            incident_open=unhealthy, last_status=result['status'], checked_at=now,
        ))
    # Any error/rollback before this point must not pretend to have claimed an alert.
    return {**result, 'alert': alert, 'recovered': recovered}, int(alert)
