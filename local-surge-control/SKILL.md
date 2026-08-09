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
  iOS, `DMIT-Mac.conf` for Mac, `DMIT-ATV.conf` for Apple TV, and
  `DMIT-Common.dconf` for shared content. Use `SURGE_IOS_PROFILE`,
  `SURGE_MAC_PROFILE`, and `SURGE_ATV_PROFILE` for device-specific overrides.
  `SURGE_PROFILE` remains a legacy compatibility override for old setups where
  all three devices intentionally use one profile.
- Device addresses are runtime values, not repository configuration. Set
  `SURGE_IOS_HOST` or `SURGE_ATV_HOST` to a host that the user explicitly
  identified.
- External Controller port `6170` is configured by
  `external-controller-access = password@host:port`.
- HTTPS HTTP API port `1132` is configured by
  `http-api = key@host:port` and `http-api-tls = true`.
- Read credentials from the profile at runtime. Never hard-code, print, log, or
  place them in a command-line argument.
- Mac, iOS, and Apple TV each use their matching profile credential; never
  reuse one device's HTTP API or External Controller credential for another.
- `wifi-access-http-auth` is also authentication material. Check only whether
  it is configured; never print its value.

## Quick Status

Run the bundled probe before drawing conclusions:

```bash
SURGE_IOS_HOST=ios-surge.local SURGE_ATV_HOST=apple-tv-surge.local \
  local-surge-control/scripts/surge-status.sh all
SURGE_IOS_HOST=ios-surge.local local-surge-control/scripts/surge-status.sh ios
SURGE_ATV_HOST=apple-tv-surge.local local-surge-control/scripts/surge-status.sh atv
local-surge-control/scripts/surge-status.sh mac
```

The helper checks the HTTPS HTTP API with `GET /v1/events`. It passes the
`X-Key` header to `curl` through standard input, verifies TLS by default, never
loads a user `curlrc`, prints no response body on failure, returns nonzero when
a required or explicitly targeted device check fails, and never performs
credentialed host discovery. Use `SURGE_HTTP_CA=/path/to/trusted-ca.pem` when
the Surge CA is not already trusted by the system.

For `all`, the helper always checks Mac and iOS, so `SURGE_IOS_HOST` is
required. It checks Apple TV only when `SURGE_ATV_HOST` is explicitly set. A
missing `SURGE_ATV_HOST` is an intentional `SKIP` and does not make `all` fail.
The helper reads the Mac key from `DMIT-Mac.conf`, the iOS key from `DMIT.conf`,
and the Apple TV key from `DMIT-ATV.conf`; it does not reuse one device's
credential for another.

`SURGE_HTTP_INSECURE=1` is an explicit, temporary diagnostic escape hatch. A
successful result in that mode is reported as unverified and must not be used
as final evidence.

The helper remains HTTPS-API-only by design. Surge Mac 6.8.0 can safely
authenticate direct CLI sessions, so use the CLI when its expanded diagnostics
are more suitable than the helper.

## Surge CLI 6.8

Use `--remote host:port` for a DNS name or IPv4 address and `--remote [addr]:port`
for IPv6. Never place the External Controller password in argv, including in a
password-prefixed endpoint.

For an attended command, omit all password options. Use the secure terminal prompt:

```bash
SURGE_CLI=/Applications/Surge.app/Contents/Applications/surge-cli
"$SURGE_CLI" --remote ios-surge.local:6170 status
"$SURGE_CLI" --remote '[2001:db8::10]:6170' status
```

For automation, prefer `--password-stdin` and pipe the first line from a
trusted secret manager. `SURGE_CLI_PASSWORD` is an acceptable fallback when a
stdin pipe is impractical, but keep it out of logs, unset it promptly, and do
not expose it through shell tracing. Do not combine multiple credentials in one
cross-device probe.

Stalled remote connections and finite operations have timeouts. Treat a timeout
as an inconclusive result and re-establish the exact target before retrying.
Interactive mode supports quoted arguments and backslash escaping, which are
required for names containing spaces or literal special characters; never use
either form to place a credential in command text.

Start with read-only, human-readable diagnostics. Add `--raw` only when a
structured consumer needs JSON:

The expanded commands can operate compatible Surge iOS 5.21.0 and compatible
Surge tvOS 5.21.0 instances through `--remote`. Target-platform restrictions
still apply; do not assume a macOS-only command is available on iOS or tvOS.

When more than one Surge instance has been inspected in a task, bind every
mutation to one exact target before executing it: explicitly choose local Mac
operation without `--remote`, or one verified remote endpoint with `--remote`.
Never infer the mutation target from the preceding read-only command or reuse a
different device's credential.

- `status`, `version`, and `dump summary` establish version, uptime, active
  profile, mode, feature states, interfaces, DNS, and configuration warnings.
- `profile current`, `profile list`, and `profile check <name>` inspect profile
  state without switching it. Listing and validation are macOS-only.
- `policy-group list` and `policy-group get <group>` inspect selections. Use
  `policy-group set <group> <policy>` to make a manual selection or pass `auto`
  as the policy to clear an automatic-group override.
- `module list`, `feature list`, and `feature get <name>` inspect runtime
  modules and features. `module enable <name...>` and
  `module disable <name...>` each accept multiple module names in one operation.
- `device` is macOS-only and lists or inspects Gateway Mode clients. Device
  identifiers and MAC addresses are sensitive; redact them together with
  private addresses before quoting results.
- `script list` is read-only. `script-log <log-name> <session-id>` is also
  read-only and does not run a script, but its stored output or exception may
  contain secrets. Use only a log name and session ID returned in known script
  execution metadata or provided by the user. `script list` does not supply a
  replacement session ID; do not guess a session identifier or rerun a script
  to manufacture one.
- `log file <count>`, `log memory <count>`, `log watch`, and `logbook <limit>`
  inspect recent or newly generated diagnostics, with a maximum of 10,000 lines
  per finite log request. The persistent file log provides longer history at
  the configured level, while the in-memory log provides more detailed recent
  entries from all levels. `log watch` is a continuous stream, so bound the
  observation and stop it explicitly. Unfiltered logs are sensitive; redact
  URLs, headers, tokens, and private addresses.

Never directly invoke `log file <count>` or `log memory <count>` from an agent
tool when its stdout would be recorded. Pipe the stream into a trusted local
summarizer that emits only redacted fields or aggregate counts; the raw stream
must not reach the task transcript. Do not use `tee`, and do not retrieve the
log when safe local summarization cannot be guaranteed.
- `benchmark encryption` measures correctness and encryption/decryption
  performance on the Surge target. It changes no setting, but can consume CPU;
  with `--remote`, the result describes the remote device rather than the Mac.
- `test-policy-bandwidth` with `<download/upload> <policy-name>` is an active
  network workload. Run it only when explicitly requested because it consumes
  traffic and bandwidth; with `--remote`, the traffic is generated by the target.
- Use `dump policy` to get the line hash for `proxy-runtime-status <line-hash>`,
  including detailed Tailscale and WireGuard state.

Treat execution separately from inspection. Run `script run` only when
explicitly requested because it executes a named cron script, including a
disabled script, and may have arbitrary side effects. Its returned output or
exception is the result; use `script-log` as a read-only follow-up and do not
rerun the script merely to verify it.

`reconnect-device` is a macOS-only connectivity mutation. Run it only when
explicitly requested and after resolving one exact access-point client. After
`reconnect-device` returns, use `device` to read back and verify that client;
if the read-back is inconclusive, report that result instead of reconnecting it
again.

`managed-profile update` checks, validates, replaces, and reloads the active
managed profile. Run it only when explicitly requested. Treat its returned
state as the first result, then use `status` and `profile current` to verify the
active profile on the exact local or remote target; do not retry an inconclusive
update automatically.

Commands that change settings return the resulting state and a nonzero status
on failure. Always re-query the resulting state independently after `mode set`,
`global-policy set`, `policy-group set`, `profile switch`, `module enable` or
`module disable`, `feature set`, and `set <key-path>=<value>`. System Proxy and
Enhanced Mode changes wait for the actual transition, but still read them back
with `feature get` before reporting success. System Proxy and Enhanced Mode are
macOS-only features.

Do not gate the read-back on the mutation's exit status. A timeout or nonzero
mutation result may leave the target in either state, so run the independent
read command anyway, preserve both statuses, and report an inconclusive result
instead of retrying the mutation automatically.

## Known Surge 6.8 NTP Warning

When the persistent log reports an hourly `SGNTPClient` warning, read the NTP
section in `references/surge-control-reference.md` before changing rules. On
this Mac, the confirmed failure is Surge's fixed Apple target set, not a general
UDP/123 outage. Do not change policies, controller credentials, or the signed
app to suppress the warning; retain it as an upstream issue until a Surge update
changes the targets or behavior.

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
- Never place an External Controller password in argv. Use the secure terminal
  prompt for attended work, `--password-stdin` for automation, or
  `SURGE_CLI_PASSWORD` as a controlled fallback.
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

1. Set the three device-profile paths and confirm setting presence without
   printing values:

   ```bash
   SURGE_IOS_PROFILE="${SURGE_IOS_PROFILE:-$HOME/Library/Mobile Documents/iCloud~com~nssurge~inc/Documents/DMIT.conf}"
   SURGE_MAC_PROFILE="${SURGE_MAC_PROFILE:-$HOME/Library/Mobile Documents/iCloud~com~nssurge~inc/Documents/DMIT-Mac.conf}"
   SURGE_ATV_PROFILE="${SURGE_ATV_PROFILE:-$HOME/Library/Mobile Documents/iCloud~com~nssurge~inc/Documents/DMIT-ATV.conf}"
   for profile in "$SURGE_IOS_PROFILE" "$SURGE_MAC_PROFILE" "$SURGE_ATV_PROFILE"; do
     sed -nE 's/^(http-api|http-api-tls|external-controller-access|wifi-access-http-auth)[[:space:]]*=.*/\1 = configured/p' "$profile"
   done
   ```

2. Back up all three device profiles and the shared `DMIT-Common.dconf` before
   editing.
3. Change only the required line or split device-specific `[General]` settings
   into detached profiles.
4. Run `"$SURGE_CLI" --check` separately for `DMIT.conf`, `DMIT-Mac.conf`, and
   `DMIT-ATV.conf`.
5. Reload through the HTTPS API when available.
6. Verify positive and negative authentication without printing any
   credential or raw response.
7. Report Mac, iPhone, and Apple TV status separately.

## References

- Official docs and endpoint notes: `references/surge-control-reference.md`.
- Safe status helper: `scripts/surge-status.sh`.
