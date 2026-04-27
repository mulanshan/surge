#!/usr/bin/env bash
# Diagnose why yt.capture.redacted produced 0 samples.
set -uo pipefail
API="http://127.0.0.1:1132"
KEY="X-Key: 1132"

echo ">>> 1) Reload Surge profile"
curl -sS --max-time 5 -H "$KEY" -X POST "$API/v1/profiles/reload" >/dev/null
echo "    reloaded."
echo

echo ">>> 2) List ALL active scripts"
curl -sS --max-time 5 -H "$KEY" "$API/v1/scripting" | python3 -m json.tool
echo

echo ">>> 3) List persistent-store keys"
curl -sS --max-time 5 -H "$KEY" "$API/v1/scripting/persistent_store/list" | python3 -m json.tool
echo

echo ">>> 4) Recent youtubei + iOS App requests in buffer"
curl -sS --max-time 5 -H "$KEY" "$API/v1/requests/recent" | python3 -c '
import json, sys
data = json.load(sys.stdin)
items = data.get("requests", data) if isinstance(data, dict) else data
hits = [r for r in items
        if "youtubei.googleapis.com" in (r.get("URL") or r.get("url") or "")
        and ("get_watch" in (r.get("URL") or r.get("url") or "")
             or "/player" in (r.get("URL") or r.get("url") or ""))]
print(f"  {len(hits)} matching request(s) (get_watch / player) in buffer")
for r in hits[:10]:
    url = r.get("URL") or r.get("url")
    notes = r.get("notes", []) or []
    print(f"   - {url}")
    for n in notes:
        if isinstance(n, str) and ("script" in n.lower() or "modified" in n.lower()):
            print(f"       {n}")
'
