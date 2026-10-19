"""Hourly watchdog: one nonzero exit per continuous backup/storage incident."""
import json
import os
import sys


def main():
    engine = None
    try:
        from sqlalchemy import create_engine
        from app.config import _get_db_url
        from app.services.backup_monitor import run_monitor
        source_url = _get_db_url()
        engine = create_engine(
            source_url, hide_parameters=True, pool_pre_ping=True,
            connect_args={'connect_timeout': 10},
        )
        result, code = run_monitor(
            engine, source_url,
            os.environ.get('FLASK_DATABASE_SCHEMA', 'wildmarket'),
            os.environ.get('APP_ENV'),
        )
        print(json.dumps(result, sort_keys=True), flush=True)
        return code
    except Exception:
        # Do not flood the owner when the durable latch itself is unavailable.
        # This is NOT healthy: inspect this status during activation/operations.
        print(json.dumps({
            'status': 'monitor_unavailable',
            'alert': False,
            'message': 'Check watchdog configuration and persistent state access.',
        }), file=sys.stderr, flush=True)
        return 0
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == '__main__':
    sys.exit(main())
