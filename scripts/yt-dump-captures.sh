#!/usr/bin/env bash
# Pull every yt_capture_* key from Surge's $persistentStore and write
# the redacted base64 -> binary file under ~/surge/captures-redacted/.
set -uo pipefail
API="http://127.0.0.1:1132"
KEY="X-Key: 1132"
OUT="$HOME/surge/captures-redacted"
mkdir -p "$OUT"

echo ">>> Listing all persistent-store keys…"
RAW=$(curl -sS --max-time 10 -H "$KEY" "$API/v1/scripting/persistent_store/list" 2>/dev/null)
if [ -z "$RAW" ]; then
  echo "    Surge HTTP API didn't return; check the API is running on 1132."
  exit 1
fi

# parse keys array
echo "$RAW" | python3 -c '
import json, sys, base64, os, subprocess
data = json.load(sys.stdin)
keys = data.get("keys", []) if isinstance(data, dict) else data
yt = [k for k in keys if isinstance(k, str) and k.startswith("yt_capture_")]
print(f"  found {len(yt)} yt_capture_* keys")
out_dir = os.path.expanduser("~/surge/captures-redacted")
for k in yt:
    print(f"   - {k}")
'

echo
echo ">>> Reading each key and writing to $OUT/<key>.bin …"
KEYS=$(echo "$RAW" | python3 -c '
import json, sys
data = json.load(sys.stdin)
keys = data.get("keys", []) if isinstance(data, dict) else data
print("\n".join(k for k in keys if isinstance(k, str) and k.startswith("yt_capture_")))
')
N=0
while IFS= read -r k; do
  [ -z "$k" ] && continue
  VAL=$(curl -sS --max-time 10 -H "$KEY" "$API/v1/scripting/persistent_store?key=$k" \
        | python3 -c 'import json,sys; print(json.load(sys.stdin).get("val","") or "")')
  if [ -n "$VAL" ]; then
    echo "$VAL" | base64 -D > "$OUT/$k.bin" 2>/dev/null && \
      echo "    wrote $OUT/$k.bin ($(stat -f%z "$OUT/$k.bin") bytes)"
    N=$((N+1))
  fi
done <<< "$KEYS"

echo
echo ">>> Done. $N file(s) saved under $OUT/"
echo ">>> These files were token-redacted in Surge BEFORE saving."
