#!/usr/bin/env bash
# Watch youtubei / googlevideo traffic through Surge in real time.
#
# Run this BEFORE you start a YouTube video (Mac Chrome OR iPhone YouTube App).
# It polls Surge HTTP API every 2 seconds and prints any new request that
# touches youtubei.googleapis.com or googlevideo.com.
set -uo pipefail

API="http://127.0.0.1:1132"
KEY="X-Key: 1132"

echo ">>> Reloading Surge profile so newest sgmodule is in use…"
curl -sS --max-time 5 -H "$KEY" -X POST "$API/v1/profiles/reload" >/dev/null
echo "    reloaded."
echo

echo ">>> Re-listing scripts after reload (look for the latest pattern)…"
curl -sS --max-time 5 -H "$KEY" "$API/v1/scripting" | python3 -m json.tool 2>/dev/null | head -30
echo

echo ">>> Watching youtubei + googlevideo requests. Open YouTube on Mac or iPhone now."
echo ">>> Ctrl+C to stop."
echo

LAST_TS=""
while true; do
  curl -sS --max-time 5 -H "$KEY" "$API/v1/requests/recent" 2>/dev/null \
    | LAST="$LAST_TS" python3 -c '
import json, sys, os, time
last = os.environ.get("LAST", "")
data = json.load(sys.stdin)
items = data.get("requests", data) if isinstance(data, dict) else data
new_last = last
for r in items:
    url = r.get("URL") or r.get("url") or ""
    if not ("youtubei.googleapis.com" in url or "googlevideo.com" in url):
        continue
    rid = str(r.get("id", "")) + "|" + str(r.get("startDate", r.get("timestamp", "")))
    if rid <= last:
        continue
    method = r.get("method", "?")
    status = r.get("status", r.get("statusCode", "?"))
    rule = r.get("rule", "")
    notes = r.get("notes", []) or []
    short = url.split("?")[0]
    print(f"  {method:5} {status:>3}  {short}")
    for n in notes:
        if isinstance(n, str) and ("script" in n.lower() or "matched" in n.lower() or "mitm" in n.lower()):
            print(f"       · {n}")
    if rid > new_last:
        new_last = rid
sys.stderr.write(new_last)
' 2>/tmp/.yt_last
  NL=$(cat /tmp/.yt_last 2>/dev/null)
  if [ -n "$NL" ]; then LAST_TS="$NL"; fi
  sleep 2
done
