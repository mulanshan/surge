# Surge Control Reference

## Official Docs

- Surge Dashboard and External Controller: https://manual.nssurge.com/tools/dashboard.html
- Surge Mac CLI: https://manual.nssurge.com/tools/cli.html
- Surge CLI 6.8 update: https://nssurge.com/blog/surge-cli-updates/
- HTTP API: https://manual.nssurge.com/tools/http-api.html
- Detached Profile: https://kb.nssurge.com/surge-knowledge-base/guidelines/detached-profile

## Profile Lines

```ini
external-controller-access = password@127.0.0.1:6170
http-api = key@127.0.0.1:1132
http-api-tls = true
```

Use `127.0.0.1` for local-only access. Use `0.0.0.0` only when LAN access is
intentional, the credential is strong, the network is trusted, and host/router
firewall policy limits exposure.

## External Controller Boundary

Surge Mac 6.8.0 uses `--remote host:port` for a DNS name or IPv4 address and
`--remote [addr]:port` for a bracketed IPv6 address.
Never put the password in argv. Do not use a password-prefixed endpoint form.

For attended use, run the command without a password option and respond to the
secure terminal prompt. For automation, prefer `--password-stdin`; it reads the
password from the first input line. `SURGE_CLI_PASSWORD` is an acceptable
fallback when standard input is unavailable, but environment inheritance and
debug output must be controlled.

```bash
SURGE_CLI=/Applications/Surge.app/Contents/Applications/surge-cli
"$SURGE_CLI" --remote ios-surge.local:6170 status

/usr/bin/security find-generic-password -w -s surge-controller-ios |
  "$SURGE_CLI" --remote ios-surge.local:6170 --password-stdin status

"$SURGE_CLI" --remote '[2001:db8::10]:6170' status
```

Do not enable shell xtrace around any of these commands, and do not capture the
secret manager's output in the task transcript.

Stalled remote connections and finite operations have timeouts. A timeout is
not proof that a mutation failed or succeeded; re-identify the exact target and
read its state before deciding whether a retry is safe. Interactive mode accepts
quoted arguments and backslash escaping for names with spaces or literal
special characters. These parsing forms do not make credentials safe in the
command text.

### Command capability matrix

Surge Mac 6.8.0 provides the expanded command set. Compatible Surge iOS 5.21.0
and Surge tvOS 5.21.0 instances can be operated through `--remote`, subject to
the target platform's available features. A remote benchmark runs on the target,
not on the controlling Mac.

When more than one Surge instance has been inspected in a task, bind every
mutation to one exact target before executing it: explicitly choose local Mac
operation without `--remote`, or one verified remote endpoint with `--remote`.
Never infer the mutation target from the preceding read-only command or reuse a
different device's credential.

| Commands | Boundary | Platform, output, and acceptance |
| --- | --- | --- |
| `status`, `version`, `dump summary` | Read-only snapshot | The full profile path, device/OS details, interface addresses, routers, and DNS data are sensitive. |
| `profile current`, `profile list`, `profile check <name>` | Read-only inspection and validation | Listing and validation are macOS-only. Switching is a mutation covered below. |
| `policy-group list`, `policy-group get <group>`, `policy-group set <group> <policy>` | Inspection or selection mutation | Pass `auto` as the policy to clear a manual override on an automatic group; independently read back the resulting selection. |
| `module list`, `feature list`, `feature get <name>` | Read-only runtime state | Feature availability depends on the target; System Proxy and Enhanced Mode are macOS-only. `module enable <name...>` and `module disable <name...>` accept multiple module names in one operation. |
| `device` | Read-only Gateway Mode inventory or lookup | macOS-only. Device identifiers and MAC addresses are sensitive, as are private addresses in the result. |
| `script list`, `script-log <log-name> <session-id>` | Read-only script metadata and prior execution log | Use identifiers returned in known script execution metadata or provided by the user. `script-log` does not run a script, and `script list` does not supply a replacement session ID. Do not guess a session identifier or rerun a script to manufacture one. Output and exceptions may contain tokens or private request data. |
| `log file <count>`, `log memory <count>`, `log watch`, `logbook <limit>` | Read-only finite retrieval or continuous observation | A finite log retrieval accepts up to 10,000 lines. The persistent file log provides longer history at the configured level; the in-memory log provides more detailed recent entries from all levels. `log watch` streams newly generated, unfiltered logs. Unfiltered logs are sensitive; redact URLs, headers, tokens, identifiers, and private addresses. |
| `benchmark encryption` | Diagnostic workload with no setting change | Measures correctness, integrity, tamper detection, and encryption/decryption performance on the selected local or remote Surge device; it may consume CPU. |
| `test-policy-bandwidth` with `<download/upload> <policy-name>` | Active network workload with no setting change | Run only when explicitly requested because it consumes traffic and bandwidth on the selected local or remote target. |
| `dump policy`, `proxy-runtime-status <line-hash>` | Read-only proxy runtime diagnosis | Includes detailed Tailscale and WireGuard traffic, peer, path, handshake, DERP, Exit Node, error, and MagicDNS state. |
| `environment`, `dump event`, `dump request`, `dump dns`, `dump rule`, `dump profile original` | Existing read-only commands | Request and profile output is sensitive; prefer redacted summaries. |

### Execution and observation boundary

- `script run` executes a named cron script, including a disabled script. Use it
  only with explicit approval for that script because its side effects are
  script-defined. Treat the returned output or exception as the execution
  result; use `script-log` as a read-only follow-up and do not rerun a script to
  manufacture a second verification result.
- `reconnect-device` is macOS-only and actively disrupts one access-point
  client. Use it only with explicit approval after resolving an exact identifier
  or MAC address. After `reconnect-device` returns, use `device` to read back and
  verify that client. If the read-back is inconclusive, report it; do not repeat
  the disruption automatically.
- `log watch` has no natural completion point. Bound the observation window,
  stop the stream explicitly, and do not paste unfiltered output into a task
  transcript. Prefer finite `log file <count>` or `log memory <count>` retrieval
  for routine diagnostics.
- Never directly invoke `log file <count>` or `log memory <count>` from an agent
  tool when its stdout would be recorded. Pipe the stream into a trusted local
  summarizer that emits only redacted fields or aggregate counts; the raw stream
  must not reach the task transcript. Do not use `tee`, and do not retrieve the
  log when safe local summarization cannot be guaranteed.
- `managed-profile update` checks, validates, replaces, and reloads the active
  managed profile. Run it only with explicit approval. Treat the returned state
  as the first result, then use `status` and `profile current` to read back and
  verify the active profile on the exact local or remote target. Do not retry an
  inconclusive update automatically.

### Mutation verification

Surge 6.8 setting commands return the resulting state and use a nonzero exit
status for failures. Still re-query the resulting state independently before
reporting success:

```bash
"$SURGE_CLI" mode set rule
mode_mutation_status=$?
"$SURGE_CLI" mode get
mode_readback_status=$?

"$SURGE_CLI" feature set enhanced-mode on
feature_mutation_status=$?
"$SURGE_CLI" feature get enhanced-mode
feature_readback_status=$?

"$SURGE_CLI" policy-group set 'Group Name' 'Policy Name'
policy_mutation_status=$?
"$SURGE_CLI" policy-group get 'Group Name'
policy_readback_status=$?

"$SURGE_CLI" profile switch 'Profile Name'
profile_mutation_status=$?
"$SURGE_CLI" profile current
profile_readback_status=$?

"$SURGE_CLI" module enable 'Module Name'
module_mutation_status=$?
"$SURGE_CLI" module list
module_readback_status=$?
```

Apply the same read-back rule to `global-policy set`, `module disable`, and
`set <key-path>=<value>`. System Proxy and Enhanced Mode commands wait for the
actual transition to finish; a subsequent `feature get` remains the acceptance
check. Those two features are macOS-only. For remote mutations, add the same
safe `--remote` form and password transport used for the preceding read-only
commands.

Do not gate the read-back on the mutation's exit status. A timeout or nonzero
mutation result may leave the target in either state, so run the independent
read command anyway, preserve both statuses, and report an inconclusive result
instead of retrying the mutation automatically.

## Surge 6.8 Apple NTP Warning

Surge Mac 6.8.0 (11990) contains these fixed UDP/123 targets for its internal
`SGNTPClient` probe:

- `17.253.114.125`
- `17.253.84.251`
- `17.253.114.253`
- `17.253.84.125`
- `17.253.84.123`

Local binary inspection shows the first request starts after 15 seconds, the
probe repeats every 3600 seconds, and each attempt has a 5 seconds timeout. On
2026-08-08 all five fixed targets timed out, while the current address returned
by `time.apple.com` and other NTP servers responded from the same Mac. This
rules out a general UDP/123 failure.

The internal probe does not appear in Surge request records. Existing DIRECT
coverage for Apple's `17.0.0.0/8` therefore cannot be shown to fix the internal
warning, and adding a more specific profile rule is not an evidence-based
remediation. Do not patch the signed Surge app. Preserve the log evidence,
recheck after a Surge update, and treat a target refresh or hostname-based probe
as an upstream Surge fix.

## HTTPS HTTP API

Use the `X-Key` request header. Pass the header through `curl --config -`, not
`curl -H`, so the key does not appear in the process argument list. Verify TLS
with the system trust store or an explicit `SURGE_HTTP_CA`. Do not use `-k` for
routine operation; `SURGE_HTTP_INSECURE=1` is only for a short diagnostic that
must be repeated with verification enabled.

Put `-q` first in every authenticated curl invocation so a user-level curl
configuration cannot inject `insecure`, redirects, verbose output, or tracing.
Disable shell xtrace before reading the profile key.

The implementation in `../scripts/surge-status.sh` is the canonical command
pattern for this repository. Useful documented resources include:

- `/v1/events`: event center.
- `/v1/requests/recent`: recent requests. Treat the response as sensitive.
- `/v1/requests/active`: active requests. Treat the response as sensitive.
- `/v1/profiles/current?sensitive=0`: partially redacted current profile. It may
  still contain controller/API settings and must not be printed or shared.
- `/v1/profiles/reload`: reload current profile.
- `/v1/policies`, `/v1/policy_groups`: policy inspection.
- `/v1/features/mitm`, `/v1/features/rewrite`, `/v1/features/scripting`,
  `/v1/features/capture`: feature state and toggles.

Query parameter `x-key` is acceptable only for special browser cases described
by the official documentation, such as downloading a CA certificate. Do not use
it in scripts because URLs are routinely logged.

## Known Local Quirks

- Local macOS `surge-cli --raw ...` may return `(null)` in some situations.
  Cross-check with listeners, route state, and a TLS-verified HTTP API probe.
- `watch request` only captures traffic that traverses the monitored instance.
- Apple TV can lag behind shared iCloud profile edits. Verify the active
  endpoint rather than trusting file contents.
- `sensitive=0` is not a guarantee that the complete profile response is safe
  to display.

## Portable Local Setup

Override machine- or network-specific values at runtime instead of editing them
into the repository:

```bash
export SURGE_IOS_PROFILE="$HOME/Library/Mobile Documents/iCloud~com~nssurge~inc/Documents/DMIT.conf"
export SURGE_MAC_PROFILE="$HOME/Library/Mobile Documents/iCloud~com~nssurge~inc/Documents/DMIT-Mac.conf"
export SURGE_ATV_PROFILE="$SURGE_IOS_PROFILE" # override if tvOS has its own profile
export SURGE_IOS_HOST="ios-surge.local"
export SURGE_ATV_HOST="apple-tv-surge.local"
export SURGE_HTTP_API_PORT="1132"
export SURGE_HTTP_CA="$HOME/.config/surge/http-api-ca.pem" # only if system trust is unavailable
local-surge-control/scripts/surge-status.sh all
```

`SURGE_PROFILE` remains a compatibility override for an older single-profile
setup. Do not set it in the detached setup above: Mac and iOS have independent
HTTP API and External Controller credentials, and the helper must read each
credential from its matching device profile. Shared content belongs in
`DMIT-Common.dconf`, but that file may still contain sensitive proxy or routing
configuration and must not be printed wholesale.

Never commit live credentials (including `wifi-access-http-auth`), a private
network inventory, CA private keys, or raw request/event/profile output.
