#!/usr/bin/env bash
# Export CamScanner traffic from iOS Surge into reviewable rule candidates.
#
# Default mode reads recent requests from the remote iPhone Surge controller.
# Pass --input FILE to re-process a previously saved dump request JSON.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_PROFILE="/Users/mulanshan/Library/Mobile Documents/iCloud~com~nssurge~inc/Documents/DMIT.conf"
DEFAULT_SURGE_CLI="/Applications/Surge.app/Contents/Applications/surge-cli"

PROFILE="${SURGE_PROFILE:-$DEFAULT_PROFILE}"
SURGE_CLI="${SURGE_CLI:-}"
REMOTE_HOST="${SURGE_REMOTE_HOST:-192.168.50.103}"
REMOTE_PORT="${SURGE_REMOTE_PORT:-6170}"
OUT_DIR="${OUT_DIR:-$ROOT_DIR/reports/camscanner}"
INPUT_JSON=""

usage() {
  cat <<'USAGE'
Usage:
  rule/Surge/scripts/export-camscanner-candidates.sh [options]

Options:
  -i, --input FILE      Re-process an existing Surge dump request JSON.
  -o, --out-dir DIR     Output directory. Default: reports/camscanner
      --host HOST       Remote Surge host. Default: 192.168.50.103
      --port PORT       Remote Surge controller port. Default: 6170
      --profile FILE    Surge profile used to read controller password.
  -h, --help            Show this help.

Environment:
  SURGE_CLI             surge-cli path override.
  SURGE_PROFILE         DMIT.conf path override.
  SURGE_REMOTE_HOST     Remote host override.
  SURGE_REMOTE_PORT     Remote controller port override.
  OUT_DIR               Output directory override.

Outputs:
  *.requests.json       Raw request dump or a copy of --input.
  *.summary.tsv         Domain/rule/policy aggregation.
  *.candidate-rules.list
                        Only high-confidence new reject candidates.
  *.report.md           Human review report.
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

if [ -z "$SURGE_CLI" ]; then
  if command -v surge-cli >/dev/null 2>&1; then
    SURGE_CLI="$(command -v surge-cli)"
  else
    SURGE_CLI="$DEFAULT_SURGE_CLI"
  fi
fi

mkdir -p "$OUT_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)-$$"
RAW_JSON="$OUT_DIR/$STAMP.requests.json"
SUMMARY_TSV="$OUT_DIR/$STAMP.summary.tsv"
CANDIDATE_LIST="$OUT_DIR/$STAMP.candidate-rules.list"
REPORT_MD="$OUT_DIR/$STAMP.report.md"

if [ -n "$INPUT_JSON" ]; then
  if [ ! -f "$INPUT_JSON" ]; then
    echo "Input JSON not found: $INPUT_JSON" >&2
    exit 1
  fi
  cp "$INPUT_JSON" "$RAW_JSON"
else
  if [ ! -x "$SURGE_CLI" ]; then
    echo "surge-cli not found or not executable: $SURGE_CLI" >&2
    exit 1
  fi
  if [ ! -f "$PROFILE" ]; then
    echo "Surge profile not found: $PROFILE" >&2
    exit 1
  fi
  CTRL_PASS="$(sed -nE 's/^external-controller-access[[:space:]]*=[[:space:]]*([^@]+)@.*/\1/p' "$PROFILE" | head -1)"
  if [ -z "$CTRL_PASS" ]; then
    echo "Cannot read external-controller-access from profile." >&2
    exit 1
  fi
  "$SURGE_CLI" --raw --remote "${CTRL_PASS}@${REMOTE_HOST}:${REMOTE_PORT}" dump request > "$RAW_JSON"
fi

python3 - "$ROOT_DIR" "$RAW_JSON" "$SUMMARY_TSV" "$CANDIDATE_LIST" "$REPORT_MD" <<'PY'
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

root = Path(sys.argv[1])
raw_path = Path(sys.argv[2])
summary_path = Path(sys.argv[3])
candidate_path = Path(sys.argv[4])
report_path = Path(sys.argv[5])
module_path = root.parent.parent / "rewrite" / "Surge" / "camscanner-self.sgmodule"

TOPIC_RE = re.compile(
    r"camscanner|intsig|scan[-_.]?cam|camscannerapp|cs[-_.]?(ad|api|stat)|app[-_.]?static[.]camscanner|"
    r"gdt[.]qq|sdk[.]e[.]qq|apmplus[.]volces",
    re.I,
)
HIGH_CONF_RE = re.compile(
    r"(^|[.-])(ad|ads|adstat|advert|analytics|appsflyer|collect|crash|event|events|log|"
    r"measurement|monitor|stat|stats|track|tracking)([.-]|$)",
    re.I,
)
OBSERVE_RE = re.compile(
    r"intsig|camscanner|static-cdn[.]camscanner|app-static[.]camscanner|cscan|scan|gdt[.]qq|sdk[.]e[.]qq|apmplus[.]volces",
    re.I,
)
SENSITIVE_RE = re.compile(
    r"purchase|receipt|order|payment|billing|subscribe|subscription|vip|premium|property|quota|account|user|oauth",
    re.I,
)


def as_text(value):
    if value is None:
        return ""
    if isinstance(value, list):
        return " | ".join(as_text(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def load_requests(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        for key in ("recent-requests", "requests", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    if isinstance(data, list):
        return data
    raise SystemExit(f"Unsupported Surge request dump shape: {path}")


def extract_host(row):
    url = as_text(row.get("URL") or row.get("url"))
    remote = as_text(row.get("remoteHost") or row.get("remote_host"))

    match = re.search(r"\(([^)]+)\)", url)
    if match:
        return match.group(1).strip()

    if "://" in url:
        parsed = urlparse(url)
        if parsed.hostname:
            return parsed.hostname

    candidate = url or remote
    candidate = candidate.split()[0].strip()
    candidate = candidate.strip("[]")
    if not candidate:
        return ""
    if ":" in candidate and not re.match(r"^\d+\.\d+\.\d+\.\d+:", candidate):
        host, port = candidate.rsplit(":", 1)
        if port.isdigit():
            return host
    return candidate


def extract_path(row):
    url = as_text(row.get("URL") or row.get("url"))
    if "://" not in url:
        return ""
    parsed = urlparse(url)
    return parsed.path or ""


def base_domain(host):
    host = host.lower().strip(".")
    if not host:
        return ""
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", host):
        return host
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    return ".".join(parts[-2:])


def first_time(row):
    notes = row.get("notes")
    if isinstance(notes, list):
        source = " ".join(as_text(v) for v in notes)
    else:
        source = as_text(notes)
    match = re.search(r"\b(\d{2}:\d{2}:\d{2})", source)
    return match.group(1) if match else ""


def is_rejected(row):
    policy = as_text(row.get("policyName"))
    return bool(row.get("rejected") is True or policy == "REJECT")


def load_existing_rules(path):
    rules = []
    if not path.exists():
        return rules
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("[") or "=" in line:
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 2:
            continue
        if parts[0] in {"DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD"}:
            rules.append((parts[0], parts[1].lower()))
    return rules


def matches_existing(host, rules):
    for rule_type, value in rules:
        if rule_type == "DOMAIN" and host == value:
            return True
        if rule_type == "DOMAIN-SUFFIX" and (host == value or host.endswith("." + value)):
            return True
        if rule_type == "DOMAIN-KEYWORD" and value in host:
            return True
    return False


rows = load_requests(raw_path)
existing_rules = load_existing_rules(module_path)
by_host = {}
times = []

for row in rows:
    host = extract_host(row)
    if not host:
        continue
    host_l = host.lower()
    path = extract_path(row)
    topic_text = " ".join(
        [
            host_l,
            path,
            as_text(row.get("URL")),
            as_text(row.get("remoteHost")),
            as_text(row.get("rule")),
            as_text(row.get("policyName")),
            as_text(row.get("notes")),
        ]
    )
    sensitive_text = " ".join([host_l, path, as_text(row.get("URL"))])
    topic = bool(TOPIC_RE.search(topic_text))
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
            "sensitive": False,
            "rules": Counter(),
            "policies": Counter(),
            "statuses": Counter(),
            "first": "",
            "last": "",
            "sample_path": "",
        },
    )
    item["count"] += 1
    item["rejected"] += int(rejected)
    item["direct"] += int(not rejected)
    item["topic"] = item["topic"] or topic
    item["sensitive"] = item["sensitive"] or bool(SENSITIVE_RE.search(sensitive_text))
    item["rules"][rule] += 1
    item["policies"][policy] += 1
    item["statuses"][status] += 1
    if path and not item["sample_path"]:
        item["sample_path"] = path[:160]
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
    if item["sensitive"]:
        return "sensitive-skip"
    if item["rejected"] > 0:
        return "rejected-by-other"
    if HIGH_CONF_RE.search(host):
        return "candidate-reject"
    if item["topic"] or OBSERVE_RE.search(host):
        return "observe"
    return "ignore"


for item in by_host.values():
    item["class"] = classify(item)

items = sorted(
    by_host.values(),
    key=lambda x: (
        {"candidate-reject": 0, "observe": 1, "existing-rule": 2, "sensitive-skip": 3, "rejected-by-other": 4, "ignore": 5}.get(x["class"], 9),
        -x["count"],
        x["host"],
    ),
)

with summary_path.open("w", encoding="utf-8") as f:
    f.write("class\thost\tbase_domain\tcount\trejected\tdirect\trules\tpolicies\tstatuses\tfirst\tlast\tsample_path\n")
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
                    item["sample_path"],
                ]
            )
            + "\n"
        )

candidates = [item["host"] for item in items if item["class"] == "candidate-reject"]
with candidate_path.open("w", encoding="utf-8") as f:
    f.write("# Review before merging into rewrite/Surge/camscanner-self.sgmodule\n")
    f.write("# Generated from: " + str(raw_path) + "\n")
    for host in candidates:
        f.write(f"DOMAIN,{host},REJECT\n")

classes = Counter(item["class"] for item in items)
time_range = f"{min(times)} -> {max(times)}" if times else "unknown"


def table_lines(selected, limit=30):
    lines = ["| class | host | count | rejected | policy | rule | sample path |", "| --- | --- | ---: | ---: | --- | --- | --- |"]
    for item in selected[:limit]:
        lines.append(
            f"| {item['class']} | `{item['host']}` | {item['count']} | {item['rejected']} | "
            f"{top(item['policies'])} | {top(item['rules'])} | `{item['sample_path'] or '-'}` |"
        )
    if len(selected) > limit:
        lines.append(f"| ... | {len(selected) - limit} more | | | | | |")
    return "\n".join(lines)


candidate_items = [item for item in items if item["class"] == "candidate-reject"]
observe_items = [item for item in items if item["class"] == "observe"]
sensitive_items = [item for item in items if item["class"] == "sensitive-skip"]
existing_items = [item for item in items if item["class"] == "existing-rule"]

report = [
    "# CamScanner Surge Candidate Report",
    "",
    f"- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    f"- Source: `{raw_path}`",
    f"- Requests: {len(rows)}",
    f"- Unique hosts: {len(items)}",
    f"- Time range: {time_range}",
    f"- New reject candidates: {classes['candidate-reject']}",
    f"- Observe-only hosts: {classes['observe']}",
    f"- Existing rules seen: {classes['existing-rule']}",
    f"- Sensitive hosts skipped: {classes['sensitive-skip']}",
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
    report.append("No observe-only CamScanner hosts in this dump.")

report.extend(["", "## Sensitive Skips", ""])
if sensitive_items:
    report.append(table_lines(sensitive_items))
else:
    report.append("No purchase/account-sensitive hosts appeared in this dump.")

report.extend(["", "## Existing Rules Seen", ""])
if existing_items:
    report.append(table_lines(existing_items))
else:
    report.append("No current CamScanner module rules appeared in this dump.")

report.extend(
    [
        "",
        "## Files",
        "",
        f"- Summary TSV: `{summary_path}`",
        f"- Candidate rules: `{candidate_path}`",
        "",
        "Review `candidate-rules.list` manually before copying any line into the production module.",
    ]
)

report_path.write_text("\n".join(report) + "\n", encoding="utf-8")

print(f"requests={len(rows)}")
print(f"unique_hosts={len(items)}")
print(f"time_range={time_range}")
print(f"candidate_reject={classes['candidate-reject']}")
print(f"observe={classes['observe']}")
print(f"existing_rule={classes['existing-rule']}")
print(f"sensitive_skip={classes['sensitive-skip']}")
print(f"raw_json={raw_path}")
print(f"summary_tsv={summary_path}")
print(f"candidate_rules={candidate_path}")
print(f"report_md={report_path}")
PY
