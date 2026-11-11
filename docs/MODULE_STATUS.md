# Module Status Matrix

This file records the public module lifecycle independently from the install URL.
The `main` branch contains the latest reviewed module definitions, while response
scripts used by a stable module are pinned to an immutable repository tag.

| Module | Channel | Last live evidence | Required companion | Scope note |
| --- | --- | --- | --- | --- |
| YouTube | stable | 2026-07-13, `.4` script execution and native DOMAIN-SET routing | none | Playback ads, feed cards, background playback and PiP |
| Instagram | limited | 2026-07-13, native HTTPS fallback and netseer rejection | none | Web endpoints only; pinned native API stays outside MITM |
| 高德地图 | candidate | 2026-07-13, m5-x MITM and telemetry endpoints | 基础去广告模块 recommended | Conservative first-party response cleanup |
| 扫描全能王 | candidate | layered architecture validation | 基础去广告模块 required | First-party operations and ad containers only |
| 京东 | stable | 2026-07-12, JD 15.8.50 | 基础去广告模块 recommended | Whitelisted `functionId` values only |
| 微信 | candidate | 2026-07-13, iOS load and synthetic response-engine pass; real WeChat flow pending | 基础去广告模块 recommended | Official-account ads and exact mini-program ad hosts; native MMTLS feeds excluded |
| 小红书 | candidate | synthetic tests only; Xiaohongshu 9.43 live regression pending | none | Explicit structured ads only; save/watermark and search UI excluded |
| 微博 | candidate | synthetic tests only; Weibo 16.8.1 live regression pending | none | Endpoint/container allowlists; account, membership, messages and wallet excluded |
| 基础去广告模块 | stable | 2026-07-13 Mac/iOS domain review | none | Domain rules only; no script or MITM |

## Status meanings

- `stable`: automated checks pass and the current behavior has live-device evidence.
- `candidate`: automated checks pass, but a fresh live-device regression pass is
  still required before the module receives an independent stable tag.
- `limited`: the module is stable only within the explicitly documented technical
  boundary. It must not be presented as covering pinned native APIs.

## Current distribution and validated baseline

- Active distribution: `surge-self-v2026.07.27.1`. Its manifest records
  `live_device_validation: pending`; active identifies the canonical module pin
  and must not be interpreted as stable or rollback-eligible.
- Last live-device-validated bundle: `surge-self-v2026.07.13.4`. It is inactive
  and explicitly `rollback_eligible: true`.
- Supported runtime used for the `.07.13.4` validation:
  - Surge Mac 6.6.0 (11270)
  - Surge iOS 5.19.0 (3727)
- The public module install URLs remain under `main`; each script-backed module
  currently pins its `script-path` to the active `.07.27.1` distribution. The
  pending 07-27 live-device regression is recorded in `CHANGELOG.md` and must be
  completed before that bundle is described as stable.
- Xiaohongshu and Weibo remain under `rewrite/Surge/candidates/`. Their module
  definitions target the `surge-self-v2026.11.11` candidate (which superseded
  `surge-self-v2026.11.10` to include YouTube protobuf feed scanning latency
  optimizations alongside the `account/get_setting` inflation fix) and are not
  public install entries. They may move to
  canonical `main` paths only after manifest registration, immutable tag
  creation, a recorded passed device run, and distribution activation.

## Rollback certification evidence for surge-self-v2026.07.13.4

- Certification scope: the complete six-script bundle recorded by the immutable
  `.07.13.4` manifest, including the current module paths for YouTube, Instagram,
  Amap, CamScanner, JD, and WeChat.
- Integrity basis: the release verifier reconstructs every recorded script from
  `release_commit` and checks its SHA-256 before the bundle can remain eligible.
- Runtime basis: the final Surge Mac 6.6.0 and Surge iOS 5.19.0 rollout is recorded
  in the append-only live-device evidence section referenced by the manifest.
- Eligibility decision: `.07.13.4` is the last complete, live-device-passed bundle
  available as an emergency rollback target. Its eligibility must be revoked in a
  separate release transaction if a later runtime or module contract makes this
  compatibility evidence obsolete.

## Current iOS rollout evidence

- The effective profile contains 205 top-level rules, including nine adjacent
  `DOMAIN-SET` / residual `RULE-SET` pairs with the original policies and order.
- All 36 external resources are ready: 9 domain sets, 21 rule sets, and 6 scripts.
  This live inventory is separate from the 22 managed-source tracking inputs;
  replacing the Claude URL is one-for-one and does not add a runtime resource.
- Controlled Microsoft, YouTube, and PayPal requests completed successfully and
  matched `microsoft.domainset`, `youtube.domainset`, and `paypal.domainset`.
- The official module API could not refresh the installed cloud definition, so
  an iCloud-local `.4` fallback was used briefly. After the owner ran Surge's
  manual module update, the canonical cloud `YouTube` entry became the sole
  enabled YouTube module and the fallback file was removed.
- The final cloud module expands to exactly one `.4` response script with
  `debug=false`. A controlled valid-JSON player response matched
  `youtube.domainset`, was modified by `youtube.self.response (YouTube)`, and
  completed without failure or rejection.

The first 2026-07-13 iOS rollout used versioned iCloud-local module definitions
because the official remote API cannot update an installed module definition.
The maintained public module URLs are now the permanent device-management
entries: existing devices update those subscriptions in place, while new
devices install the same URLs once. Display names no longer contain `Self`, and
all response scripts remain pinned to the immutable public tag.

Changing a module from `candidate` to `stable` requires updating this matrix in
the same pull request as the release notes.

## Live-device evidence for surge-self-v2026.11.11

- Registered payload commit: `4b1a7ce93998cca6c1b5804e44be6cbb56daf27b`.
- Device and runtime: `iPhone18,3` running iOS `27.2 (24B119)` with
  `Surge iOS 5.23.0 (3867)` (`Core 6010000`), exercised between
  `2026-11-11 11:32 +08:00` and `2026-11-11 12:01 +08:00`; Surge Mac (`6.9.1`,
  `Core 6009001`) remained free of candidate modules throughout.
- Readiness and script pinning: enabled `YouTube (候选 2026.11.11)`,
  `小红书 (候选 2026.11.11)`, and `微博 (候选 2026.11.11)` on iOS; refreshed all
  external resources (`39/39` reported `ready=1`, `0` load errors) and verified
  `script list` pinned `youtube.self.response`, `xiaohongshu.self.response`, and
  `weibo.self.response` to immutable tag `surge-self-v2026.11.11` (`?v=20261111-1`).
- Exercised release change surface and result (`passed`):
  - Three live `youtube.self.response` sessions at `2026-11-11 11:49:16–11:49:21 +08:00`
    (`A0B2543E`, `70A3AF6D`, `BE1F876A`) completed cleanly and returned rewritten
    protobuf bodies (`result.body = true`, `18.4 ms` on compact response and
    `420.4 ms` / `453.6 ms` on large rewritten surfaces, down from pre-optimization
    `957.5 ms` / `586.7 ms`), with zero script errors, zero `protobuf-inflation-abort`,
    and zero `browse-schema-safety` aborts.
  - Surge iOS `file` and `memory` logs recorded zero warnings or errors across the
    validation window, confirming bundle integrity and readiness for canonical
    cloud activation.
