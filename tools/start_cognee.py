"""start_cognee.py — Cognee API server launcher with correct env vars.

Sets environment variables BEFORE importing cognee, so the config is read
correctly. Usage:

    python tools/start_cognee.py

Runs the FastAPI+Uvicorn server at the configured host:port (default 0.0.0.0:8000).
"""

import os
import sys

# ── Set env vars before any Cognee import ──────────────────────────────
os.environ.setdefault("ENABLE_BACKEND_ACCESS_CONTROL", "false")
os.environ.setdefault("CACHING", "false")

# LLM via OpenCode Go (only allowed AI API)
os.environ.setdefault("LLM_PROVIDER", "openai")
os.environ.setdefault("LLM_MODEL", "openai/deepseek-v4-flash")
os.environ.setdefault("LLM_ENDPOINT", "https://opencode.ai/zen/go/v1")
os.environ.setdefault("LLM_API_KEY", "YOUR_DEEPSEEK_API_KEY")

# JSON instructor mode avoids forced tool_choice (Console Go doesn't support it)
os.environ.setdefault("LLM_INSTRUCTOR_MODE", "json_mode")

# Embedding via local fastembed (OpenCode Go has no embedding endpoint)
os.environ.setdefault("EMBEDDING_PROVIDER", "fastembed")
os.environ.setdefault("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
os.environ.setdefault("EMBEDDING_DIMENSIONS", "384")

os.environ.setdefault("DB_PROVIDER", "sqlite")
# Use SQLite for now — asyncpg has Windows connection-reset issues with PostgreSQL.
# To switch: DB_PROVIDER=postgres, DB_HOST=localhost, DB_PORT=5432, DB_NAME=cognee,
#            DB_USER=postgres, DB_PASSWORD=postgres
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "cognee")
os.environ.setdefault("DB_USER", "postgres")
os.environ.setdefault("DB_PASSWORD", "postgres")

os.environ.setdefault("HTTP_API_HOST", "0.0.0.0")
os.environ.setdefault("HTTP_API_PORT", "8000")

# ── Start the server ───────────────────────────────────────────────────
from cognee.api.client import start_api_server

if __name__ == "__main__":
    host = os.environ["HTTP_API_HOST"]
    port = int(os.environ["HTTP_API_PORT"])
    print(f"[COGNEE] Starting server at http://{host}:{port}", flush=True)
    sys.stdout.flush()
    start_api_server(host=host, port=port)
