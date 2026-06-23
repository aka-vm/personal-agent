#!/bin/bash
# Simple page-screenshot debug tool.
#   shot.sh <url> [outfile]   ->  prints the PNG path
#
# Brings the off-by-default Playwright browser up on demand (start if present,
# recreate via compose if it was removed). The reap cron auto-stops it after
# ~15 min, so it never lingers.
set -e
URL="${1:?usage: shot.sh <url> [outfile]}"
OUT="${2:-/tmp/shot.png}"
C=playwright-mcp-playwright-mcp-1
DIR=/home/vineet/playwright-mcp

if docker ps --format '{{.Names}}' | grep -qx "$C"; then
  :                                              # already running
elif docker ps -a --format '{{.Names}}' | grep -qx "$C"; then
  docker start "$C" >/dev/null                   # present but stopped
else
  ( cd "$DIR" && docker compose up -d ) >/dev/null   # removed -> recreate
fi

# wait until the container can exec
for i in $(seq 1 12); do docker exec "$C" true 2>/dev/null && break; sleep 1; done

docker cp "$DIR/shot.js" "$C":/tmp/shot.js >/dev/null
docker exec -e NODE_PATH=/usr/local/lib/node_modules/@playwright/mcp/node_modules \
  "$C" node /tmp/shot.js "$URL" /tmp/_shot.png >/dev/null
docker cp "$C":/tmp/_shot.png "$OUT" >/dev/null
echo "$OUT"
