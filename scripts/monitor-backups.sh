#!/usr/bin/env bash
# A separate hourly Scheduled deployment, not part of backup-postgres.sh.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
umask 077
exec python flask-app/monitor_backups.py
