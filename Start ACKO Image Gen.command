#!/bin/bash
# Double-click this file to start the ACKO Image Generator.
# It starts the local proxy (if not already running) and opens the tool in your browser.

cd "$(dirname "$0")"

PORT=3458
URL="http://localhost:$PORT/generate.html"

if lsof -i ":$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Proxy already running on port $PORT."
else
  echo "Starting proxy..."
  nohup python3 proxy.py > /tmp/acko_proxy.log 2>&1 &
  sleep 1
fi

if lsof -i ":$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Proxy is up. Opening $URL"
  open "$URL"
else
  echo "Failed to start the proxy. Check /tmp/acko_proxy.log for details."
  read -n 1 -s -r -p "Press any key to close this window..."
  exit 1
fi

echo ""
echo "Leave this window open while you use the tool."
echo "Close this window (or press Ctrl+C) to stop the proxy."
wait
