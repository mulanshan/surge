# Changelog

Release and rollout records for this repository. Runtime audit documents under
`docs/` are frozen point-in-time snapshots; ongoing change history lives here.

## 2026-08-15

Unreleased Xiaohongshu and Weibo candidate modules:

- Added self-authored, single-script candidates for Xiaohongshu 9.43 and Weibo
  16.8.1 after reviewing current Surge documentation, Apple version metadata,
  and maintained community implementations from fmz200, zirawell, QingRex and
  ddgksf2013.
- Xiaohongshu removes only explicitly marked entries from selected feed,
  search-result, note and splash containers. Save/watermark switches, search UI,
  generic system configuration and write endpoints are deliberately excluded.
  Weibo uses endpoint/container double allowlists and excludes profile, account,
  membership, message, notification and wallet-adjacent APIs.
- Excluded third-party runtime code, mutable `main` script URLs, raw-body logs,
  signed-media persistence, broad first-party domain rejection, and Weibo
  membership/skin/icon mutation.
- Both modules remain under `rewrite/Surge/candidates/` and point to the planned
  `surge-self-v2026.08.15` bundle. Before the immutable tag exists they are not
  installable. After tag creation they are Surge iOS test entries only; they must
  not be installed in Surge Mac or advertised as public/stable until current
  iPhone live-device regressions pass and activation completes.

## 2026-08-13

Upstream drift notification hardening:

- Classified reviewed-source drift separately from generator or network errors.
  Scheduled checks now maintain one deduplicated maintenance issue for ordinary
  drift while genuine execution failures still fail the workflow.
- Reviewed the latest Blackmatrix Apple tracking change as ordering-only after
  normalization, then refreshed the immutable Blackmatrix commit pins through
  the existing generated-rule workflow.
- Added structured workflow contracts and regression tests so drift cannot be
  silenced with `continue-on-error` or by swallowing unexpected exit statuses.

## 2026-08-09

Unreleased stability hardening:

- Added a reproducible Claude/Anthropic managed rule set pinned to Blackmatrix
  commit `ccc2d6b` and SHA-256, while retaining the active `hinet` policy.
- Isolated Mac, iOS, and Apple TV HTTP API credentials in the status helper;
  Apple TV now defaults to `DMIT-ATV.conf`, with legacy single-profile behavior
  and explicit profile overrides covered by behavior tests.
- Runtime gate: merge and verify the hosted `generated/claude.list` first, then
  replace the active moving Claude URL one-for-one, reload, and read back each
  explicit target. Repository checks alone do not complete that rollout.
- Device gate: iPhone and Apple TV verification remains pending until their
  current trusted LAN addresses are explicitly supplied.

## 2026-07-27

Repository-wide audit remediation (PRs #15–#21), bundles `surge-self-v2026.07.27`
and `surge-self-v2026.07.27.1`:

- Reviewed managed-source refresh: all blackmatrix7 inputs repinned to commit
  `8f67b64` (Apple.list comment/ordering change only), Sukka Telegram IP
  snapshot refreshed, clearing the drift alarms ongoing since 2026-07-16.
- YouTube module hygiene: ~410 lines of dead code removed, overfitted brand
  markers dropped, DEFAULTS aligned with the module argument, text fallback
  hardened with a card-size floor and exact badge strings, and the hand-written
  UDP REJECT rules replaced by Surge's documented auto-quic-block behavior.
  Released as `surge-self-v2026.07.27`.
- Archived-feature recovery: captionLang works again on JSON player responses
  (`&tlang=` translated caption track), eight curated ad/promotional renderer
  keys restored, and script/MITM coverage extended to `m.youtube.com` and
  `music.youtube.com`. Released as `surge-self-v2026.07.27.1`.
- License separation: the Apple managed set split into `apple-bm7.list`
  (GPL-2.0-only) and `apple-sukka.list` (AGPL-3.0-only).
- Test/CI hardening: hand-kept count ledgers replaced by metadata-derived
  expectations, fanqie three-copy consistency test, domain-before-IP ordering
  invariant, a syntax gate for every distributed rule payload
  (`scripts/test_rule_list_syntax.py`), and CI now fails when a test suite
  silently disappears. Documented that `surge-cli --check` does not validate
  external rule resources.
- Canonical alignment: `rule-section-managed.conf` declares the active profile
  as the single source of truth, gains the live-only references, and drops the
  nonexistent `绿云` policy name. New runtime audit snapshot
  `docs/RUNTIME_AUDIT_2026-07-27.md`.
- Governance: dependabot updates merged (setup-node v7, checkout v7.0.1,
  setup-python v7) with pinning assertions made structural; stale branches
  pruned.

Pending: iOS live-device regression for both 07-27 bundles
(`docs/MODULE_STATUS.md` evidence entry).

## 2026-07-15

Supply-chain hardening (PR #14, commit `25cbc75`): dependabot for GitHub
Actions, daily pinned-upstream drift monitoring, third-party license text
hashing, `releases/retired-tags.json`, and the SECURITY.md supply-chain
provisions.

## 2026-07-13

Bundles `surge-self-v2026.07.13` (later retired-moved) through
`surge-self-v2026.07.13.4`. The following records were migrated verbatim from
`docs/RUNTIME_AUDIT_2026-07-13.md`, where they had accumulated as appendices.

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

The owner later chose permanent cloud subscriptions for easier setup on
replacement and additional devices. A live check after the cloud entries were
manually re-enabled showed that their installed definitions were still stale:
they had unlimited response sizes and pre-release script URLs. The fixed public
URLs are therefore retained as the canonical identities so every installed
device can use Surge's normal module update action. Their display names are now
`YouTube`, `Instagram`, `高德地图`, `扫描全能王`, and `京东`; the URL paths remain
stable for one-time installation and subsequent in-place updates.

## Protected patch release and final iOS regression

A later integrity audit found that `surge-self-v2026.07.13` had been moved after
its GitHub Release was published. The Release recorded Instagram SHA-256
`21b5cec6...`, while the moved tag served a different script. That tag is now
marked `retired-moved` and protected against any further update or deletion.

The replacement release completed on 2026-07-13:

- pull request `#5` passed the protected `validate` check and merged to `main`;
- protected tag and GitHub Release: `surge-self-v2026.07.13.1`;
- a repository tag ruleset blocks update and deletion of every
  `refs/tags/surge-self-v*` ref with no bypass actor;
- release manifests, CI checks, tag/release event checks, and a scheduled remote
  audit verify the exact five script SHA-256 values;
- all five canonical module files stayed at their original `main` install URLs.

The existing iOS module subscriptions were updated in place rather than
reinstalled. Final effective-profile checks on the explicitly selected iOS
Surge endpoint showed five
references to `surge-self-v2026.07.13.1`, zero references to the retired tag,
and 26 of 26 external resources ready.

Targeted regression results:

- 高德地图: a temporary no-rewrite probe first confirmed that
  `m5-x.amap.com` supports MITM and carries `shield/alc/collect` plus
  `shield/amapstream/upload`. The final canonical module then matched both
  paths repeatedly with `modified=true`, no rejected/failed business request,
  and no MITM or script error. The temporary probe was disabled and removed.
- Instagram: native HTTPS connections remained healthy; expected QUIC attempts
  fell back to HTTPS. The narrowed logical rule matched six verified
  `netseer-ipaddr-assoc` requests only when the host also ended in `fbcdn.net`,
  while 27 sampled HTTPS requests completed normally and no unexpected failure
  appeared.
- Both module debug arguments were returned to `false` after validation.

The iOS module set ended as `HomeKit Accessories Quirk`, `YouTube`,
`Instagram`, `高德地图`, `扫描全能王`, `京东`, and `基础去广告模块`, with no legacy or
temporary probe entry remaining.

## Basic web advertising hardening and iOS rollout

Pull request `#9` later expanded the canonical Basic AdBlock module from 44 to
94 auditable domain rules. The new layer covers common programmatic advertising,
pop-up/redirect networks, and exact advertising hosts observed in the current
iPhone web session. It still contains no JavaScript, MITM, URL rewrite, Map
Local, broad application business domains, or media CDN rules.

The fixed `main` install URL and commit-specific GitHub payload both matched
SHA-256 `8c961ebc...` after the merge. Surge's `external-resource update all`
and profile reload did not update the installed cloud-module cache: the remote
`基础去广告模块` entry still expanded to 44 rules. The validated payload was therefore
copied into the shared iCloud `modules/` directory as
`basic-adblock-web-20260713.sgmodule`, with the device-local display name
`基础去广告模块 网页增强 2026.07.13`. The old cloud entry was disabled and the local
enhanced entry enabled atomically.

The final effective iOS profile contained all 94 enhanced rules and none from
the disabled cloud entry. Controlled requests through the iPhone LAN proxy
confirmed `REJECT` for `tsyndicate.com`, `amazon-adsystem.com`,
`go.mayzaent.com`, and `mavrtracktor.com`; `cdnjs.cloudflare.com` remained
allowed and returned HTTP 200. No unexpected non-REJECT request failure or
error-like Surge event was present after the switch.

When the iPhone Surge UI eventually refreshes the canonical cloud subscription
to 94 rules, the durable cleanup path is to enable `基础去广告模块`, disable the
versioned local entry, and remove the local `.sgmodule` file only after the
effective-profile rule count is reconfirmed.

## Native DOMAIN-SET and YouTube log hardening rollout

Pull request `#11` and immutable release `surge-self-v2026.07.13.4` completed on
2026-07-13. The release, tag payload, GitHub Release checksum block, historical
release audit, pull-request CI, `main` CI, and Pages deployment all passed.

Nine domain-heavy mixed rulesets were split into 7,391 native DOMAIN-SET entries
and 175 residual rules. The original 7,566-rule compatibility snapshots remain
available for rollback, and automated tests reconstruct every original rule
exactly from each optimized pair. The live profile retained its Pages URLs,
policies, options, and first-match order. Its optimized downloaded text is
124,352 bytes instead of 212,233 bytes for the nine full lists, a 41.4% decrease.

After a timestamped iCloud profile backup and local `surge-cli --check`, the iOS
profile was reloaded and all external resources refreshed. A first reload raced
the new resource cache and recorded transient load-failure events; after the
resources became ready, a clean reload produced no new event. Final state:

- 36 of 36 external resources ready: 9 domain sets, 21 rule sets, and 6 scripts;
- 205 top-level effective rules, including all 18 optimized pair entries;
- successful controlled requests matched `microsoft.domainset`,
  `youtube.domainset`, and `paypal.domainset` with their intended policies;
- no failed or rejected controlled request after the final switch.

The YouTube script now routes normal JSON, protobuf, schema-cleanup, and
passthrough diagnostics through strict `debug === true` logging. Safety aborts
and top-level errors remain unconditional. Synthetic tests cover debug false,
debug true, the string value `"false"`, schema safety, growth/inflation aborts,
and malformed input.

The official module API can toggle modules but cannot refresh an installed cloud
definition. The cloud `YouTube` entry therefore remained on the previous script
pin after an off/on cycle and full external-resource refresh. It was disabled
atomically and replaced by one iCloud-local fallback named `YouTube 稳定 .4`.
The final effective profile contains exactly one YouTube response script, pinned
to `.4` with `debug=false`; a controlled player request matched
`youtube.domainset`, executed that script, and was modified without request
failure. The fallback file should be removed only after the canonical cloud
subscription is updated to `.4` and the single-script invariant is reconfirmed.

The owner then used Surge's manual module-update action. Final verification
confirmed that the canonical cloud `YouTube` module is enabled, the local
fallback is no longer available, and all eight intended modules remain enabled.
The effective profile contains one YouTube response script from the cloud
module, pinned to `surge-self-v2026.07.13.4` with query `v=20260713-2` and
`debug=false`. All 36 resources remained ready, the profile retained 205
top-level rules, and a new controlled player request was modified by
`youtube.self.response (YouTube)` without failure or rejection. A clean reload
after the cloud switch produced no new failure-like event.
