#!/usr/bin/env bash
# Quick health-check of Surge Mac via HTTP API.
# Confirms: profile loaded, the YouTube Self Enhance script is registered,
# and recent youtubei requests show up in the activity log.
set -uo pipefail

API="http://127.0.0.1:1132"
KEY="X-Key: 1132"

echo ">>> 1) Profile name + version"
curl -sS --max-time 5 -H "$KEY" "$API/v1/profile/current" | head -40
echo
echo

echo ">>> 2) Active scripts (look for youtube.self.response)"
curl -sS --max-time 5 -H "$KEY" "$API/v1/scripting" | head -200
echo
echo

echo ">>> 3) Last 50 requests filtered to youtubei (so you can see hits)"
curl -sS --max-time 5 -H "$KEY" "$API/v1/requests/recent" \
  | python3 -c '
import json, sys
data = json.load(sys.stdin)
items = data.get("requests", data) if isinstance(data, dict) else data
hits = []
for r in items:
    url = r.get("URL") or r.get("url") or ""
    if "youtubei.googleapis.com" in url or "googlevideo.com" in url:
        hits.append(r)
print(f"  total youtubei/googlevideo requests in buffer: {len(hits)}")
for r in hits[:20]:
    url = r.get("URL") or r.get("url")
    status = r.get("status") or r.get("statusCode")
    method = r.get("method")
    rule = r.get("rule")
    notes = r.get("notes") or []
    print(f"   - {method} {status} {url}")
    if notes:
        for n in notes[:5]:
            print(f"       note: {n}")
'
echo

echo ">>> 4) Trigger a script test (dry-run that the script loads)"
curl -sS --max-time 10 -H "$KEY" -H "Content-Type: application/json" \
  -X POST "$API/v1/scripting/evaluate" \
  -d '{"script_text":"$done({body: \"ok\"});","mock_type":"http-response","timeout":5}' | head -40
echo
