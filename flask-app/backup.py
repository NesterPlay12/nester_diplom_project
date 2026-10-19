"""One-shot scheduled job. Nonzero exit triggers the scheduler's failure email."""
import json
import os
import sys


def main():
    safe_error_type = ()
    try:
        from app.config import _get_db_url
        from app.services.postgres_backups import BackupError, run_backup
        safe_error_type = BackupError
        environment = os.environ.get('APP_ENV')
        if environment not in {'development', 'staging', 'production'}:
            raise RuntimeError('APP_ENV must explicitly select the backup environment.')
        result = run_backup(
            _get_db_url(),
            schema=os.environ.get('FLASK_DATABASE_SCHEMA', 'wildmarket'),
            environment=environment,
            maintenance_url=os.environ.get('WILDMARKET_RESTORE_DATABASE_URL'),
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        # Third-party exceptions can contain passwords, SQL and full row values.
        message = str(error) if isinstance(error, safe_error_type) else 'Backup configuration or execution failed.'
        print(json.dumps({'status': 'failed', 'message': message}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
