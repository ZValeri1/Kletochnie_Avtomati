#!/usr/bin/env sh
. .venv/Scripts/activate
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
