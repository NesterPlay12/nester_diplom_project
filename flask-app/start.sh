#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

export APP_ENV="${APP_ENV:-production}"
export FLASK_ENV="${FLASK_ENV:-production}"

if [ -z "${SESSION_SECRET:-}" ]; then
    echo "ERROR: SESSION_SECRET must be configured before starting the application." >&2
    exit 1
fi

if [ "${APP_ENV}" = "production" ] || [ "${APP_ENV}" = "staging" ]; then
    if [ -z "${FLASK_DATABASE_URL:-}" ] && [ "${FLASK_DATABASE_SOURCE:-}" != "replit" ]; then
        echo "ERROR: configure FLASK_DATABASE_URL or FLASK_DATABASE_SOURCE=replit." >&2
        exit 1
    fi
    database_url="${FLASK_DATABASE_URL:-}"
    if [ -n "$database_url" ] && [[ "$database_url" != postgres://* && "$database_url" != postgresql://* && "$database_url" != postgresql+psycopg2://* ]]; then
        echo "ERROR: WildMarket requires PostgreSQL." >&2
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
