#!/bin/bash
echo ">>> Применяем миграции и заполняем БД..."
python seed.py
echo ">>> Запускаем сервер..."
gunicorn -w 2 -b 0.0.0.0:$PORT "run:app"
