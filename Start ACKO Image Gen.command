#!/bin/bash
# Double-click this file to start the ACKO Image Generator.
# It starts the local proxy (restarting it if it's stuck/unresponsive) and
# opens the tool in your browser.

cd "$(dirname "$0")"

PORT=3458
URL="http://localhost:$PORT/generate.html"

is_listening() {
  lsof -i ":$PORT" -sTCP:LISTEN >/dev/null 2>&1
}

is_healthy() {
  # A real HTTP check, not just "is the port occupied" — a crashed proxy can still
  # hold the port open while failing every request.
  code=$(curl -s -o /dev/null -m 3 -w "%{http_code}" "$URL" 2>/dev/null)
  [ "$code" = "200" ]
}

start_proxy() {
  echo "Starting proxy..."
  nohup python3 proxy.py > /tmp/acko_proxy.log 2>&1 &
}

# Poll for up to ~8s instead of checking once immediately — startup (DB init,
# admin bootstrap) can take a beat longer than a single fixed sleep.
wait_for_healthy() {
  for i in 1 2 3 4 5 6 7 8; do
    if is_healthy; then return 0; fi
    sleep 1
  done
  return 1
}

if is_listening && is_healthy; then
  echo "Proxy already running and healthy on port $PORT."
elif is_listening; then
  echo "Something's listening on port $PORT but not responding — restarting it."
  lsof -ti ":$PORT" | xargs kill -9 2>/dev/null
  sleep 1
  start_proxy
else
  start_proxy
fi

if wait_for_healthy; then
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
