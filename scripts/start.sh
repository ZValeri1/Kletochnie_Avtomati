#!/usr/bin/env sh
cd "$(dirname "$0")/.." || exit 1
if [ -f .venv/bin/activate ]; then
    . .venv/bin/activate
else
    . .venv/Scripts/activate
fi
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
