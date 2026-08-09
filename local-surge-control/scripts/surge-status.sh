#!/usr/bin/env bash
set -u
set -o pipefail
if [[ $- == *x* ]]; then
  set +x
fi
umask 077

PROFILE_DIR="${HOME}/Library/Mobile Documents/iCloud~com~nssurge~inc/Documents"
LEGACY_PROFILE="${SURGE_PROFILE:-}"
IOS_PROFILE="${SURGE_IOS_PROFILE:-${LEGACY_PROFILE:-${PROFILE_DIR}/DMIT.conf}}"
MAC_PROFILE="${SURGE_MAC_PROFILE:-${LEGACY_PROFILE:-${PROFILE_DIR}/DMIT-Mac.conf}}"
ATV_PROFILE="${SURGE_ATV_PROFILE:-${LEGACY_PROFILE:-${PROFILE_DIR}/DMIT-ATV.conf}}"
API_PORT="${SURGE_HTTP_API_PORT:-1132}"
MAC_HOST="${SURGE_MAC_HOST:-127.0.0.1}"
IOS_HOST="${SURGE_IOS_HOST:-}"
ATV_HOST="${SURGE_ATV_HOST:-}"
HTTP_CA="${SURGE_HTTP_CA:-}"
HTTP_INSECURE="${SURGE_HTTP_INSECURE:-0}"
FAILURES=0

target="${1:-all}"

if [[ "$HTTP_INSECURE" != "0" && "$HTTP_INSECURE" != "1" ]]; then
  echo "SURGE_HTTP_INSECURE must be 0 or 1." >&2
  exit 2
fi
if [[ "$HTTP_CA" == *$'\n'* || "$HTTP_CA" == *$'\r'* ]]; then
  echo "SURGE_HTTP_CA must not contain a newline." >&2
  exit 2
fi

extract_secret() {
  local profile="$1"
  local key="$2"
  sed -nE "s/^${key}[[:space:]]*=[[:space:]]*([^@]+)@.*/\\1/p" "$profile" |
    head -1 |
    tr -d '\r'
}

profile_has_setting() {
  local profile="$1"
  local key="$2"
  grep -Eq "^${key}[[:space:]]*=" "$profile"
}

status_line() {
  if [[ "$3" == FAIL:* ]]; then
    FAILURES=$((FAILURES + 1))
  fi
  printf '%-5s %-22s %s\n' "$1" "$2" "$3"
}

valid_host() {
  [[ "$1" =~ ^[-A-Za-z0-9._:]+$ || "$1" =~ ^\[[0-9A-Fa-f:]+\]$ ]]
}

valid_port() {
  [[ "$1" =~ ^[0-9]+$ ]] && ((10#$1 >= 1 && 10#$1 <= 65535))
}

curl_config() {
  local http_key="$1"
  local escaped_key escaped_ca
  if [[ "$http_key" == *$'\n'* || "$http_key" == *$'\r'* ]]; then
    return 1
  fi
  escaped_key="${http_key//\\/\\\\}"
  escaped_key="${escaped_key//\"/\\\"}"
  printf 'header = "X-Key: %s"\n' "$escaped_key"
  printf 'silent\nshow-error\nconnect-timeout = 2\nmax-time = 6\n'
  if [[ "$HTTP_INSECURE" == "1" ]]; then
    printf 'insecure\n'
  elif [[ -n "$HTTP_CA" ]]; then
    escaped_ca="${HTTP_CA//\\/\\\\}"
    escaped_ca="${escaped_ca//\"/\\\"}"
    printf 'cacert = "%s"\n' "$escaped_ca"
  fi
}

probe_controller_boundary() {
  local label="$1"
  local profile="$2"
  if profile_has_setting "$profile" external-controller-access; then
    status_line "$label" "external-controller" \
      "SKIP: helper uses HTTPS API only; use the secure surge-cli prompt or --password-stdin separately"
  else
    status_line "$label" "external-controller" "SKIP: not configured in profile"
  fi
}

probe_http_api() {
  local label="$1"
  local host="$2"
  local profile="$3"
  local http_key

  http_key="$(extract_secret "$profile" http-api)"

  if [[ -z "$http_key" ]]; then
    status_line "$label" "https-http-api" "SKIP: http-api is not configured in profile"
    return
  fi
  if ! valid_host "$host" || ! valid_port "$API_PORT"; then
    status_line "$label" "https-http-api" "FAIL: invalid explicit host or port"
    return
  fi
  if [[ -n "$HTTP_CA" && ! -r "$HTTP_CA" && "$HTTP_INSECURE" != "1" ]]; then
    status_line "$label" "https-http-api" "FAIL: SURGE_HTTP_CA is not readable"
    return
  fi

  local response body http_code rc
  response="$(
    curl_config "$http_key" |
      curl -q --noproxy '*' --config - --write-out $'\n%{http_code}' \
        "https://${host}:${API_PORT}/v1/events" 2>/dev/null
  )"
  rc=$?
  http_code="${response##*$'\n'}"
  body="${response%$'\n'*}"

  if [[ $rc -eq 0 && "$http_code" == "200" && "$body" == *'"events"'* ]]; then
    if [[ "$HTTP_INSECURE" == "1" ]]; then
      status_line "$label" "https-http-api" \
        "OK: ${host}:${API_PORT} (TLS verification explicitly disabled)"
    else
      status_line "$label" "https-http-api" "OK: ${host}:${API_PORT} (TLS verified)"
    fi
  elif [[ "$http_code" == "401" || "$http_code" == "403" ]]; then
    status_line "$label" "https-http-api" "FAIL: authentication denied at ${host}:${API_PORT}"
  elif [[ "$http_code" =~ ^[0-9]{3}$ && "$http_code" != "000" ]]; then
    status_line "$label" "https-http-api" "FAIL: HTTP ${http_code} at ${host}:${API_PORT}"
  else
    status_line "$label" "https-http-api" \
      "FAIL: TLS or transport check failed at ${host}:${API_PORT}; no response body was printed"
  fi
}

probe_device() {
  local label="$1"
  local host="$2"
  local profile="$3"
  if [[ ! -r "$profile" ]]; then
    status_line "$label" "profile" "FAIL: device profile is not readable; set the matching SURGE_*_PROFILE"
    return
  fi
  probe_controller_boundary "$label" "$profile"
  probe_http_api "$label" "$host" "$profile"
}

probe_ios() {
  if [[ -z "$IOS_HOST" ]]; then
    status_line "ios" "host" \
      "FAIL: set SURGE_IOS_HOST explicitly; credentialed ARP discovery is disabled"
    return
  fi
  probe_device "ios" "$IOS_HOST" "$IOS_PROFILE"
}

probe_atv() {
  if [[ -z "$ATV_HOST" ]]; then
    status_line "atv" "host" "SKIP: set SURGE_ATV_HOST explicitly for Apple TV"
    return
  fi
  probe_device "atv" "$ATV_HOST" "$ATV_PROFILE"
}

case "$target" in
  mac)
    probe_device "mac" "$MAC_HOST" "$MAC_PROFILE"
    ;;
  ios|iphone)
    probe_ios
    ;;
  atv|tvos|apple-tv)
    probe_atv
    ;;
  all)
    probe_device "mac" "$MAC_HOST" "$MAC_PROFILE"
    probe_ios
    probe_atv
    ;;
  *)
    echo "Usage: $0 [all|mac|ios|atv]" >&2
    exit 2
    ;;
esac

if ((FAILURES > 0)); then
  exit 1
fi
