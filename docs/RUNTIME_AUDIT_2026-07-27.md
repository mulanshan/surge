# Runtime Audit — 2026-07-27

Point-in-time snapshot of the live Surge runtime versus this repository.
Supersedes the baseline in `RUNTIME_AUDIT_2026-07-13.md`; that file is frozen
as a historical snapshot and must not receive further appends.

## Runtime baseline

- Surge Mac 6.7.0 (build 11730) on macOS 26.5.2.
- Active profile: `DMIT-Mac.conf` from the iCloud container. Mac (`DMIT-Mac.conf`),
  iOS (`DMIT.conf`), and Apple TV (`DMIT-ATV.conf`) are thin `[General]` shells
  that `#!include` the shared `DMIT-Common.dconf` for Proxy/Proxy Group/Rule/MITM.
- Mac feature switches: MITM, Rewrite, and Scripting all disabled. Enabled
  modules are five `%INTERNAL%` ones only; the local "Installed Modules"
  directory and the iCloud `modules/` directory are both empty.
- Division of labor: this repository's `.sgmodule` files and pinned scripts
  serve the iOS device only. Mac logs therefore say nothing about module
  health; module regressions must be assessed from the iOS side.
- Active bundle: `surge-self-v2026.07.27` (supersedes `surge-self-v2026.07.13.4`).
  iOS module refresh and the live-device evidence entry in `MODULE_STATUS.md`
  are pending as of this snapshot.

## Profile ↔ repository alignment

- The 30+ RULE-SET/DOMAIN-SET references in `DMIT-Common.dconf` point at this
  repository's GitHub Pages mirror (`mulanshan.github.io/surge`), which builds
  from `main`.
- The Apple mirror reference was split into `apple-bm7.list` + `apple-sukka.list`
  (license separation) in both the profile and `rule-section-managed.conf`.
- `rule-section-managed.conf` now states the authority relationship explicitly:
  the active profile is the single source of truth; the checked-in section is a
  reference template aligned with it.
- Known intentional divergence kept by owner decision: the profile's direct
  reference to the blackmatrix7 `master` Claude.list (upstream path currently
  404) stays as-is.

## Runtime changes recorded in this audit

- DNS: `dns-server = system` (which resolved to an empty plaintext list at
  runtime and caused ~1047 "No available upstream DNS server" incidents in the
  July logs) replaced with `223.5.5.5, 119.29.29.29, system` on all three
  shells; `h3://dns.alidns.com/dns-query` added as an encrypted-DNS transport
  fallback; `[Host]` pins `*.mulanshan.uk` to 119.29.29.29.
- Proxy groups: new `HK优先 = fallback, HK, us` group added and exposed as the
  first option of `Proxy` so the hk relay chain no longer lacks failover
  (motivated by the 2026-07-20 17:44 retry storm, ~1764 log lines in 2 minutes).
- Housekeeping: stray profile backups (13-file AuditBackups snapshot, four
  iCloud `.bak` files, `Default.conf` leftovers) consolidated into a single
  0600 archive under the local Surge support directory; the stale 2026-04
  clone of this repository was bundled and removed.

## Open items

- `chat` / `nl` / `cpa` subdomains of the personal zone return NXDOMAIN from
  the authoritative DNS (Cloudflare): records are missing server-side; client
  `[Host]` pinning cannot fix that.
- The 魔戒 subscription uses a bare-IP HTTPS endpoint whose IP-SAN certificate
  expires 2026-08-02; expect update failures to recur unless the provider
  renews on time or supplies a domain URL. The second subscription profile
  uses the same bare-IP pattern (certificate valid until 2026-09-01).
- The running Surge Mac instance authenticates its HTTP API with an
  app-managed key, not the profile's `http-api` line: API calls using the
  profile value are rejected with "invalid key". Tools that extract the key
  from the profile (local-surge-control) will not work against this instance
  until the two are reconciled.
