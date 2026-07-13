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
| 基础去广告模块 | stable | 2026-07-13 Mac/iOS domain review | none | Domain rules only; no script or MITM |

## Status meanings

- `stable`: automated checks pass and the current behavior has live-device evidence.
- `candidate`: automated checks pass, but a fresh live-device regression pass is
  still required before the module receives an independent stable tag.
- `limited`: the module is stable only within the explicitly documented technical
  boundary. It must not be presented as covering pinned native APIs.

## Current stable bundle

- Tag: `surge-self-v2026.07.13.4`
- Supported runtime used for release verification:
  - Surge Mac 6.6.0 (11270)
  - Surge iOS 5.19.0 (3727)
- The public module install URLs remain under `main`; each script-backed module
  pins its `script-path` to the immutable tag above.

## Current iOS rollout evidence

- The effective profile contains 205 top-level rules, including nine adjacent
  `DOMAIN-SET` / residual `RULE-SET` pairs with the original policies and order.
- All 36 external resources are ready: 9 domain sets, 21 rule sets, and 6 scripts.
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
