#!/usr/bin/env bash
# Plan B puller. Reads Surge console events via HTTP API, finds [YTC] lines,
# reassembles base64 chunks per request id, decodes to ~/surge/captures-redacted/<id>_<ep>_<bytes>.bin.
set -uo pipefail
API="http://127.0.0.1:1132"
KEY="X-Key: 1132"
OUT="$HOME/surge/captures-redacted"
mkdir -p "$OUT"

echo ">>> Pulling Surge events (this gets the full console buffer)…"
EVENTS=$(curl -sS --max-time 10 -H "$KEY" "$API/v1/events")
if [ -z "$EVENTS" ]; then
  echo "    Surge HTTP API didn't respond on $API. Is it on?"
  exit 1
fi

echo "$EVENTS" | python3 - "$OUT" <<'PY'
import json, sys, base64, os, re
out_dir = sys.argv[1]
os.makedirs(out_dir, exist_ok=True)
data = json.load(sys.stdin)
events = data.get("events", data) if isinstance(data, dict) else data

line_re = re.compile(
    r"\[YTC\]\s+id=(?P<id>\S+)\s+ep=(?P<ep>\S+)\s+idx=(?P<i>\d+)/(?P<n>\d+)\s+len=(?P<len>\d+)\s+data=(?P<data>\S+)"
)

# bucket: id -> {ep, total_bytes, chunks: {idx: data}}
buckets = {}
ytc_lines = 0
for e in events:
    msg = ""
    if isinstance(e, dict):
        msg = e.get("content") or e.get("message") or ""
    elif isinstance(e, str):
        msg = e
    if "[YTC]" not in msg:
        continue
    ytc_lines += 1
    m = line_re.search(msg)
    if not m:
        continue
    rid = m.group("id")
    b = buckets.setdefault(rid, {
        "ep": m.group("ep"),
        "len": int(m.group("len")),
        "n": int(m.group("n")),
        "chunks": {},
    })
    b["chunks"][int(m.group("i"))] = m.group("data")

print(f"  parsed {ytc_lines} [YTC] line(s) from console buffer")
print(f"  found {len(buckets)} unique capture session(s)")

written = 0
for rid, b in buckets.items():
    if len(b["chunks"]) != b["n"]:
        print(f"   - id={rid} INCOMPLETE ({len(b['chunks'])}/{b['n']} chunks); skipping")
        continue
    pieces = [b["chunks"][i] for i in sorted(b["chunks"])]
    b64 = "".join(pieces)
    raw = base64.b64decode(b64)
    fname = f"{rid}_{b['ep']}_{b['len']}.bin"
    path = os.path.join(out_dir, fname)
    with open(path, "wb") as f:
        f.write(raw)
    print(f"   - wrote {path} ({len(raw)} bytes; declared {b['len']})")
    written += 1

print(f"\n>>> Done. {written} file(s) reassembled under {out_dir}/")
PY
