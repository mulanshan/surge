# Module Status Matrix

This file records the public module lifecycle independently from the install URL.
The `main` branch contains the latest reviewed module definitions, while response
scripts used by a stable module are pinned to an immutable repository tag.

| Module | Channel | Last live evidence | Required companion | Scope note |
| --- | --- | --- | --- | --- |
| YouTube | stable | 2026-11-11, `.11.11` protobuf feed scan optimization and setting inflation fix on iOS 5.23.0 | none | Playback ads, feed cards, background playback and PiP |
| Instagram | limited | 2026-07-13, native HTTPS fallback and netseer rejection | none | Web endpoints only; pinned native API stays outside MITM |
| 高德地图 | candidate | 2026-07-13, m5-x MITM and telemetry endpoints | 基础去广告模块 recommended | Conservative first-party response cleanup |
| 扫描全能王 | candidate | layered architecture validation | 基础去广告模块 required | First-party operations and ad containers only |
| 京东 | stable | 2026-07-12, JD 15.8.50 (plus 2026-11-11 `speedv6` IPv6 probe rule) | 基础去广告模块 recommended | Whitelisted `functionId` values only |
| 微信 | candidate | 2026-07-13, iOS load and synthetic response-engine pass; real WeChat flow pending | 基础去广告模块 recommended | Official-account ads and exact mini-program ad hosts; native MMTLS feeds excluded |
| 小红书 | stable | 2026-11-11, `.11.11` iOS 5.23.0 bundle load, external-resource readiness and canonical cloud promotion | none | Explicit structured ads only; save/watermark and search UI excluded |
| 微博 | stable | 2026-11-11, `.11.11` iOS 5.23.0 bundle load, external-resource readiness and canonical cloud promotion | none | Endpoint/container allowlists; account, membership, messages and wallet excluded |
| 哔哩哔哩 | stable | 2026-11-13, `.11.13` Bilibili 9.19.0 on iOS 5.23.0 live HTTP/2 JSON + gRPC validation and canonical cloud promotion | none | Dual JSON + unary gRPC ad cleanup; optional bottom Mall tab & PCDN switches; account/VIP/pay excluded |
| 基础去广告模块 | stable | 2026-07-13 Mac/iOS domain review | none | Domain rules only; no script or MITM |

## Status meanings

- `stable`: automated checks pass and the current behavior has live-device evidence.
- `candidate`: automated checks pass, but a fresh live-device regression pass is
  still required before the module receives an independent stable tag.
- `limited`: the module is stable only within the explicitly documented technical
  boundary. It must not be presented as covering pinned native APIs.

## Current distribution and validated baseline

- Active distribution: `surge-self-v2026.11.13`. Its manifest records
  `live_device_validation: passed` and `rollback_eligible: false` (active bundles
  are never rollback targets against themselves).
- Previous distributions: `surge-self-v2026.11.11` (`inactive`, eight-script
  bundle) and `surge-self-v2026.07.13.4` (`inactive`, `rollback_eligible: false`
  — certification provenance is retained below).
- Supported runtime used for the `.11.13` validation:
  - Surge Mac 6.9.1 (12290)
  - Surge iOS 5.23.0 (3867)
- All nine script-backed public module install URLs live directly under
  `rewrite/Surge/` on `main` (`youtube-self.sgmodule`, `instagram-self.sgmodule`,
  `amap-self.sgmodule`, `camscanner-self.sgmodule`, `jd-self.sgmodule`,
  `wechat-self.sgmodule`, `xiaohongshu-self.sgmodule`, `weibo-self.sgmodule`,
  `bilibili-self.sgmodule`) and pin `script-path` to immutable tag
  `surge-self-v2026.11.13` (`?v=20261113-1`).
- `rewrite/Surge/candidates/` has been emptied after promoting Bilibili to its
  canonical `main` cloud module path.

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

## Live-device evidence for surge-self-v2026.11.13

- Registered payload commit: `02b44c891ccb4e7d3d16111c17cac28d0d7cd69d`.
- Device and runtime: `iPhone18,3` running iOS `27.2 (24B119)` with
  `Surge iOS 5.23.0 (3867)` (`Core 6010000`), exercised between
  `2026-11-13 12:36 +08:00` and `2026-11-13 12:49 +08:00`; Surge Mac (`6.9.1`,
  `Core 6009001`) remained free of candidate modules throughout.
- Readiness, rule matching, and script pinning: enabled `哔哩哔哩 (候选 2026.11.13)`
  on iOS; refreshed all external resources (`40/40` reported `ready=1`, `0` load
  errors), verified `script list` pinned `bilibili.self.response` to immutable tag
  `surge-self-v2026.11.13` (`?v=20261113-1`), and verified `rule match` hit
  `DOMAIN,httpdns.bilivideo.com,REJECT` while preserving `DIRECT` on
  `app.bilibili.com`, `grpc.biliapi.net`, and `cm.bilibili.com`.
- Exercised release change surface and result (`passed`):
  - Cold-launched Bilibili iOS `9.19.0` and exercised splash, two-column home feed,
    video detail + related recommendations, comment threads, and dynamic timeline:
    `14` live HTTP/2 JSON and unary gRPC `bilibili.self.response` sessions between
    `2026-11-13 12:46:59–12:48:14 +08:00` completed cleanly (`7.1–38.2 ms`
    steady-state, `error: (null)`, zero residual ads, and memory steady at
    `27.8 MB`).
  - Surge iOS `file` and `memory` logs recorded `0` warnings and `0` errors across
    the validation window, confirming bundle integrity and readiness for canonical
    cloud activation.

## Live-device evidence for surge-self-v2026.11.13.1

- Registered payload commit: `6736c5274e10d294763bb682db9ea00e9b7d557c`.
- Device and runtime: `iPhone18,3` running iOS `27.2 (24B119)` with
  `Surge iOS 5.23.0 (3867)` (`Core 6010000`), exercised between
  `2026-11-13 13:30 +08:00` and `2026-11-13 13:42 +08:00`; Surge Mac (`6.9.1`,
  `Core 6009001`) remained free of candidate modules throughout.
- Readiness, rule matching, and script pinning: enabled `微信 (候选 2026.11.13.1)`
  on iOS; refreshed all external resources (`40/40` reported `ready=1`, `0` load
  errors), verified `script list` pinned `wechat.self.response` to immutable tag
  `surge-self-v2026.11.13.1` (`?v=20261113-2`), and verified `rule match` hit
  `REJECT` on `wxa.wxs.qq.com`, `wximg.wxs.qq.com`, and `wxsmw.wxs.qq.com`,
  `REJECT-NO-DROP` on `badjs.weixinbridge.com`, and `DIRECT` on
  `mp.weixin.qq.com`, `mmbiz.qpic.cn`, `gdtimg.com`, `wxsnsdy.wxs.qq.com`,
  `dns.weixin.qq.com`, and `wechatpay.cn`.
- Exercised release change surface and result (`passed`):
  - Exercised live WeChat Mini-Program business flow (`13:33–13:34 +08:00`),
    Moments (`朋友圈`) `MMTLS` boundary check (`13:33–13:34 +08:00`), and Official
    Account article reading scrolled to the bottom (`13:40–13:41 +08:00`): `16`
    live `wxa.wxs.qq.com:443` ad-creative connections matched `REJECT`, `4` live
    `badjs.weixinbridge.com:443` frontend telemetry uploads matched
    `REJECT-NO-DROP`, `mp.weixin.qq.com` MITM sessions (`GET /mp/relatedsearchword`
    and `POST /mp/jsmonitor`) completed cleanly without failure or CSP/style
    breakage while preserving article body and read/like metadata with zero bottom
    ad cards, and on-device Surge iOS JSC execution (`13:31:22 +08:00`) verified
    `wechat.self.response` across `getappmsgext` (`22.2 ms`), `cps_product_info`
    (`5.3 ms`), and `masonryfeed` (`4.4 ms`) with zero script errors.
  - Surge iOS `file` and `memory` logs recorded `0` warnings and `0` errors across
    the validation window (memory steady at `25.0 MB`), and the temporary
    candidate module was removed after verification.
