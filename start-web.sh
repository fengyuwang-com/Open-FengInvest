#!/bin/bash
cd "$(dirname "$0")/fengweb"

# Check if port 23456 is in use
if lsof -i:23456 -P -n 2>/dev/null | grep LISTEN; then
  echo "[WARN] Port 23456 is in use. Killing old process..."
  lsof -ti:23456 -P -n 2>/dev/null | xargs kill -9 2>/dev/null
  sleep 2
fi

echo "Building..."
npx tsc
echo "Starting FengWeb on http://localhost:23456"
node dist/index.js
if [ $? -ne 0 ]; then
  echo "[ERROR] Failed to start on port 23456."
  echo "Run: lsof -i:23456 to check what's using it."
  exit 1
fi
