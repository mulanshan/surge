---
name: local-surge-control
description: Control and troubleshoot the user's local macOS Surge and remote iPhone/Apple TV Surge instances from the Mac. Use when Codex needs to inspect Mac Surge status, connect to an explicitly identified iOS or tvOS Surge instance over LAN, verify HTTPS HTTP API port 1132, collect redacted runtime evidence, reload profiles, update DMIT.conf controller/API settings, or explain permission and security boundaries for Surge remote control.
---

# Local Surge Control

## Overview

Use this skill for an Apple-ecosystem Surge setup: Mac is the operator, while
iPhone and Apple TV are optional LAN targets. Prefer live verification over
assumptions because device addresses and runtime profiles can drift. Phone
mirroring is not required for these API-based checks.

## Local Context

- Surge CLI is usually not in `PATH`; its standard path is
  `/Applications/Surge.app/Contents/Applications/surge-cli`.
- Detached-profile defaults in the iCloud Surge directory are `DMIT.conf` for
  iOS, `DMIT-Mac.conf` for Mac, and `DMIT-Common.dconf` for shared content. Use
  `SURGE_IOS_PROFILE` and `SURGE_MAC_PROFILE` for device-specific overrides.
  `SURGE_PROFILE` remains a legacy compatibility override for old setups where
  both devices intentionally use one profile.
- Device addresses are runtime values, not repository configuration. Set
  `SURGE_IOS_HOST` or `SURGE_ATV_HOST` to a host that the user explicitly
  identified.
- External Controller port `6170` is configured by
  `external-controller-access = password@host:port`.
- HTTPS HTTP API port `1132` is configured by
  `http-api = key@host:port` and `http-api-tls = true`.
- Read credentials from the profile at runtime. Never hard-code, print, log, or
  place them in a command-line argument.
- Mac and iOS use separate HTTP API and External Controller credentials. Never
  assume a key read from one device profile authenticates to the other device.
- `wifi-access-http-auth` is also authentication material. Check only whether
  it is configured; never print its value.

## Quick Status

Run the bundled probe before drawing conclusions:

```bash
SURGE_IOS_HOST=ios-surge.local local-surge-control/scripts/surge-status.sh all
SURGE_IOS_HOST=ios-surge.local local-surge-control/scripts/surge-status.sh ios
local-surge-control/scripts/surge-status.sh mac
```

The helper checks the HTTPS HTTP API with `GET /v1/events`. It passes the
`X-Key` header to `curl` through standard input, verifies TLS by default, never
loads a user `curlrc`, prints no response body on failure, returns nonzero when
any requested device check fails, and never performs credentialed host
discovery. Use `SURGE_HTTP_CA=/path/to/trusted-ca.pem` when the Surge CA is not
already trusted by the system.

For `all`, the helper reads the Mac key from `DMIT-Mac.conf` and the iOS key
from `DMIT.conf`. It does not reuse one device's credential for the other.

`SURGE_HTTP_INSECURE=1` is an explicit, temporary diagnostic escape hatch. A
successful result in that mode is reported as unverified and must not be used
as final evidence.

The helper intentionally does not authenticate with remote `surge-cli`.
Surge's CLI accepts the External Controller password only inside the
`--remote password@host:port` argument, which exposes the credential to process
inspection. Prefer the HTTPS API for automated inspection and reloads.

## LAN Change / Device Discovery

When the user moves to another LAN, never assume the previous device address is
still valid. A stale address commonly appears as a timeout or transport error.

Use only uncredentialed evidence to identify a device:

1. Check the Mac's active route and LAN address.
2. Ask the user for the address shown by Surge, or use a trusted router lease or
   an already established local hostname.
3. Optionally test whether ports `1132` or `6170` are open without sending a
   credential.
4. Set exactly one explicit target such as `SURGE_IOS_HOST=ios-surge.local` and
   run the status helper.

Do not take every address from `arp -a` and send the stored HTTP API key or
External Controller password to each candidate. An unrelated or malicious LAN
host could collect the credential.

For traffic-capture workflows, pass the same explicitly identified target to
the exporter:

```bash
SURGE_REMOTE_HOST=ios-surge.local rule/Surge/scripts/export-fanqie-candidates.sh
```

## Credential Handling

- Do not use `rg` or another command that prints complete `http-api` or
  `external-controller-access` lines. Apply the same rule to
  `wifi-access-http-auth`; check only whether each setting exists.
- Do not place an HTTP API key in a `curl -H` argument. The helper and candidate
  exporters use `curl -q --config -` so the header arrives over standard input
  and a user `curlrc` cannot disable TLS or enable secret-bearing traces.
- Do not place an External Controller password in an automated `surge-cli
  --remote` argument. There is no safe non-argv credential input in the current
  CLI.
- Do not include raw command stderr or response bodies in status output. Return
  a categorized TLS, transport, authentication, or HTTP failure instead.
- Treat the profile, process list, shell history, terminal scrollback, task
  transcript, and exported request data as possible secret-bearing surfaces.
- The bundled scripts disable shell xtrace before reading credentials. Do not
  re-enable `set -x` around profile parsing or authenticated requests.

## Control Surfaces

Prefer HTTPS HTTP API `1132` for documented API access. The safe pattern is the
one implemented in `scripts/surge-status.sh`: provide `X-Key` through a stdin
curl config, verify TLS, use an explicit host, and suppress raw failure bodies.
Documented resources include events, recent requests, feature state, policy
groups, and profile reload.

Use local Mac probes that require no credential when the API is unavailable:

```bash
lsof -nP -iTCP:6152 -iTCP:6153 -iTCP:6170 -iTCP:1132
curl -x http://127.0.0.1:6152 -fsS -o /dev/null -w '%{http_code}\n' http://cp.cloudflare.com/generate_204
```

## Permission And Security Boundaries

- External Controller `6170` is high privilege. It can read runtime state,
  recent requests, events, policies, rules, and profile data; trigger reloads
  and tests; update external resources; and mutate runtime settings.
- HTTP API `1132` is also privileged. Use HTTPS with certificate verification
  and a strong key. Bind it to `127.0.0.1` unless LAN access is intentional.
- `GET /v1/profiles/current?sensitive=0` is only partially redacted. Current
  Surge versions may still return HTTP API and External Controller settings
  even when proxy credentials and CA passwords are masked. Treat the entire
  response as sensitive, do not print it during routine diagnostics, and do
  not describe it as safe merely because `sensitive=0` is present.
- Editing the iCloud profile is a persistent change. Create a timestamped
  backup, apply the smallest edit, run `surge-cli --check`, then reload and
  verify each explicit target.
- Apple TV may retain an old runtime profile after iCloud changes. Do not claim
  it has updated until the active endpoint proves the new configuration.
- Request and event data may contain tokens, account identifiers, device
  identifiers, URLs, and private network details. Prefer aggregate results and
  delete temporary raw captures.

## Change Workflow

1. Set the two device-profile paths and confirm setting presence without
   printing values:

   ```bash
   SURGE_IOS_PROFILE="${SURGE_IOS_PROFILE:-$HOME/Library/Mobile Documents/iCloud~com~nssurge~inc/Documents/DMIT.conf}"
   SURGE_MAC_PROFILE="${SURGE_MAC_PROFILE:-$HOME/Library/Mobile Documents/iCloud~com~nssurge~inc/Documents/DMIT-Mac.conf}"
   for profile in "$SURGE_IOS_PROFILE" "$SURGE_MAC_PROFILE"; do
     sed -nE 's/^(http-api|http-api-tls|external-controller-access|wifi-access-http-auth)[[:space:]]*=.*/\1 = configured/p' "$profile"
   done
   ```

2. Back up both device profiles and the shared `DMIT-Common.dconf` before
   editing.
3. Change only the required line or split device-specific `[General]` settings
   into detached profiles.
4. Run `"$SURGE_CLI" --check` separately for `DMIT.conf` and `DMIT-Mac.conf`.
5. Reload through the HTTPS API when available.
6. Verify positive and negative authentication without printing either
   credential or raw response.
7. Report Mac, iPhone, and Apple TV status separately.

## References

- Official docs and endpoint notes: `references/surge-control-reference.md`.
- Safe status helper: `scripts/surge-status.sh`.
