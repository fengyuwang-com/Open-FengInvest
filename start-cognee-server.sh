#!/usr/bin/env bash
# start-cognee-server.sh — Start Cognee API server with PostgreSQL backend
# Uses the Python wrapper (tools/start_cognee.py) which sets env vars before import.
# Usage: bash start-cognee-server.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "[COGNEE] Starting server (first startup ~4 min import)"
cd "$PROJECT_DIR"
exec python tools/start_cognee.py
