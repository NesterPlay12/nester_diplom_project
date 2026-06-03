---
name: Flask + pnpm workspace coexistence
description: Как запускать Flask-приложение рядом с Node.js монорепой без конфликтов переменных окружения и портов
---

**Правило:** `DATABASE_URL` в Replit окружении занята Node.js/PostgreSQL стеком. Flask-приложение должно использовать `FLASK_DATABASE_URL` или `MYSQL_URL`.

**Почему:** При попытке Flask прочитать `DATABASE_URL` получает PostgreSQL URL, но psycopg2 не установлен — ModuleNotFoundError.

**Как применять:** Конфигурация Flask читает `FLASK_DATABASE_URL` → `MYSQL_URL` → SQLite fallback. Никогда не читать `DATABASE_URL` в Flask-конфиге.

**Порты:** api-server на 8080 (внутри, проксируется как /api), Flask на 8000 (webview workflow).
