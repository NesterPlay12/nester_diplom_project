#!/bin/bash
# Переходим в директорию скрипта (flask-app/)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo ">>> Проверяем базу данных..."
python seed.py

echo ">>> Запускаем продакшн-сервер..."
if command -v gunicorn >/dev/null 2>&1; then
    exec gunicorn -w 2 -b "0.0.0.0:${PORT:-8000}" "run:app"
else
    echo ">>> Gunicorn недоступен, используем Flask production server..."
    export FLASK_ENV=production
    exec python run.py
fi
