# Surge Control Reference

## Official Docs

- External Controller: https://manual.nssurge.com/others/external-controller.html
- Surge Mac CLI: https://manual.nssurge.com/others/cli.html
- HTTP API: https://manual.nssurge.com/others/http-api.html
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

Common External Controller commands include `environment`, `dump event`, `dump
request`, `dump dns`, `dump policy`, `dump rule`, `dump profile original`,
`reload`, `test-network`, `test-policy`, and `external-resource update all`.

Do not automate a remote controller probe with the current `surge-cli`. Its
remote syntax requires `password@host:port` in an argv value, so the password
can be observed in process listings and may be copied into logs or transcripts.
The bundled helper therefore reports this surface as skipped and uses HTTPS
HTTP API for automated checks.

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
