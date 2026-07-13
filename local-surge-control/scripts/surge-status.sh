#!/usr/bin/env bash
set -u

PROFILE="${SURGE_PROFILE:-${HOME}/Library/Mobile Documents/iCloud~com~nssurge~inc/Documents/DMIT.conf}"
SURGE_CLI="${SURGE_CLI:-/Applications/Surge.app/Contents/Applications/surge-cli}"
CTRL_PORT="${SURGE_CONTROLLER_PORT:-6170}"
API_PORT="${SURGE_HTTP_API_PORT:-1132}"
MAC_HOST="${SURGE_MAC_HOST:-127.0.0.1}"
IOS_HOST="${SURGE_IOS_HOST:-}"
IOS_HOST_HINTS="${SURGE_IOS_HOST_HINTS:-}"
ATV_HOST="${SURGE_ATV_HOST:-}"

target="${1:-all}"

if [[ ! -r "$PROFILE" ]]; then
  echo "Surge profile is not readable: $PROFILE" >&2
  echo "Set SURGE_PROFILE to the shared Surge profile path." >&2
  exit 1
fi

extract_secret() {
  local key="$1"
  sed -nE "s/^${key}[[:space:]]*=[[:space:]]*([^@]+)@.*/\\1/p" "$PROFILE" | head -1
}

CTRL_PASS="$(extract_secret external-controller-access)"
HTTP_KEY="$(extract_secret http-api)"

status_line() {
  printf '%-5s %-22s %s\n' "$1" "$2" "$3"
}

local_ipv4s() {
  ifconfig 2>/dev/null | sed -nE 's/^[[:space:]]*inet ([0-9.]+) .*/\1/p'
}

arp_ipv4s() {
  arp -a 2>/dev/null | awk '$0 !~ /\(incomplete\)/' | sed -nE 's/.*\(([0-9.]+)\).*/\1/p'
}

is_local_host() {
  local host="$1"
  local ip
  [[ "$host" == "127.0.0.1" || "$host" == "localhost" ]] && return 0
  for ip in $(local_ipv4s); do
    [[ "$host" == "$ip" ]] && return 0
  done
  return 1
}

candidate_hosts() {
  {
    if [[ -n "$IOS_HOST_HINTS" ]]; then
      printf '%s\n' $IOS_HOST_HINTS
    fi
    arp_ipv4s
  } | awk '
    /^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)/ && !seen[$0]++
  '
}

tcp_port_open() {
  local host="$1"
  local port="$2"
  if ! command -v nc >/dev/null 2>&1; then
    return 0
  fi
  if nc -h 2>&1 | grep -q -- '-G'; then
    nc -G 1 -z "$host" "$port" >/dev/null 2>&1
  else
    nc -w 1 -z "$host" "$port" >/dev/null 2>&1
  fi
}

verify_remote_host() {
  local host="$1"
  local output
  local api_open=1
  local controller_open=1
  is_local_host "$host" && return 1

  if command -v nc >/dev/null 2>&1; then
    api_open=0
    controller_open=0
    tcp_port_open "$host" "$API_PORT" && api_open=1
    tcp_port_open "$host" "$CTRL_PORT" && controller_open=1
    [[ $api_open -eq 0 && $controller_open -eq 0 ]] && return 1
  fi

  if [[ -n "${HTTP_KEY}" && $api_open -eq 1 ]]; then
    output="$(curl --noproxy '*' -k -fsS --connect-timeout 1 -m 2 -H "X-Key: ${HTTP_KEY}" "https://${host}:${API_PORT}/v1/events" 2>&1)"
    [[ "$output" == *'"events"'* ]] && return 0
  fi

  if [[ -n "${CTRL_PASS}" && -x "$SURGE_CLI" && $controller_open -eq 1 ]]; then
    output="$("$SURGE_CLI" --raw --remote "${CTRL_PASS}@${host}:${CTRL_PORT}" environment 2>&1)"
    [[ "$output" == *'"result":"success"'* ]] && return 0
  fi

  return 1
}

discover_ios_host() {
  local host
  for host in $(candidate_hosts); do
    if verify_remote_host "$host"; then
      printf '%s\n' "$host"
      return 0
    fi
  done
  return 1
}

probe_controller() {
  local label="$1"
  local host="$2"
  if [[ -z "${CTRL_PASS}" ]]; then
    status_line "$label" "external-controller" "SKIP: missing external-controller-access in profile"
    return
  fi
  if [[ ! -x "$SURGE_CLI" ]]; then
    status_line "$label" "external-controller" "SKIP: surge-cli not executable at $SURGE_CLI"
    return
  fi

  local output
  output="$("$SURGE_CLI" --raw --remote "${CTRL_PASS}@${host}:${CTRL_PORT}" environment 2>&1)"
  local rc=$?
  if [[ $rc -eq 0 && "$output" == *'"result":"success"'* ]]; then
    status_line "$label" "external-controller" "OK: ${host}:${CTRL_PORT}"
  elif [[ "$output" == *"Authorization denied"* ]]; then
    status_line "$label" "external-controller" "FAIL: auth denied at ${host}:${CTRL_PORT}"
  else
    status_line "$label" "external-controller" "FAIL: ${output}"
  fi
}

probe_http_api() {
  local label="$1"
  local host="$2"
  if [[ -z "${HTTP_KEY}" ]]; then
    status_line "$label" "https-http-api" "SKIP: missing http-api in profile"
    return
  fi

  local output
  output="$(curl --noproxy '*' -k -fsS -m 6 -H "X-Key: ${HTTP_KEY}" "https://${host}:${API_PORT}/v1/events" 2>&1)"
  local rc=$?
  if [[ $rc -eq 0 && "$output" == *'"events"'* ]]; then
    status_line "$label" "https-http-api" "OK: https://${host}:${API_PORT}/v1/events"
  elif [[ "$output" == *"401"* ]]; then
    status_line "$label" "https-http-api" "FAIL: auth denied at ${host}:${API_PORT}"
  else
    status_line "$label" "https-http-api" "FAIL: ${output}"
  fi
}

probe_device() {
  local label="$1"
  local host="$2"
  probe_controller "$label" "$host"
  probe_http_api "$label" "$host"
}

probe_ios() {
  local host="${IOS_HOST}"
  if [[ -z "$host" ]]; then
    host="$(discover_ios_host || true)"
  fi
  if [[ -z "$host" ]]; then
    status_line "ios" "auto-discovery" "FAIL: no reachable iOS Surge host found; set SURGE_IOS_HOST=<ip> to override"
    return
  fi
  probe_device "ios" "$host"
}

probe_atv() {
  if [[ -z "$ATV_HOST" ]]; then
    status_line "atv" "host" "SKIP: set SURGE_ATV_HOST=<ip> for the current Apple TV"
    return
  fi
  probe_device "atv" "$ATV_HOST"
}

case "$target" in
  mac)
    probe_device "mac" "$MAC_HOST"
    ;;
  ios|iphone)
    probe_ios
    ;;
  atv|tvos|apple-tv)
    probe_atv
    ;;
  all)
    probe_device "mac" "$MAC_HOST"
    probe_ios
    probe_atv
    ;;
  *)
    echo "Usage: $0 [all|mac|ios|atv]" >&2
    exit 2
    ;;
esac
