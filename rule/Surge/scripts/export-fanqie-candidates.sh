#!/usr/bin/env bash
# Export Fanqie Novel traffic from iOS Surge into reviewable rule candidates.
#
# Default mode reads recent requests from the remote iPhone Surge controller.
# Pass --input FILE to re-process a previously saved dump request JSON.
set -euo pipefail
if [[ $- == *x* ]]; then
  set +x
fi
umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
DEFAULT_PROFILE="${HOME}/Library/Mobile Documents/iCloud~com~nssurge~inc/Documents/DMIT.conf"

PROFILE="${SURGE_IOS_PROFILE:-${SURGE_PROFILE:-$DEFAULT_PROFILE}}"
REMOTE_HOST="${SURGE_REMOTE_HOST:-}"
REMOTE_PORT="${SURGE_REMOTE_PORT:-1132}"
OUT_DIR="${OUT_DIR:-$ROOT_DIR/reports/fanqie}"
HTTP_CA="${SURGE_HTTP_CA:-}"
HTTP_INSECURE="${SURGE_HTTP_INSECURE:-0}"
INPUT_JSON=""
KEEP_RAW=0

usage() {
  cat <<'USAGE'
Usage:
  rule/Surge/scripts/export-fanqie-candidates.sh [options]

Options:
  -i, --input FILE      Re-process an existing Surge dump request JSON.
  -o, --out-dir DIR     Output directory. Default: reports/fanqie
      --keep-raw        Retain a mode-0600 copy of the raw request JSON.
      --host HOST       Remote Surge host. Required without --input.
      --port PORT       Remote Surge HTTPS HTTP API port. Default: 1132
      --profile FILE    Surge profile used to read the HTTP API key.
  -h, --help            Show this help.

Environment:
  SURGE_PROFILE         DMIT.conf path override.
  SURGE_IOS_PROFILE     iOS profile override; takes precedence over SURGE_PROFILE.
  SURGE_REMOTE_HOST     Remote host override.
  SURGE_REMOTE_PORT     Remote HTTPS HTTP API port override.
  SURGE_HTTP_CA         CA bundle used to verify the Surge HTTPS certificate.
  SURGE_HTTP_INSECURE   Set to 1 only for a temporary unverified diagnostic.
  OUT_DIR               Output directory override.

Outputs:
  *.summary.tsv         Domain/rule/policy aggregation.
  *.candidate-rules.list
                        Only high-confidence new reject candidates.
  *.report.md           Human review report.

Raw requests are not copied or retained by default. Use --keep-raw only when a
review requires them, and delete the retained file as soon as it is no longer
needed.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    -i|--input)
      INPUT_JSON="${2:-}"
      shift 2
      ;;
    -o|--out-dir)
      OUT_DIR="${2:-}"
      shift 2
      ;;
    --keep-raw)
      KEEP_RAW=1
      shift
      ;;
    --host)
      REMOTE_HOST="${2:-}"
      shift 2
      ;;
    --port)
      REMOTE_PORT="${2:-}"
      shift 2
      ;;
    --profile)
      PROFILE="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$HTTP_INSECURE" != "0" && "$HTTP_INSECURE" != "1" ]]; then
  echo "SURGE_HTTP_INSECURE must be 0 or 1." >&2
  exit 2
fi
if [[ "$HTTP_CA" == *$'\n'* || "$HTTP_CA" == *$'\r'* ]]; then
  echo "SURGE_HTTP_CA must not contain a newline." >&2
  exit 2
fi

mkdir -p "$OUT_DIR"
chmod 700 "$OUT_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)-$$"
SUMMARY_TSV="$OUT_DIR/$STAMP.summary.tsv"
CANDIDATE_LIST="$OUT_DIR/$STAMP.candidate-rules.list"
REPORT_MD="$OUT_DIR/$STAMP.report.md"
RAW_JSON=""
RAW_OUTPUT=""
TEMP_RAW=""
SOURCE_LABEL=""

cleanup() {
  if [[ -n "$TEMP_RAW" ]]; then
    rm -f -- "$TEMP_RAW"
  fi
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

curl_config() {
  local key="$1"
  local escaped_key escaped_ca
  escaped_key="${key//\\/\\\\}"
  escaped_key="${escaped_key//\"/\\\"}"
  printf 'header = "X-Key: %s"\n' "$escaped_key"
  printf 'silent\nshow-error\nfail\nconnect-timeout = 5\nmax-time = 30\n'
  if [[ "$HTTP_INSECURE" == "1" ]]; then
    printf 'insecure\n'
  elif [[ -n "$HTTP_CA" ]]; then
    escaped_ca="${HTTP_CA//\\/\\\\}"
    escaped_ca="${escaped_ca//\"/\\\"}"
    printf 'cacert = "%s"\n' "$escaped_ca"
  fi
}

valid_host() {
  [[ "$1" =~ ^[-A-Za-z0-9._:]+$ || "$1" =~ ^\[[0-9A-Fa-f:]+\]$ ]]
}

valid_port() {
  [[ "$1" =~ ^[0-9]+$ ]] && ((10#$1 >= 1 && 10#$1 <= 65535))
}

if [ -n "$INPUT_JSON" ]; then
  if [ ! -f "$INPUT_JSON" ]; then
    echo "Input JSON not found: $INPUT_JSON" >&2
    exit 1
  fi
  RAW_JSON="$INPUT_JSON"
  SOURCE_LABEL="user-provided input (not copied)"
  if [[ $KEEP_RAW -eq 1 ]]; then
    RAW_OUTPUT="$OUT_DIR/$STAMP.requests.json"
    cp "$INPUT_JSON" "$RAW_OUTPUT"
    chmod 600 "$RAW_OUTPUT"
    RAW_JSON="$RAW_OUTPUT"
    SOURCE_LABEL="retained raw capture (see raw_json output)"
  fi
else
  if [ -z "$REMOTE_HOST" ]; then
    echo "Remote Surge host is required. Set SURGE_REMOTE_HOST or pass --host." >&2
    exit 1
  fi
  if ! valid_host "$REMOTE_HOST" || ! valid_port "$REMOTE_PORT"; then
    echo "Remote Surge host or port is invalid." >&2
    exit 2
  fi
  if [ ! -f "$PROFILE" ]; then
    echo "Surge profile not found: $PROFILE" >&2
    exit 1
  fi
  HTTP_KEY="$(sed -nE 's/^http-api[[:space:]]*=[[:space:]]*([^@]+)@.*/\1/p' "$PROFILE" | head -1 | tr -d '\r')"
  if [ -z "$HTTP_KEY" ]; then
    echo "Cannot read http-api from profile." >&2
    exit 1
  fi
  if [[ -n "$HTTP_CA" && ! -r "$HTTP_CA" && "$HTTP_INSECURE" != "1" ]]; then
    echo "SURGE_HTTP_CA is not readable." >&2
    exit 1
  fi
  TEMP_RAW="$(mktemp "${TMPDIR:-/tmp}/surge-fanqie.requests.XXXXXX")"
  chmod 600 "$TEMP_RAW"
  RAW_JSON="$TEMP_RAW"
  SOURCE_LABEL="temporary live capture (deleted after export)"
  curl_config "$HTTP_KEY" |
    curl -q --noproxy '*' --config - "https://${REMOTE_HOST}:${REMOTE_PORT}/v1/requests/recent" > "$RAW_JSON"
  if [[ $KEEP_RAW -eq 1 ]]; then
    RAW_OUTPUT="$OUT_DIR/$STAMP.requests.json"
    mv "$TEMP_RAW" "$RAW_OUTPUT"
    TEMP_RAW=""
    RAW_JSON="$RAW_OUTPUT"
    SOURCE_LABEL="retained raw capture (see raw_json output)"
  fi
fi

python3 - "$ROOT_DIR" "$RAW_JSON" "$SUMMARY_TSV" "$CANDIDATE_LIST" "$REPORT_MD" "$SOURCE_LABEL" <<'PY'
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(sys.argv[1]) / "rule" / "Surge" / "scripts"))
from surge_candidate_common import (  # noqa: E402
    as_text,
    base_domain,
    extract_host,
    first_time,
    is_rejected,
    load_existing_rules,
    load_requests,
    matches_existing,
)

root = Path(sys.argv[1])
raw_path = Path(sys.argv[2])
summary_path = Path(sys.argv[3])
candidate_path = Path(sys.argv[4])
report_path = Path(sys.argv[5])
source_label = sys.argv[6]

rules_paths = [root / "rewrite" / "Surge" / "basic-adblock.sgmodule"]

TOPIC_RE = re.compile(
    r"fqnovel|fanqie|snssdk|zijieapi|byteimg|bdurl|applog|bytegecko|pangolin|"
    r"pglstat|pangle|ad-sign|ad[.]oceanengine|timon|vcs|mon[0-9]+-misc|"
    r"douyinpic|douyin[.]com|ecombdapi|ecombdimg|ydycdn|manlaxycloud",
    re.I,
)
HIGH_CONF_RE = re.compile(
    r"(^|[.-])(ads?[0-9]*|ad-sign|applog|rtlog|timon|vcs|pangolin|pglstat|iegadp|"
    r"ugsdk|bdurl|toutiaocloud|mon[0-9]+-misc)([.-]|$)",
    re.I,
)
RESOURCE_RE = re.compile(
    r"bytegecko|douyinpic|ecombdapi|ecombdimg|ydycdn|manlaxycloud|fqnovelpic|fqnovelvod",
    re.I,
)

rows = load_requests(raw_path)
existing_rules = load_existing_rules(rules_paths)

by_host = {}
times = []
for row in rows:
    host = extract_host(row)
    if not host:
        continue
    host_l = host.lower()
    text = " ".join(
        [
            host_l,
            as_text(row.get("URL")),
            as_text(row.get("remoteHost")),
            as_text(row.get("rule")),
            as_text(row.get("policyName")),
            as_text(row.get("notes")),
        ]
    )
    topic = bool(TOPIC_RE.search(text))
    rejected = is_rejected(row)
    rule = as_text(row.get("rule")) or "-"
    policy = as_text(row.get("policyName")) or "-"
    status = as_text(row.get("status")) or "-"
    t = first_time(row)
    if t:
        times.append(t)

    item = by_host.setdefault(
        host_l,
        {
            "host": host_l,
            "count": 0,
            "rejected": 0,
            "direct": 0,
            "topic": False,
            "rules": Counter(),
            "policies": Counter(),
            "statuses": Counter(),
            "first": "",
            "last": "",
        },
    )
    item["count"] += 1
    item["rejected"] += int(rejected)
    item["direct"] += int(not rejected)
    item["topic"] = item["topic"] or topic
    item["rules"][rule] += 1
    item["policies"][policy] += 1
    item["statuses"][status] += 1
    if t and (not item["first"] or t < item["first"]):
        item["first"] = t
    if t and (not item["last"] or t > item["last"]):
        item["last"] = t


def top(counter):
    if not counter:
        return "-"
    return "; ".join(f"{k}:{v}" for k, v in counter.most_common(3))


def classify(item):
    host = item["host"]
    if matches_existing(host, existing_rules):
        return "existing-rule"
    if item["rejected"] > 0:
        return "rejected-by-other"
    if HIGH_CONF_RE.search(host):
        return "candidate-reject"
    if item["topic"] or RESOURCE_RE.search(host):
        return "observe"
    return "ignore"


for item in by_host.values():
    item["class"] = classify(item)

items = sorted(
    by_host.values(),
    key=lambda x: (
        {"candidate-reject": 0, "observe": 1, "existing-rule": 2, "rejected-by-other": 3, "ignore": 4}.get(x["class"], 9),
        -x["count"],
        x["host"],
    ),
)

with summary_path.open("w", encoding="utf-8") as f:
    f.write("class\thost\tbase_domain\tcount\trejected\tdirect\trules\tpolicies\tstatuses\tfirst\tlast\n")
    for item in items:
        f.write(
            "\t".join(
                [
                    item["class"],
                    item["host"],
                    base_domain(item["host"]),
                    str(item["count"]),
                    str(item["rejected"]),
                    str(item["direct"]),
                    top(item["rules"]),
                    top(item["policies"]),
                    top(item["statuses"]),
                    item["first"],
                    item["last"],
                ]
            )
            + "\n"
        )

candidates = [item["host"] for item in items if item["class"] == "candidate-reject"]
with candidate_path.open("w", encoding="utf-8") as f:
    f.write("# Review before adding to the Basic AdBlock or an app-specific module\n")
    f.write("# Generated from: " + source_label + "\n")
    for host in candidates:
        f.write(f"DOMAIN,{host},REJECT\n")

classes = Counter(item["class"] for item in items)
time_range = ""
if times:
    time_range = f"{min(times)} -> {max(times)}"
else:
    time_range = "unknown"

def table_lines(selected, limit=30):
    lines = ["| class | host | count | rejected | policy | rule | window |", "| --- | --- | ---: | ---: | --- | --- | --- |"]
    for item in selected[:limit]:
        window = item["first"] if item["first"] == item["last"] else f"{item['first']} - {item['last']}"
        lines.append(
            f"| {item['class']} | `{item['host']}` | {item['count']} | {item['rejected']} | "
            f"{top(item['policies'])} | {top(item['rules'])} | {window or '-'} |"
        )
    if len(selected) > limit:
        lines.append(f"| ... | {len(selected) - limit} more | | | | | |")
    return "\n".join(lines)

topic_items = [item for item in items if item["topic"] or item["class"] != "ignore"]
candidate_items = [item for item in items if item["class"] == "candidate-reject"]
observe_items = [item for item in items if item["class"] == "observe"]
existing_items = [item for item in items if item["class"] == "existing-rule"]

report = [
    "# Fanqie Surge Candidate Report",
    "",
    f"- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    f"- Source: {source_label}",
    f"- Requests: {len(rows)}",
    f"- Unique hosts: {len(items)}",
    f"- Time range: {time_range}",
    f"- Existing rules: {classes['existing-rule']}",
    f"- New reject candidates: {classes['candidate-reject']}",
    f"- Observe-only hosts: {classes['observe']}",
    "",
    "## Candidate Rules",
    "",
]

if candidate_items:
    report.append(table_lines(candidate_items))
else:
    report.append("No new high-confidence reject candidates in this dump.")

report.extend(["", "## Observe Only", ""])
if observe_items:
    report.append(table_lines(observe_items))
else:
    report.append("No observe-only topic hosts in this dump.")

report.extend(["", "## Existing Rules Seen", ""])
if existing_items:
    report.append(table_lines(existing_items))
else:
    report.append("No existing Fanqie rules appeared in this dump.")

report.extend(
    [
        "",
        "## Files",
        "",
        f"- Summary TSV: `{summary_path}`",
        f"- Candidate rules: `{candidate_path}`",
        "",
        "Review `candidate-rules.list` manually before adding any line to the Basic AdBlock or an app-specific module.",
    ]
)

report_path.write_text("\n".join(report) + "\n", encoding="utf-8")

print(f"requests={len(rows)}")
print(f"unique_hosts={len(items)}")
print(f"time_range={time_range}")
print(f"candidate_reject={classes['candidate-reject']}")
print(f"observe={classes['observe']}")
print(f"existing_rule={classes['existing-rule']}")
print(f"summary_tsv={summary_path}")
print(f"candidate_rules={candidate_path}")
print(f"report_md={report_path}")
PY

chmod 600 "$SUMMARY_TSV" "$CANDIDATE_LIST" "$REPORT_MD"
if [[ -n "$RAW_OUTPUT" ]]; then
  printf 'raw_json=%s\n' "$RAW_OUTPUT"
elif [[ -n "$INPUT_JSON" ]]; then
  printf 'raw_json=input-not-copied\n'
else
  printf 'raw_json=not-retained\n'
fi
