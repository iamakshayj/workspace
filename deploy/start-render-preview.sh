#!/bin/sh
set -eu

python -c 'import asyncio; from backend.app.database import init_database; asyncio.run(init_database())'
python -m scripts.seed_enterprise_demo

uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 &
api_pid=$!

cleanup() {
    kill "$api_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

exec nginx -g 'daemon off;'
