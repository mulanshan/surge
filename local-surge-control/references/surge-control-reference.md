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
| `profile current`, `profile list`, `profile check <name>`, `profile section <list\|get\|set>` | Read-only inspection, validation, or atomic section replacement | Listing and validation are macOS-only; `profile section` requires controller protocol 31+ (Surge Mac 6.11.0+). `profile section get <name>` prints unredacted proxy secrets and must never enter a task transcript. Switching is a mutation covered below. |
| `policy-group list`, `policy-group get <group>`, `policy-group set <group> <policy>`, `policy-avoid <list\|add\|remove\|clear>` | Inspection, selection mutation, or temporary automatic-group avoidance | Pass `auto` as the policy to clear a manual override on an automatic group; `policy-avoid` requires controller protocol 40+ and clears on restart. Independently read back the resulting selection or avoidance list. |
| `module list`, `module show <name>`, `feature list`, `feature get <name>` | Read-only runtime state and module inspection | Feature availability depends on the target; System Proxy and Enhanced Mode are macOS-only. `module show` requires Surge Mac 6.11.0+. `module enable <name...>` and `module disable <name...>` accept multiple module names in one operation. |
| `rule match`, `rule explain` | Read-only offline routing evaluation | On controller protocol 41+ (Surge Mac 6.11.0+), returns `rule-source` (profile file/line or module) and `matched-sub-rules` inside `RULE-SET`/`DOMAIN-SET`. |
| `capture-filter <list\|get\|set>`, `capture-session <list\|dump\|data>` | Capture filter management and saved capture inspection | Requires controller protocol 36+/37+ (Surge Mac 6.11.0+). `capture-session data` returns raw HTTP request/response bodies and must never enter a task transcript unfiltered. |
| `dump traffic-stat-breakdown`, `dump traffic-stat-records` | Read-only aggregated traffic rankings | Requires controller protocol 38+/39+ (Surge Mac 6.11.0+); summarize sensitive hostnames before quoting. |
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
- `/v1/policies`, `/v1/policy_groups`, `/v1/policies/avoided`: policy inspection
  and temporary automatic-group avoidance (`include_external=true` supported on
  `/v1/policies` in 6.11+).
- `/v1/capture/filters`, `/v1/capture/sessions`, `/v1/capture/sessions/requests`,
  `/v1/capture/sessions/data`: capture filter and saved session endpoints (6.11+).
  Treat session request lists and raw body payloads as sensitive.
- `/v1/features/mitm`, `/v1/features/rewrite`, `/v1/features/scripting`,
  `/v1/features/capture`: feature state and toggles.
- `/v1/mcp`: Model Context Protocol Streamable HTTP endpoint (`http-api-mcp = true`
  in `[General]`, Surge Mac 6.11.0+ / iOS 6.0+). Enable `http-api-mcp = true`
  **only** on loopback-bound `127.0.0.1:1132` (`DMIT-Mac.conf`) with TLS enabled;
  keep it disabled on LAN-exposed `0.0.0.0:1132` profiles (`DMIT.conf`,
  `DMIT-ATV.conf`). Local Stdio MCP clients should use
  `../scripts/surge-mcp-bridge.py` so `X-Key` is read at runtime and never stored
  in `mcp_config.json` or process `argv`. MCP tools `get_profile`,
  `get_profile_section`, `get_captured_body`, `get_capture_session_body`, and
  `get_logs` carry secret-bearing data and must be summarized/redacted locally.

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
export SURGE_ATV_PROFILE="$HOME/Library/Mobile Documents/iCloud~com~nssurge~inc/Documents/DMIT-ATV.conf"
export SURGE_IOS_HOST="ios-surge.local"
export SURGE_ATV_HOST="apple-tv-surge.local"
export SURGE_HTTP_API_PORT="1132"
export SURGE_HTTP_CA="$HOME/.config/surge/http-api-ca.pem" # only if system trust is unavailable
local-surge-control/scripts/surge-status.sh all
```

For `all`, Mac and iOS are always checked, and `SURGE_IOS_HOST` is required.
Apple TV is checked only when `SURGE_ATV_HOST` is explicitly set. A missing
`SURGE_ATV_HOST` is an intentional `SKIP` and does not make `all` fail. Mac,
iOS, and Apple TV each use their matching profile credential; never reuse one
device's credential for another.

`SURGE_PROFILE` remains a compatibility override for an older single-profile
setup. Do not set it in the detached setup above: Mac, iOS, and Apple TV have
independent HTTP API and External Controller credentials, and the helper must
read each credential from its matching device profile. Shared content belongs
in `DMIT-Common.dconf`, but that file may still contain sensitive proxy or
routing configuration and must not be printed wholesale.

Never commit live credentials (including `wifi-access-http-auth`), a private
network inventory, CA private keys, or raw request/event/profile output.

## Surge Mac 6.9.1 / iOS and tvOS 5.23.0 Notes

Verified on 2026-11-10 against the local Mac (6.9.1, build 12290), iOS 5.23.0
(3867) and tvOS 5.23.0 (3869). All three report controller protocol 25.

- Smart groups (Mac 6.9+) learn from TCP and UDP results and mark a connection
  that receives no response within three seconds as failed. Inspect the
  learned state with `dump smart-group-info`; keep Smart members concrete
  proxies rather than nested groups.
- Group-level `underlying-proxy` is available on 6.9+.
- The HTTP API exposes Prometheus metrics on Mac and iOS; the tvOS instance
  returns 404 for `/v1/metrics`.
- tvOS 5.23.0 accepts `status`, `version`, `dump performance`, `dump summary`,
  `feature list`, `policy-group`, `rule match`, `rule explain`, `rule temp`,
  `external-resource list|update` and `log file`. It returns `Unsupported
  command` for `module list`, `logbook` and `update-profile`, and `log memory`
  is empty.
- A tvOS profile cannot be replaced from the Mac CLI. Deploy it from Surge iOS.
  Until then, interim rule changes can be applied with `rule temp add`; they
  precede profile rules and are discarded when the tvOS engine restarts. Proxy,
  group-type and `[General]` changes still require a deployment.
- The VS Code Surge Language Support extension starts `surge-cli lsp --stdio`,
  which requires Mac 6.10.0 or later. On 6.9.1 it provides highlighting only;
  validate with `surge-cli --check <profile>`.
- The hourly `SGNTPClient` warning described above is still present on 6.9.1.

## Surge Mac 6.11.0 / Cross-Version Dual-Stack Notes

Verified on 2026-11-17 against local Mac (6.11.0, build 12800, Core `6011000`,
controller protocol `41`), while App Store stable iOS 5.23.0 (3867) and tvOS
5.23.0 (3869) remain at Core `6010000` / controller protocol `25` (Surge iOS 6.0
is in TestFlight).

- **Cross-version detached profile rule**: Keep shared `DMIT-Common.dconf`
  compatible with Core `6010000` (`5.23.0`) until iOS/tvOS 6.0 reaches App Store
  stable. Put 6.11-only `[General]` keys (`http-api-mcp = true`,
  `log-file-size-limit`) in `DMIT-Mac.conf` only.
- **Adaptive QUIC**: Setting `block-quic = auto` in all three `[General]`
  profiles is valid on both 5.23.0 and 6.11.0, and automatically activates
  `adaptive` mode for non-DIRECT policies on Mac 6.11.0 (and future iOS/tvOS 6.0)
  while preserving Snell v6 zero-wait UDP.
- **Dual-stack IPv6**: All three profiles run `ipv6 = true` and `ipv6-vif = auto`
  so native China Telecom `/64` SLAAC+RDNSS traffic uses direct IPv6 while VIF
  prevents raw IPv6/WebRTC bypass leaks on proxied destinations.
- **Mac listener & MCP hardening**: `DMIT-Mac.conf` binds `http-listen`,
  `socks5-listen`, `http-api`, and `external-controller-access` strictly to
  `127.0.0.1`, allowing `http-api-mcp = true` safely over local TLS (`1132`) via
  `scripts/surge-mcp-bridge.py`.
- **VS Code LSP**: On Mac 6.10.0+, `SurgeNetworks.surge-language-support` runs
  `surge-cli lsp --stdio` offline and ignores module `#!system` / `#!requirement`
  headers during editor diagnostics so iOS-only `.sgmodule` files validate on Mac.

## Surge Mac 6.12.0 & Multi-Client DNS Notes

Verified on 2026-11-19 against local Mac (6.12.0, build 12880, Core `6012000`,
controller protocol `43`), alongside iPhone (`5.23.0`, build 3867), iPad
(`5.23.0`, build 3867), and Apple TV (`5.23.0`, build 3869):

- **Shared iOS/iPadOS shell**: Both iPhone and iPad run `DMIT.conf` from iCloud
  Drive; verify module inventory on both devices so retired third-party modules
  do not linger on secondary iPadOS instances.
- **Public DoH `429` mitigation**: Sharing one residential NAT IP across four
  Surge instances plus periodic `url-test` groups trips DNSPod public DoH
  (`https://1.12.12.12/dns-query`) `HTTP 429` / `502` rate limits. Use dual
  AliDNS DoH (`https://223.5.5.5/dns-query, https://223.6.6.6/dns-query`) in
  `encrypted-dns-server`, pin `*.mulanshan.uk = server:119.29.29.29` in `[Host]`,
  and prefer `smart` over `url-test` for large external `policy-path` node lists.

## Surge 6 Unified Core 6012000 / Protocol 45 Notes

Verified on 2026-11-20 against local Mac (`6.12.0`, build `12900`, Core
`6012000`, controller protocol `45`, macOS `27.2.1`) and Apple TV (`6.0.1`,
build `4039`, Core `6012000`, controller protocol `45`, tvOS `27.2.1`), with
iPhone and iPad upgraded to Surge 6:

- **Unified Core & VLESS**: Mac `6.12.0 (12900)` and tvOS `6.0.1 (4039)` both
  report Core `6012000` / protocol `45`, matching Surge iOS/iPadOS 6. Native
  VLESS policy groups (e.g., `自留地`) are now supported across all Surge 6
  clients.
- **Zero-warning DoH confirmation**: Persistent logs on both Mac and Apple TV
  recorded `0 WARNING / 0 ERROR` after switching to dual AliDNS DoH
  (`223.5.5.5` / `223.6.6.6`), with all 32 Apple TV external resources `ready`
  and `7.1 MB` runtime memory.
- **Loopback MCP live verification**: `scripts/surge-mcp-bridge.py` verified
  end-to-end against `https://127.0.0.1:1132/v1/mcp` using `/usr/bin/python3`
  with TLS verification and runtime `X-Key` lookup, exposing 72 native Surge MCP
  tools while keeping `http-api-mcp` disabled on LAN-bound `DMIT.conf` and
  `DMIT-ATV.conf`.
