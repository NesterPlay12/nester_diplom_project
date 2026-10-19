"""Real development backup/restore; prints no records, hashes or credentials."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text
from app.config import _get_db_url
from app.services.database_transfer import require_development
from app.services.postgres_backups import BackupError, run_backup, schema_fingerprints


def main():
    require_development()
    schema = os.environ.get('FLASK_DATABASE_SCHEMA', 'wildmarket')
    url = _get_db_url()
    engine = create_engine(url, hide_parameters=True)
    try:
        def state():
            with engine.connect() as connection:
                connection.exec_driver_sql("SET LOCAL TIME ZONE 'UTC'")
                tables = schema_fingerprints(connection, schema)
                databases = set(connection.execute(text(
                    "SELECT datname FROM pg_database "
                    "WHERE starts_with(datname, 'wm_backup_verify_')"
                )).scalars())
                return tables, databases
        before = state()
        result = run_backup(
            url, schema, 'development',
            maintenance_url=os.environ.get('WILDMARKET_RESTORE_DATABASE_URL'),
        )
        after = state()
        if before != after:
            raise BackupError('Source changed during smoke check or verification database was not cleaned up.')
        print(json.dumps({**result, 'source_unchanged': True, 'temporary_database_removed': True}))
    finally:
        engine.dispose()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({
            'status': 'failed',
            'message': str(error) if isinstance(error, BackupError) else 'Backup smoke check failed.',
        }), file=sys.stderr)
        sys.exit(1)
