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

## Post-release rollout result

The repository hardening release was deployed later on 2026-07-13:

- Pull request CI and the subsequent `main` push both passed.
- Immutable tag and GitHub Release: `surge-self-v2026.07.13`.
- The five tagged response scripts matched the reviewed local SHA-256 values.
- `main` now requires pull requests and the `validate` status check; force push
  and branch deletion are disabled.
- The obsolete `gh-pages` branch was deleted. GitHub Pages continues to build
  from `main` with HTTPS enforced.
- Private vulnerability reporting is enabled.
- The scheduled managed-rule workflow completed successfully and created no PR
  because all 17 reviewed source pins still matched.

The installed remote iOS module cache did not refresh through the public HTTP
API because Surge exposes module enable/disable state but no module-install or
module-update endpoint. To avoid continuing to run the old broad MITM and
unlimited-response definitions, the audited modules were copied into the shared
iCloud `modules/` directory with versioned names and switched atomically:

- YouTube Self 2026.07.13
- Instagram Self 2026.07.13
- 高德地图 Self 2026.07.13
- 扫描全能王 Self v2 2026.07.13
- 京东 Self 2026.07.13

The previous five installed module entries remain available but disabled. The
existing 基础去广告模块 remains enabled because its rule payload did not require
a script-definition migration. The final effective profile confirmed:

- all five script paths use `surge-self-v2026.07.13`;
- all response size limits are finite;
- the narrowed MITM host list is active;
- every tagged script resource reports `ready=1`;
- Apple TV media rules precede Apple system DIRECT rules;
- the Apple TV ruleset reports `ready=1` after the initial Pages deployment
  race was resolved by a successful external-resource refresh;
- the final recent-request window contains no failed or rejected requests.

`allow-wifi-access` remained unchanged, as required by the explicit release
exception above.

## Subsequent cloud-module migration

The owner later chose cloud-installed modules for easier setup on replacement
and additional devices. A live check after the old cloud entries were manually
re-enabled showed that Surge had reused their stale URL-backed definitions:
they still had unlimited response sizes and pre-release script URLs. The public
module files were therefore moved to new canonical URL paths and renamed to
`YouTube`, `Instagram`, `高德地图`, `扫描全能王`, and `京东`. The new URLs must be
installed and verified before the old `Self`-named cache entries are removed.
