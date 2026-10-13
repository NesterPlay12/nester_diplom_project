#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

export APP_ENV="${APP_ENV:-production}"
export FLASK_ENV="${FLASK_ENV:-production}"

if [ -z "${SESSION_SECRET:-}" ]; then
    echo "ERROR: SESSION_SECRET must be configured before starting the application." >&2
    exit 1
fi

if [ "${APP_ENV}" = "production" ] || [ "${APP_ENV}" = "staging" ]; then
    if [ -z "${FLASK_DATABASE_URL:-}${MYSQL_URL:-}${MYSQL_HOST:-}" ]; then
        echo "ERROR: configure FLASK_DATABASE_URL or MYSQL_URL for a persistent production database." >&2
        exit 1
    fi
    database_url="${FLASK_DATABASE_URL:-${MYSQL_URL:-}}"
    if [[ "${database_url,,}" == sqlite:* ]]; then
        echo "ERROR: SQLite is not supported for production; configure a persistent server database." >&2
        exit 1
    fi
fi

if ! command -v gunicorn >/dev/null 2>&1; then
    echo "ERROR: Gunicorn is required; install project dependencies before starting." >&2
    exit 1
fi

exec gunicorn \
    --config gunicorn.conf.py \
    --bind "0.0.0.0:${PORT:-8000}" \
    "run:app"
