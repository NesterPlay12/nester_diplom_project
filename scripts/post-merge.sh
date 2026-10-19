#!/bin/bash
set -e
pnpm install --frozen-lockfile
pnpm --filter db push
uv sync --frozen
APP_ENV=development python flask-app/manage.py init-schema
APP_ENV=development python flask-app/manage.py restore-development
APP_ENV=development python flask-app/manage.py secure-demo-accounts --confirm
