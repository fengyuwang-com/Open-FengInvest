#!/bin/bash
cd "$(dirname "$0")/fengweb"

# Check if port 3000 is in use
if lsof -i:3000 -P -n 2>/dev/null | grep LISTEN; then
  echo "[WARN] Port 3000 is in use. Killing old process..."
  lsof -ti:3000 -P -n 2>/dev/null | xargs kill -9 2>/dev/null
  sleep 2
fi

echo "Building..."
npx tsc
echo "Starting FengWeb on http://localhost:3000"
node dist/index.js
if [ $? -ne 0 ]; then
  echo "[ERROR] Failed to start on port 3000."
  echo "Run: lsof -i:3000 to check what's using it."
  exit 1
fi
