# Bilibili Surge Module Research (2026-11-13)

## Target baseline

- App Store entry: `哔哩哔哩-弹幕番剧直播高清视频` (`https://apps.apple.com/cn/app/id736536022`), bundle `tv.danmaku.bilianime`, version `9.19.0` (2026-11-11).
- Surge baseline: `Surge iOS 5.23.0` (`CORE_VERSION>=20 && SYSTEM = 'iOS'`), HTTP/2 MITM enabled (`h2 = true`), binary script support (`binary-body-mode=1`), explicit `max-size=6291456`, `$surge.logbook` diagnostics, and Surge's default `auto-quic-block` for MITM hostnames.

## Community landscape

Reviewed public architectural discussions and Surge module conventions across `BiliUniverse` (`ADBlock` / `Enhanced`), `Maasea/sgmodule`, `fmz200/wool_scripts`, and `ddgksf2013`:

- Modern Bilibili iOS builds split ad delivery across two distinct transport surfaces:
  1. **HTTPS JSON (`app.bilibili.com`, `api.bilibili.com`, `api.live.bilibili.com`)**: launch splash schedules (`/x/v2/splash/list|show|event/list2|brand/list`), two-column home feed (`/x/v2/feed/index`), vertical story feed (`/x/v2/feed/index/story`), search square promotions (`/x/v2/search/square`), live room banner slots (`/xlive/app-room/v1/index/getInfoByRoom`), and navigation tab layout (`/x/resource/show/tab/v2`).
  2. **gRPC over HTTP/2 (`grpc.biliapi.net`, `app.bilibili.com`)**: video detail metadata and related cards (`bilibili.app.viewunite.v1.View/{View,RelatesFeed}` and legacy `bilibili.app.view.v1.View/{View,RelatesFeed}`), comment threads (`bilibili.main.community.reply.v1.Reply/MainList`), and dynamic timeline feeds (`bilibili.app.dynamic.v2.Dynamic/DynAll`), framed as 5-byte gRPC Length-Prefixed-Message headers (`[compressed_flag, uint32_be_len]`) wrapping binary Protocol Buffers.
- Community discussions highlight four recurring failure modes in third-party modules:
  1. **HTTPDNS bypass**: Bilibili queries `httpdns.bilivideo.com` and connects directly to resolved CDN/API IPs, bypassing hostname MITM unless `httpdns.bilivideo.com` is rejected.
  2. **QUIC / UDP rule blackholes**: handwritten `PROTOCOL,UDP,REJECT` rules hit Surge's automatic `REJECT -> DROP` flood upgrade (50 hits in 30 seconds), stalling video startup while the client waits for UDP timeouts. Surge's built-in `auto-quic-block` on `[MITM]` hostnames avoids this trap.
  3. **Broad `grpc-accept-encoding` stripping and compressed frames**: stripping `grpc-accept-encoding` across every `/bilibili.*` gRPC method forces multi-megabyte danmaku segments (`DmSegMobile`) to transfer uncompressed, while scripts that assume every gRPC body is uncompressed corrupt responses whenever `compressed_flag !== 0x00`.
  4. **Overbroad domain or feed predicates**: rejecting `cm.bilibili.com` at the domain level breaks official event jump links (`https://cm.bilibili.com/...`), and filtering `/x/v2/feed/index` items on `is_ad_loc` deletes organic videos occupying ad-eligible slots when no ad was served.

## Why third-party code is excluded

- Community Bilibili scripts commonly load mutable remote bundles (`raw.githubusercontent.com/.../main/...` or CDN mirrors), embed large generated `protobufjs` runtimes, or carry non-MIT / copyleft license constraints.
- Several "enhanced" packages combine ad cleanup with region-unlock proxy routing, VIP/theme spoofing, or `/x/v2/account/mine` profile mutation, expanding attack surface onto authenticated account and entitlement endpoints.
- Consistent with `CONTRIBUTING.md`, `bilibili-self` is written 100% from scratch under MIT in this repository, pins `script-path` to an immutable `surge-self-v*` tag verified by SHA-256, makes zero network calls, and never reads or logs cookies, tokens, user IDs, or raw bodies.

## Self-hosted module design

- Staged candidate path: `rewrite/Surge/candidates/bilibili-self.sgmodule` (`#!name=哔哩哔哩 (候选 2026.11.13)`), promoted to canonical `rewrite/Surge/bilibili-self.sgmodule` (`#!name=哔哩哔哩`) only after tagged iPhone validation passes.
- Single response script: `rewrite/Surge/scripts/bilibili/bilibili-self.response.js` (`binary-body-mode=1`, `max-size=6291456`).
- Network and header rules:
  - `DOMAIN,httpdns.bilivideo.com,REJECT` to prevent HTTPDNS MITM bypass without whole-domain blocking `bilibili.com`, `biliapi.net`, `bilivideo.com`, or `cm.bilibili.com`.
  - Optional PCDN policy parameter (`PCDN节点策略`, default `DIRECT`; user-selectable `REJECT`) scoped to `mcdn.bilivideo.cn` and `szbdyd.com`.
  - `[Header Rewrite]` removes `grpc-accept-encoding` **only** on the six whitelisted gRPC RPC paths handled by the script, preserving gzip compression on danmaku (`DmSegMobile`) and playback endpoints.
- Strict double allowlist (host + exact pathname, then explicit commercial field/enum markers):
  - **JSON**:
    - `/x/v2/splash/{list,show,event/list2}`: clears `show` / `event_list`, zeroes splash display duration (`max_time = 0`, `min_interval = 86400`, `pull_interval = 86400`), and neutralizes cached `list` schedules; `/x/v2/splash/brand/list` clears only `show` so user-selected launch brand logos keep working.
    - `/x/v2/feed/index` and `/x/v2/feed/index/story`: removes items only when explicit commercial markers exist (`is_ad === true`, non-empty `ad_info` / `ads_info`, non-empty `ad_cb`, `goto` starting with `ad`, or `card_goto` starting with `ad_` / `cm_` / `live_ad`), filters `banner_item` entries marked `type === "ad"` / `is_ad`, and preserves organic items that merely carry `is_ad_loc: true`.
    - `/x/v2/search/square`: removes explicit commercial promotion squares and ad-marked entries while preserving normal search history and trending queries.
    - `/xlive/app-room/v1/index/getInfoByRoom`: clears `activity_banner_info` and `ad_banner_info` without touching stream play URLs, gifts, or room state.
    - `/x/resource/show/tab/v2`: untouched by default; when `隐藏底栏会员购` (`hideMallTab`) is set to `true`, removes only the bottom `会员购` (`global_mall` / `mall` / `bilibili://mall/...`) tab and re-indexes `pos`.
  - **gRPC Protobuf** (unary uncompressed frames `compressed_flag === 0x00` with exact 4-byte big-endian length match; compressed, multi-frame, or malformed payloads pass through untouched):
    - `bilibili.app.view.v1.View/View`: strips `ViewReply` fields `30` (`cms`), `31` (`cm_config`), `41` (`cm_ipad`), `48` (`cm_under_player`), and filters `10` (`relates`) entries carrying field `28` (`cm`) or `goto` (`7`) in `{"cm", "ad"}`.
    - `bilibili.app.view.v1.View/RelatesFeed`: filters `RelatesFeedReply.list` (`1`) with the same `Relate` commercial predicate.
    - `bilibili.app.viewunite.v1.View/View`: strips `ViewReply.cm` (`7`) and filters `RelateCard` entries inside `tab (5) -> tab_module (1) -> introduction (2) -> modules (2) -> relates (22) -> cards (1)` where `relate_card_type (1) === 5 (CM)` or `cm (6)` / `cm_stock (11)` is present.
    - `bilibili.app.viewunite.v1.View/RelatesFeed`: filters `RelatesFeedReply.relates` (`1`) with the same `RelateCard` commercial predicate.
    - `bilibili.main.community.reply.v1.Reply/MainList`: strips `MainListReply.cm` (`11`) while preserving `replies` (`2`) and creator-pinned `up_top` (`4`).
    - `bilibili.app.dynamic.v2.Dynamic/DynAll`: filters `DynAllReply.dynamic_list (1).list (1)` items whose `card_type (1)` or `item_type (2)` equals `15` (`DYNAMIC_TYPE_AD`).
- Explicitly excluded surfaces: `/x/v2/account/*`, `/x/passport-*`, `/pay/*`, `/wallet/*`, playback `PlayView`, danmaku `DmSegMobile`, login, VIP entitlement status, coins/charging, and write/POST mutations.
