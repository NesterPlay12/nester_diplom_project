#!/bin/bash
# Переходим в директорию скрипта (flask-app/)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo ">>> Проверяем базу данных..."
python seed.py

echo ">>> Запускаем продакшн-сервер..."
exec gunicorn -w 2 -b "0.0.0.0:${PORT:-8000}" "run:app"
