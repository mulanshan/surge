# Runtime Audit - 2026-07-13

This snapshot records the live state used to design the repository hardening
release. It intentionally excludes request URLs, headers, credentials, account
data, and raw response bodies.

## Versions

- Surge Mac 6.6.0, build 11270
- Surge iOS 5.19.0, build 3727
- Shared profile: `DMIT.conf` in the Surge iCloud container

Both versions matched the current official release channels on the audit date.

## Control and feature state

- Mac External Controller and HTTPS HTTP API: reachable
- iOS External Controller and HTTPS HTTP API: reachable
- iOS MITM, Rewrite, and Scripting: enabled
- Mac Scripting: enabled
- Mac MITM and Rewrite: disabled

The difference is intentional. Surge officially treats module enablement as
device-local state even when the base profile is shared through iCloud.

## iOS modules

Enabled during the audit:

- HomeKit Accessories Quirk
- YouTube Self
- Instagram Self
- 高德地图 Self
- 扫描全能王 Self v2
- 京东 Self
- 基础去广告模块

The legacy Fanqie compatibility module entry was not enabled alongside its
current replacement. The retired Instagram Feed compatibility entry was also
disabled during the audit and has since been removed from the repository.

## External resources and logs

- Every listed script and ruleset external resource reported `ready=1`.
- The recent iOS request window contained no failed or rejected requests.
- The recent window did not contain enough target API requests to claim a fresh
  live regression pass for every application module.
- No script error was present in the current event window.
- Mac request failures observed during the audit were stale LAN target probes,
  not application or proxy failures.

## Explicit exception

The iOS LAN proxy access behavior is intentionally unchanged by the hardening
release. `allow-wifi-access` and proxy authentication settings are outside the
scope of this release by owner decision.

## Release verification requirement

After publishing the stable tag:

1. Update all external resources on iOS.
2. Confirm every script resolves through the tagged URL and remains `ready=1`.
3. Confirm the current module set has no duplicate or retired entries.
4. Use targeted, redacted app sessions to promote candidate modules in
   `docs/MODULE_STATUS.md` to stable.

## Later rollout records

Rollout and release records that were previously appended to this snapshot
have moved to [../CHANGELOG.md](../CHANGELOG.md) (2026-07-13 entries). This
file is frozen as the 2026-07-13 point-in-time audit.
