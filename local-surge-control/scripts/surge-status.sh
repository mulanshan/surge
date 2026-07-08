#!/usr/bin/env bash
set -u

PROFILE="${SURGE_PROFILE:-/Users/mulanshan/Library/Mobile Documents/iCloud~com~nssurge~inc/Documents/DMIT.conf}"
SURGE_CLI="${SURGE_CLI:-/Applications/Surge.app/Contents/Applications/surge-cli}"
CTRL_PORT="${SURGE_CONTROLLER_PORT:-6170}"
API_PORT="${SURGE_HTTP_API_PORT:-1132}"
MAC_HOST="${SURGE_MAC_HOST:-127.0.0.1}"
IOS_HOST="${SURGE_IOS_HOST:-}"
IOS_HOST_HINTS="${SURGE_IOS_HOST_HINTS:-192.168.50.101 192.168.70.124 192.168.0.107}"
ATV_HOST="${SURGE_ATV_HOST:-192.168.50.107}"

target="${1:-all}"

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
  arp -a 2>/dev/null | sed -nE 's/.*\(([0-9.]+)\).*/\1/p'
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
    printf '%s\n' $IOS_HOST_HINTS
    arp_ipv4s
  } | awk 'NF && !seen[$0]++'
}

verify_remote_host() {
  local host="$1"
  local output
  is_local_host "$host" && return 1

  if [[ -n "${HTTP_KEY}" ]]; then
    output="$(curl --noproxy '*' -k -fsS --connect-timeout 1 -m 2 -H "X-Key: ${HTTP_KEY}" "https://${host}:${API_PORT}/v1/events" 2>&1)"
    [[ "$output" == *'"events"'* ]] && return 0
  fi

  if [[ -n "${CTRL_PASS}" && -x "$SURGE_CLI" ]]; then
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

case "$target" in
  mac)
    probe_device "mac" "$MAC_HOST"
    ;;
  ios|iphone)
    probe_ios
    ;;
  atv|tvos|apple-tv)
    probe_device "atv" "$ATV_HOST"
    ;;
  all)
    probe_device "mac" "$MAC_HOST"
    probe_ios
    probe_device "atv" "$ATV_HOST"
    ;;
  *)
    echo "Usage: $0 [all|mac|ios|atv]" >&2
    exit 2
    ;;
esac
