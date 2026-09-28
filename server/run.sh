#!/usr/bin/env bash
# Start the Ledger server so an iPhone can reach it, and print the URLs to paste
# into the app's Settings → Agent server.
#
# --host '::' with --reload listens on IPv4 AND IPv6 (one dual-stack socket). With
# --host 0.0.0.0 (IPv4 only) an iPhone that resolves the Mac's .local name over IPv6 (e.g. over the USB cable) gets
# "Could not connect to the server" (-1004).
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8000}"

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $PORT is already in use by:"
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN
  echo "Stop that server first (Ctrl+C in its terminal, or: kill \$(lsof -tiTCP:$PORT -sTCP:LISTEN))."
  exit 1
fi

echo "Paste one of these into the iOS app → Settings → Agent server:"
echo "  ws://$(scutil --get LocalHostName).local:$PORT/ws"
for ifc in $(ifconfig -l); do
  ip=$(ipconfig getifaddr "$ifc" 2>/dev/null || true)
  [ -n "$ip" ] && echo "  ws://$ip:$PORT/ws    ($ifc)"
done
echo "  ws://localhost:$PORT/ws    (Simulator only)"
echo

exec .venv/bin/uvicorn app.main:app --host '::' --port "$PORT" --reload
