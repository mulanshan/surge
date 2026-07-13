---
name: local-surge-control
description: Control and troubleshoot the user's local macOS Surge and remote iPhone/Apple TV Surge instances from the Mac. Use when Codex needs to inspect Mac Surge status, connect to iOS or tvOS Surge over LAN, verify External Controller port 6170 or HTTPS HTTP API port 1132, collect events/requests/profile data, reload profiles, update DMIT.conf controller/API settings, or explain permission and security boundaries for Surge remote control.
---

# Local Surge Control

## Overview

Use this skill for an Apple-ecosystem Surge setup: Mac is the operator, while iPhone and Apple TV are optional LAN targets. Prefer live verification over assumptions because device IPs, profile sync, and tvOS reload state can drift.

## Local Context

- Surge CLI is usually not in `PATH`; use `/Applications/Surge.app/Contents/Applications/surge-cli`.
- Shared profile default: `$HOME/Library/Mobile Documents/iCloud~com~nssurge~inc/Documents/DMIT.conf`. Override it with `SURGE_PROFILE`.
- Device addresses are runtime values, not repository configuration. Set `SURGE_IOS_HOST` or `SURGE_ATV_HOST` for exact targets. Set space-separated `SURGE_IOS_HOST_HINTS` only when ARP discovery is insufficient.
- External Controller port: `6170`, configured by `external-controller-access = password@host:port`.
- HTTPS HTTP API port: `1132`, configured by `http-api = key@host:port` and `http-api-tls = true`.
- Read controller password and HTTP API key from `DMIT.conf` at runtime. Do not hard-code or print secrets unless the user explicitly asks.

## Quick Status

Run the bundled probe before drawing conclusions:

```bash
scripts/surge-status.sh all
scripts/surge-status.sh ios
scripts/surge-status.sh atv
scripts/surge-status.sh mac
```

The script verifies External Controller with `surge-cli --remote ... environment` and verifies HTTP API with `GET /v1/events` over HTTPS using the `X-Key` header. It reads credentials from `DMIT.conf` and only reports status.
For `ios`, the script auto-discovers a reachable non-local Surge host from optional hints plus ARP candidates. Override with `SURGE_IOS_HOST=<ip>` when you need an exact target. Apple TV discovery is intentionally explicit: set `SURGE_ATV_HOST=<ip>` before probing it.

If the helper reports immediate connection failures inside a restricted sandbox but the same `surge-cli` or `curl` command works when run directly, treat it as a tool-permission issue and rerun the helper with LAN/network approval before diagnosing Surge.

## LAN Change / Device Discovery

When the user moves to another LAN, never assume the previous iPhone IP is still valid. A stale IP commonly appears as:

- `surge-cli --raw --remote ... environment` returning `(null)`
- `dump request` / `dump event` returning `(null)`
- HTTPS HTTP API `1132` timing out

Before concluding that there are no app logs, discover the current target:

1. Read the Mac's active LAN address with `ifconfig` and the current route with `route -n get default`.
2. List nearby IPv4 devices with `arp -a`.
3. Probe ARP candidates for Surge controller ports `6170` and `1132`; request LAN/network approval when sandboxing blocks `nc`, `curl`, or `surge-cli`.
4. Verify candidates with the stored External Controller credential:

```bash
"$SURGE_CLI" --raw --remote "${CTRL_PASS}@<candidate-ip>:6170" environment
"$SURGE_CLI" --raw --remote "${CTRL_PASS}@<candidate-ip>:6170" dump request
```

Treat `Authorization denied` as the wrong Surge instance or wrong profile. Treat a successful `environment` plus request data as the active target. Then pass the discovered IP into workspace helpers, for example:

```bash
SURGE_REMOTE_HOST=<candidate-ip> scripts/export-fanqie-candidates.sh
```

For a Fanqie/番茄小说 capture workflow, this discovery step is mandatory after a LAN change because the request buffer is short and stale IP probing wastes the useful capture window.

## Credential Extraction Pattern

Use this pattern when writing one-off commands:

```bash
PROFILE="${SURGE_PROFILE:-$HOME/Library/Mobile Documents/iCloud~com~nssurge~inc/Documents/DMIT.conf}"
SURGE_CLI="/Applications/Surge.app/Contents/Applications/surge-cli"
CTRL_PASS="$(sed -nE 's/^external-controller-access[[:space:]]*=[[:space:]]*([^@]+)@.*/\1/p' "$PROFILE" | head -1)"
HTTP_KEY="$(sed -nE 's/^http-api[[:space:]]*=[[:space:]]*([^@]+)@.*/\1/p' "$PROFILE" | head -1)"
```

Quote `--remote` arguments so future password changes with shell-sensitive characters do not break commands.

## Control Surfaces

Use External Controller `6170` for Surge CLI operations:

```bash
"$SURGE_CLI" --raw --remote "${CTRL_PASS}@<ios-ip>:6170" environment
"$SURGE_CLI" --remote "${CTRL_PASS}@<ios-ip>:6170" reload
"$SURGE_CLI" --raw --remote "${CTRL_PASS}@<ios-ip>:6170" dump event
"$SURGE_CLI" --raw --remote "${CTRL_PASS}@<ios-ip>:6170" dump request
```

Use HTTPS HTTP API `1132` for documented API access:

```bash
curl -k -fsS -H "X-Key: $HTTP_KEY" https://<ios-ip>:1132/v1/events
curl -k -fsS -H "X-Key: $HTTP_KEY" "https://<ios-ip>:1132/v1/profiles/current?sensitive=0"
curl -k -fsS -H "X-Key: $HTTP_KEY" https://<ios-ip>:1132/v1/requests/recent
```

Use local Mac probes if Surge CLI returns `(null)` or crashes:

```bash
lsof -nP -iTCP:6152 -iTCP:6153 -iTCP:6170 -iTCP:1132
curl -x http://127.0.0.1:6152 -fsS -o /dev/null -w '%{http_code}\n' http://cp.cloudflare.com/generate_204
```

## Permission And Security Boundaries

- External Controller `6170` can read runtime state, recent requests, events, policies/rules/profile, trigger reloads, run tests, update external resources, and mutate runtime environment settings with `set`. Treat it as high privilege.
- HTTP API `1132` uses `X-Key`; with HTTPS enabled, use `curl -k` because Surge generates the server certificate from its MITM CA. It can read and change documented API resources, including feature toggles, outbound mode, policy group selection, recent requests, events, and profile reload. It does not directly edit `DMIT.conf` text.
- `GET /v1/profiles/current?sensitive=0` masks proxy credentials and is safe for normal diagnostics. Avoid `sensitive=1` unless the user explicitly needs raw secrets.
- LAN access requires `0.0.0.0` listeners and a complex key/password. Do not expose `1132` over LAN with weak keys or without TLS.
- Editing the iCloud `DMIT.conf` is a persistent config change outside most workspaces. Create a timestamped backup, apply the smallest edit, run `surge-cli --check`, then reload and verify every target.
- Apple TV may keep an old runtime profile after iCloud changes. Do not claim ATV has updated until the new key works and old key fails against the current `SURGE_ATV_HOST`.
- When watching traffic, only traffic traversing the monitored Surge instance appears. For iPhone app traffic, connect to the iPhone Surge endpoint or ensure the phone is routed through the Mac Surge instance.

## Change Workflow

1. Read current `DMIT.conf` lines with `rg -n '^http-api|^http-api-tls|^external-controller-access' "$PROFILE"`.
2. Back up `DMIT.conf` before edits.
3. Change only the required line(s).
4. Run `"$SURGE_CLI" --check "$PROFILE"`.
5. Reload via External Controller for reachable targets.
6. Verify positive and negative auth: new credential succeeds, old credential fails.
7. Report exact device status separately for Mac, iPhone, and Apple TV.

## References

- Official docs and endpoint notes: `references/surge-control-reference.md`.
- Probe helper: `scripts/surge-status.sh`.
