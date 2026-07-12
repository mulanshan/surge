# Mulanshan Surge

自用 Surge 大仓库。顶层只保留两个主要入口，方便在 GitHub 和移动端文件视图里查找：

- `rewrite/Surge/`：模块、增强、去广告、脚本。
- `rule/Surge/`：分流规则集和规则示例。

原 `mulanshan/surge-rules` 里的分流规则已迁入本仓库；旧仓库已停止使用。新配置统一使用 `mulanshan/surge`。

## 公开使用

本仓库直接作为公开 Surge 模块和规则仓库使用。修改模块、脚本或规则后，提交并推送到 `mulanshan/surge/main`，手机和服务器继续使用 `https://raw.githubusercontent.com/mulanshan/surge/main/...` 地址，不需要重装模块。

需要立即刷新时，在 Surge 里更新外部资源或重新加载配置。抓包、请求导出和本地分析报告默认写入 `reports/`、`rule/Surge/reports/` 或临时目录，这些路径已加入 `.gitignore`，避免误把日志和请求内容提交到公开仓库。

## rewrite / Surge

### YouTube Self

文件：[rewrite/Surge/youtube-self.sgmodule](rewrite/Surge/youtube-self.sgmodule)

订阅地址：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/rewrite/Surge/youtube-self.sgmodule
```

这是当前仓库唯一维护的 YouTube 去广告与后台播放模块。仓库里只保留这一个 YouTube 模块和一个响应脚本：

- 模块：`rewrite/Surge/youtube-self.sgmodule`
- 脚本：`rewrite/Surge/scripts/youtube/youtube-self.response.js`

当前范围：

- 处理 `player` / `get_watch` / `next` 播放链路广告，并尝试后台播放与 PiP
- 对首页/搜索 `browse` / `search` 按 protobuf 的 `ItemSectionRenderer -> richItemContents` 结构删除整张赞助卡，避免只清空内容后留下灰壳
- `guide` / `reel` 仍原样放行，避免导航和元数据回归
- 保留 googlevideo 初始化广告与广告统计 Map Local 拦截

安装或测试时，请在 Surge 里删除所有旧的 YouTube 模块，包括 `Youtube (Music) Enhance`、`YouTube Self Fast`、`YouTube Self iOS`、`YouTube Self Local`、`YouTube Safe Lite`、`YouTube Readable Enhance` 和所有抓包/调试模块，然后只添加上面的唯一安装地址。更新后请在 Surge 中更新外部资源或重载模块，确认脚本 query 版本为 `v=20260712-15`。

安全边界：

- 不使用第三方脚本
- 只从 `mulanshan/surge` 加载 `rewrite/Surge/scripts/youtube/youtube-self.response.js`
- 脚本不发起外部请求
- 不上传请求、响应、账号、cookie 或 token

### Instagram Self

文件：[rewrite/Surge/instagram-self.sgmodule](rewrite/Surge/instagram-self.sgmodule)

订阅地址：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/rewrite/Surge/instagram-self.sgmodule
```

这是自有可审计的 Instagram 模块。2026-06-10 真机日志确认 iOS Instagram 主链路存在证书钉扎，广域 MITM 会导致 App 打不开或卡住；当前模块先切换为安全版，不启用 Instagram MITM/响应改写，优先保证正常联网。

- 模块：`rewrite/Surge/instagram-self.sgmodule`
- 脚本：`rewrite/Surge/scripts/instagram/instagram-self.response.js`

当前功能范围：

- 不追加 `instagram.com`、`*.instagram.com`、`*.cdninstagram.com`、`*.i.instagram.com` 到 MITM
- 不挂载响应脚本，避免触发 `i.instagram.com`、`gateway.instagram.com`、`test-gateway.instagram.com` 等证书钉扎失败
- 拦截真机日志出现的 `netseer-ipaddr-assoc` 辅助探测域名
- 保留登录、私信、上传、账号、媒体 CDN 和正常内容流
- 不使用第三方脚本
- 不上传请求、响应、账号、cookie 或 token
- 不整域拒绝 `instagram.com`
- 后续只在真机日志证明某个非钉扎广告/追踪端点安全后，再单点加入规则

社区参考结论：

- blackmatrix7 / ios_rule_script 的 Instagram 规则主要是分流域名覆盖：`instagram.com`、`cdninstagram.com`、`instagr.am` 和 `DOMAIN-KEYWORD,instagram`
- 公开搜索到的大合集通常是全平台去广告或全量 MITM 配置，不是 Instagram 专用自维护脚本
- 当前模块不引入第三方成品脚本或现成片段；实现代码全部写在本仓库里

### Instagram Feed Self（实验版）

文件：[rewrite/Surge/instagram-feed-self.sgmodule](rewrite/Surge/instagram-feed-self.sgmodule)

订阅地址：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/rewrite/Surge/instagram-feed-self.sgmodule
```

这是按 YouTube Self 的结构做的 web-feed 实验版，只给 `www.instagram.com` 的 `feed / discover / graphql` 入口挂载一个响应脚本：

- 模块：`rewrite/Surge/instagram-feed-self.sgmodule`
- 脚本：`rewrite/Surge/scripts/instagram/instagram-self.response.js`

当前范围：

- 仅 MITM `www.instagram.com`
- 仅处理 `www.instagram.com/api/v1/feed/`、`www.instagram.com/api/v1/discover/` 和 `www.instagram.com/graphql/query/`
- 不碰 `i.instagram.com`、`gateway.instagram.com`、`test-gateway.instagram.com`
- 不碰媒体 CDN、登录、私信和账号链路

这个实验版是为了先验证 web feed 的广告清理思路；native iOS App 主链路仍然保留在上面的安全版里。

### 高德地图 Self

文件：[rewrite/Surge/amap-self.sgmodule](rewrite/Surge/amap-self.sgmodule)

订阅地址：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/rewrite/Surge/amap-self.sgmodule
```

这是自有可审计的高德地图去广告模块。仓库里只保留这一个高德模块和一个响应脚本：

- 模块：`rewrite/Surge/amap-self.sgmodule`
- 脚本：`rewrite/Surge/scripts/amap/amap-self.response.js`

第一版功能范围：

- 清理开屏广告接口 `ws/valueadded/alimama/splash_screen`
- 清理消息盒子与通知列表 `ws/msgbox/pull`、`ws/message/notice/list`
- 清理首页广告卡片 `ws/faas/amap-navigation/main-page`
- 清理搜索热词广告配置 `ws/shield/search/new_hotword`
- 清理 DSP/推荐广告配置 `ws/shield/dsp/profile/index/nodefaas`
- 对明确广告/归因接口使用 Map Local 返回空响应

安全边界：

- 不使用第三方脚本
- 只从 `mulanshan/surge` 加载 `rewrite/Surge/scripts/amap/amap-self.response.js`
- 脚本不发起外部请求
- 不上传请求、响应、账号、cookie 或 token
- 不整域拒绝 `amap.com`
- 不拦截天气、路线规划、导航、搜索主业务和账号接口

### 扫描全能王 Self

文件：[rewrite/Surge/camscanner-self.sgmodule](rewrite/Surge/camscanner-self.sgmodule)

订阅地址：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/rewrite/Surge/camscanner-self.sgmodule
```

正式稳定版：

```text
https://raw.githubusercontent.com/mulanshan/surge/camscanner-self-v1.0.0/rewrite/Surge/camscanner-self.sgmodule
```

这是自有可审计的扫描全能王 / CamScanner 去广告模块。仓库里只保留这一个扫描全能王模块和一个响应脚本：

- 模块：`rewrite/Surge/camscanner-self.sgmodule`
- 脚本：`rewrite/Surge/scripts/camscanner/camscanner-self.response.js`

当前正式版：`camscanner-self-v1.0.0`，基于 iPhone 真机测试通过的 `753c2cb` 后续固化版本。以后扫描全能王模块更新都以这个版本为基线，先在 `main` 验证，再按需发布新的稳定 tag。

正式版功能范围：

- 拦截明确广告、统计、归因和崩溃/行为采集域名
- 拦截真机日志已出现的腾讯广告 SDK、火山 APM 和扫描全能王数据上报域名
- 清理启动弹窗、运营活动、广告配置、页面运营位、新功能弹窗、推荐广告和营销位 JSON 容器
- 对明显广告/统计路径和真机出现的 `upload_ad_record` 使用 Map Local 返回空响应
- 保留账号、云同步、OCR、PDF 转换、购买校验和主业务接口

安全边界：

- 不使用第三方脚本
- 只从 `mulanshan/surge` 加载 `rewrite/Surge/scripts/camscanner/camscanner-self.response.js`
- 脚本不发起外部请求
- 不上传请求、响应、账号、cookie 或 token
- 不整域拒绝或 MITM `intsig.net`、`camscanner.com`
- 不修改 `purchase/cs/query_property` 等会员、订阅、订单、额度、收据接口

### 番茄小说去广告

文件：[rewrite/Surge/fanqie-novel-adblock.sgmodule](rewrite/Surge/fanqie-novel-adblock.sgmodule)

模块订阅地址：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/rewrite/Surge/fanqie-novel-adblock.sgmodule
```

规则集地址：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/rule/Surge/fanqie-novel-adblock.list
```

如果不用模块，也可以在主配置 `[Rule]` 顶部加入：

```ini
RULE-SET,https://raw.githubusercontent.com/mulanshan/surge/main/rule/Surge/fanqie-novel-adblock.list,REJECT,extended-matching
```

功能范围：

- 拦截番茄小说和字节系广告、统计、监控、热更新资源域名
- 对穿山甲广告 SDK 和广告素材路径使用 URL Rewrite reject
- 不包含 JavaScript 脚本
- 仅对广告 SDK/素材域名追加 MITM hostname
- 不修改响应体

这个模块采用保守的域名拦截 + URL Rewrite 方式，不整域拒绝 `fqnovel.com`、`fanqienovel.com`、`snssdk.com` 等主业务域。`.sgmodule` 是模块，模块内的 `[Rule]` 需要带策略；`rule/Surge/fanqie-novel-adblock.list` 是规则集，规则集本身不带策略，由主配置里的 `RULE-SET,...,REJECT` 决定策略。

## rule / Surge

规则集不包含策略，使用时在主配置 `[Rule]` 里指定策略组。个人规则应放在广泛的 China、Google、Microsoft、GitHub 等社区规则前面。

### 生成型自有规则集

目录：[rule/Surge/generated](rule/Surge/generated)

这个目录保存从外部成熟规则源解析、去重并重新标注后的自有规则集。来源清单在
[rule/Surge/sources/managed-rules.yaml](rule/Surge/sources/managed-rules.yaml)，生成脚本是
[scripts/generate-managed-surge-rules.py](scripts/generate-managed-surge-rules.py)。

重新生成：

```bash
scripts/generate-managed-surge-rules.py
```

每个生成文件都会写入：

- 规则用途和建议策略
- 上游 URL
- 上游内容 SHA-256
- 上游规则数量
- 合并后的唯一规则数量

这样外部规则变动时，可以用 Git diff 查看具体变化，再决定是否接受。当前主配置可逐步把
`blackmatrix7` / `ruleset.skk.moe` 的 URL 替换为 `mulanshan/surge` 下的 generated URL。示例片段见：
[rule/Surge/generated/rule-section-managed.conf](rule/Surge/generated/rule-section-managed.conf)。

### AI / LLM / Coding

文件：[rule/Surge/ai.list](rule/Surge/ai.list)

```ini
RULE-SET,https://raw.githubusercontent.com/mulanshan/surge/main/rule/Surge/generated/openai.list,Ai,extended-matching,no-resolve
RULE-SET,https://raw.githubusercontent.com/mulanshan/surge/main/rule/Surge/ai.list,Ai,extended-matching,no-resolve
```

AI 规则按两层保存：

- `rule/Surge/generated/openai.list`：OpenAI / ChatGPT / GPT 专用，单独保留，方便以后按日志独立调整。
- `rule/Surge/ai.list`：非 OpenAI 的 AI 服务合并入口，包括 Gemini、Claude、Cursor、Windsurf、Perplexity、OpenRouter、Hugging Face、xAI/Grok 等。

建议这两条都放在 Google、Microsoft、GitHub 等大规则前面。这样 OpenAI/GPT 的命中不会被通用
AI、Google 或 global 规则抢走，其他 AI 服务也只有一个自有规则入口。

旧路径 `rule/Surge/generated/gemini.list` 只作为兼容文件保留，避免 Apple TV 等设备在 iCloud profile
同步滞后时仍引用旧 URL 导致外部规则集解析失败；正式分类入口仍然是 `rule/Surge/ai.list`。

### Apple 系统服务

文件：[rule/Surge/generated/apple.list](rule/Surge/generated/apple.list)

```ini
RULE-SET,https://raw.githubusercontent.com/mulanshan/surge/main/rule/Surge/generated/apple.list,DIRECT,extended-matching
```

这个自有规则集从 blackmatrix7 Apple、Sukka Apple domains、Sukka Apple China domains 和 Sukka Apple
IP 规则合并生成，覆盖 iCloud、CloudKit、App Store、Maps、Apple 媒体服务、中国区 Apple 域名和 Apple
IP 段。建议放在 Google、Microsoft、GitHub、global 这些大规则前面，并使用 `DIRECT`，避免系统服务被兜底代理规则抢走。

### Amazon / Resolve 规则选择

Amazon 社区规则常见两版：`Amazon.list` 和 `Amazon_Resolve.list`。两者内容基本相同，区别在于
IP-CIDR 规则是否带 `no-resolve`。

- `Amazon.list`：IP-CIDR 带 `no-resolve`，更适合作为默认选择，避免为了匹配 Amazon/AWS IP 段额外解析域名。
- `Amazon_Resolve.list`：IP-CIDR 不带 `no-resolve`，匹配更激进，但 AWS IP 范围很大，容易把跑在 AWS 上的非 Amazon 业务也卷入。

本仓库原则：默认采用带 `no-resolve` 的规则方式；只有日志证明某服务必须靠 IP 段强匹配时，才单独评估
Resolve 版。当前主配置没有引用完整 Amazon 规则，只保留更细的 `generated/prime-video.list`。

### 豆瓣

文件：[rule/Surge/douban.list](rule/Surge/douban.list)

```ini
RULE-SET,https://raw.githubusercontent.com/mulanshan/surge/main/rule/Surge/douban.list,Proxy,extended-matching,no-resolve
```

覆盖豆瓣网页、移动网页、App/API 和常见图片静态资源域名。

### TMDb

文件：[rule/Surge/tmdb.list](rule/Surge/tmdb.list)

```ini
RULE-SET,https://raw.githubusercontent.com/mulanshan/surge/main/rule/Surge/tmdb.list,TW,extended-matching,no-resolve
```

覆盖 The Movie Database 网站、API 和图片资源域名。

### Docker / OCI 镜像拉取

文件：[rule/Surge/docker-oci.list](rule/Surge/docker-oci.list)

```ini
RULE-SET,https://raw.githubusercontent.com/mulanshan/surge/main/rule/Surge/docker-oci.list,自动,extended-matching,no-resolve
```

分流对象：

- Docker Hub 认证、索引、仓库和网页入口：`auth.docker.io`、`registry-1.docker.io`、`index.docker.io`、`registry.hub.docker.com`、`hub.docker.com`
- Docker 官方域名族：`docker.io`、`docker.com`
- Docker 镜像层下载 CDN：`production.cloudflare.docker.com`、`cloudflarestorage.com`
- GitHub Container Registry 和包容器下载域名：`ghcr.io`、`pkg-containers.githubusercontent.com`

适合在拉取 Docker / OCI 镜像时走可访问 Docker Hub 和 GHCR 的策略组。当前本机 Surge 配置使用 `自动` 策略。

### 番茄小说回国分流

文件：[rule/Surge/fanqie-novel-cn.list](rule/Surge/fanqie-novel-cn.list)
Loon 文件：[rule/Loon/fanqie-novel-cn.list](rule/Loon/fanqie-novel-cn.list)

```ini
RULE-SET,https://raw.githubusercontent.com/mulanshan/surge/main/rule/Surge/fanqie-novel-adblock.list,REJECT,extended-matching
RULE-SET,https://raw.githubusercontent.com/mulanshan/surge/main/rule/Surge/fanqie-novel-cn.list,China,extended-matching
```

如果人在中国大陆、不需要代理回国，第二行策略可以用 `DIRECT`。两条规则的顺序不要反过来，否则广告/日志域名会先被回国分流而不是拒绝。

Loon 引用时不要加 Surge 的 `extended-matching` 参数，策略名按自己的配置替换，例如：

```ini
RULE-SET,https://raw.githubusercontent.com/mulanshan/surge/main/rule/Loon/fanqie-novel-cn.list,回国
```

命名为“番茄小说”的中文规则集地址仍然保留：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/rule/Surge/%E7%95%AA%E8%8C%84%E5%B0%8F%E8%AF%B4.list
```

### 示例配置

文件：[rule/Surge/rule-section.conf](rule/Surge/rule-section.conf)

这个示例展示个人规则、社区规则、流媒体规则和兜底规则的推荐顺序。使用前按自己的策略组名称替换 `Proxy`、`Ai`、`TW`、`Streaming`、`GreenCloud` 等名称。

### 日志导出与候选规则开发

脚本：[rule/Surge/scripts/export-fanqie-candidates.sh](rule/Surge/scripts/export-fanqie-candidates.sh)

默认连接 iPhone Surge External Controller，读取最近请求并生成候选报告：

```bash
rule/Surge/scripts/export-fanqie-candidates.sh
```

也可以复盘之前保存的 `dump request` JSON：

```bash
rule/Surge/scripts/export-fanqie-candidates.sh --input /private/tmp/ios-surge-requests-20260606-151744.json
```

输出会写入 `reports/fanqie/`，该目录已忽略，不会误提交到公开仓库。主要文件：

- `*.summary.tsv`：域名、次数、规则、策略、是否拒绝的聚合表
- `*.candidate-rules.list`：只包含高置信新候选，复制到生产规则前必须人工复核
- `*.report.md`：按 `candidate-reject`、`observe`、`existing-rule` 分类的审查报告

开发原则：

- 已被 `rule/Surge/fanqie-novel-adblock.list` 拦截的域名保持在生产规则里
- 新域名先进入候选或观察，不直接整域拦截
- `bytegecko`、`douyinpic`、`ecombdimg`、`ydycdn` 等 CDN/图片/动态资源域名默认观察，确认和广告强相关后再精确单域拦截

扫描全能王也有独立的候选导出脚本：

```bash
rule/Surge/scripts/export-camscanner-candidates.sh
```

也可以复盘之前保存的 `dump request` JSON：

```bash
rule/Surge/scripts/export-camscanner-candidates.sh --input /private/tmp/ios-surge-requests.json
```

输出会写入 `reports/camscanner/`，该目录已忽略，不会误提交到公开仓库。开发原则：

- `purchase`、`receipt`、`order`、`payment`、`subscription`、`vip`、`premium`、`property`、`quota`、`account` 等购买/账号敏感路径一律跳过
- 新域名先进入候选或观察，不直接整域拦截 `intsig.net`、`camscanner.com`
- 静态资源、云同步、OCR、PDF 转换和文档接口默认观察，确认和广告强相关后再精确处理
