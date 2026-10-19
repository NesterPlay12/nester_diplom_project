#!/usr/bin/env bash
# One invocation per scheduled run; do not loop or start this from Gunicorn.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
umask 077
if [[ "${APP_ENV:-}" != development && "${APP_ENV:-}" != staging && "${APP_ENV:-}" != production ]]; then
    echo '{"status":"failed","message":"Set APP_ENV explicitly for the scheduled backup."}' >&2
    exit 1
fi
for tool in python pg_dump pg_restore; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo '{"status":"failed","message":"Required backup runtime tool is missing."}' >&2
        exit 1
    fi
done
exec python flask-app/backup.py
