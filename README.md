# Mulanshan Surge

自用 Surge 大仓库。顶层只保留两个主要入口，方便在 GitHub 和移动端文件视图里查找：

- `rewrite/Surge/`：模块、增强、去广告、脚本。
- `rule/Surge/`：分流规则集和规则示例。

原 `mulanshan/surge-rules` 里的分流规则已迁入本仓库；旧仓库已停止使用。新配置统一使用 `mulanshan/surge`。

## 公开使用

本仓库直接作为公开 Surge 模块和规则仓库使用。`main` 保存通过 CI 和审查的最新模块定义与规则快照；脚本型稳定模块的 `script-path` 固定到不可变 tag，避免普通提交未经验证就改变设备正在执行的 JavaScript。手机和服务器继续使用 `https://raw.githubusercontent.com/mulanshan/surge/main/...` 模块地址，不需要重装模块。

需要立即刷新时，在 Surge 里更新外部资源或重新加载配置。抓包、请求导出和本地分析报告默认写入 `reports/`、`rule/Surge/reports/` 或临时目录，这些路径已加入 `.gitignore`，避免误把日志和请求内容提交到公开仓库。

- 模块状态与真机验证矩阵：[docs/MODULE_STATUS.md](docs/MODULE_STATUS.md)
- 分支、稳定 tag、发布和回滚流程：[docs/RELEASE_PROCESS.md](docs/RELEASE_PROCESS.md)
- 本次 Mac / iOS 运行态基线：[docs/RUNTIME_AUDIT_2026-07-13.md](docs/RUNTIME_AUDIT_2026-07-13.md)
- 安全问题报告：[SECURITY.md](SECURITY.md)

## rewrite / Surge

### YouTube

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
- 对首页/搜索 `browse` / `search`、详情页 `next` 与 `get_watch.contents.next` 按 protobuf 的 `ItemSectionRenderer -> richItemContents` 结构删除整张赞助卡，避免只清空内容后留下灰壳
- `guide` / `reel` 仍原样放行，避免导航和元数据回归
- 保留 googlevideo 初始化广告与广告统计 Map Local 拦截

已安装当前订阅的设备只需在 Surge 中更新模块，旧显示名 `YouTube Self` 会变为 `YouTube`；新设备使用上面的固定地址安装一次。其他旧模块，如 `Youtube (Music) Enhance`、`YouTube Self Fast`、`YouTube Self iOS`、`YouTube Self Local`、`YouTube Safe Lite`、`YouTube Readable Enhance` 和抓包/调试模块应停用。更新后确认脚本来自稳定 tag `surge-self-v2026.07.13.2`，YouTube query 版本为 `v=20260713-1`。

安全边界：

- 不使用第三方脚本
- 只从 `mulanshan/surge` 加载 `rewrite/Surge/scripts/youtube/youtube-self.response.js`
- 脚本不发起外部请求
- 不上传请求、响应、账号、cookie 或 token

### Instagram

文件：[rewrite/Surge/instagram-self.sgmodule](rewrite/Surge/instagram-self.sgmodule)

订阅地址：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/rewrite/Surge/instagram-self.sgmodule
```

这是自有可审计的 Instagram 增强模块。2026-07-12 使用 iPhone 上的 Instagram `437.2.0` 复测：原生 App 的 `i.instagram.com` 主链路仍会在 TLS 握手后主动断开，Surge 明确记录 `MITM failed ... certificate pinning`。因此正式模块不强行解密原生 API，而是把当前可工作的 Web Feed 广告清理合并进主安装地址。

- 模块：`rewrite/Surge/instagram-self.sgmodule`
- 脚本：`rewrite/Surge/scripts/instagram/instagram-self.response.js`

当前功能范围：

- 清理 `www.instagram.com` 的 `api/graphql`、`graphql/query`、`api/v1/feed`、`api/v1/discover`、`api/v1/clips` 响应中的明确广告、赞助和付费合作节点
- 按完整 `edge / node / media_or_ad / item` 包装删除广告条目，避免只清空内容后留下空白卡片
- 兼容 `for (;;);` JSON 前缀；没有命中广告时不重写响应体
- 不追加 `i.instagram.com`、`graph.instagram.com`、`gateway.instagram.com`、聊天和媒体 CDN 到 MITM
- 仅拦截同时带 `netseer-ipaddr-assoc` 标记并属于 `fbcdn.net` 的真机已验证辅助探测主机
- `injected_*` 容器只递归删除带明确广告标志的实体，正常推荐与未知结构保持原样
- 保留登录、私信、上传、账号、媒体 CDN 和正常内容流
- 不使用第三方脚本
- 不上传请求、响应、账号、cookie 或 token
- 不整域拒绝 `instagram.com`
- 原生 iOS App 信息流广告与正常内容共用被钉扎的第一方 API；在不越狱、不注入 App 的前提下，Surge 不能只删除这部分广告而不破坏正常联网

调研和真机边界见：[docs/INSTAGRAM_SELF_RESEARCH.md](docs/INSTAGRAM_SELF_RESEARCH.md)。

社区参考结论：

- blackmatrix7 / ios_rule_script 的 Instagram 规则主要是分流域名覆盖：`instagram.com`、`cdninstagram.com`、`instagr.am` 和 `DOMAIN-KEYWORD,instagram`
- 公开搜索到的大合集通常是全平台去广告或全量 MITM 配置，不是 Instagram 专用自维护脚本
- 当前模块不引入第三方成品脚本或现成片段；实现代码全部写在本仓库里

已安装当前订阅的设备直接更新模块即可，显示名会从 `Instagram Self` 变为 `Instagram`；新设备使用同一固定地址安装。

### 高德地图

文件：[rewrite/Surge/amap-self.sgmodule](rewrite/Surge/amap-self.sgmodule)

订阅地址：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/rewrite/Surge/amap-self.sgmodule
```

这是自有可审计的高德地图去广告模块。仓库里只保留这一个高德模块和一个响应脚本：

- 模块：`rewrite/Surge/amap-self.sgmodule`
- 脚本：`rewrite/Surge/scripts/amap/amap-self.response.js`

当前功能范围：

- 清理开屏广告接口 `ws/valueadded/alimama/splash_screen`
- 在消息盒子与通知列表 `ws/msgbox/pull`、`ws/message/notice/list` 中只过滤明确广告实体，保留正常服务通知
- 清理首页广告卡片 `ws/faas/amap-navigation/main-page`
- 清理搜索热词广告配置 `ws/shield/search/new_hotword`
- 清理 DSP/推荐广告配置 `ws/shield/dsp/profile/index/nodefaas`
- 对明确广告/归因接口使用 Map Local 返回空响应
- 覆盖 `m5.amap.com`、`m5-zb.amap.com` 与 2026-07-13 真机验证的 `m5-x.amap.com`；后者已确认承载 `shield/alc/collect` 和 `shield/amapstream/upload`

安全边界：

- 不使用第三方脚本
- 只从 `mulanshan/surge` 加载 `rewrite/Surge/scripts/amap/amap-self.response.js`
- 脚本不发起外部请求
- 不上传请求、响应、账号、cookie 或 token
- 不整域拒绝 `amap.com`
- 不拦截天气、路线规划、导航、搜索主业务和账号接口

已安装当前订阅的设备直接更新模块即可，显示名会从 `高德地图 Self` 变为 `高德地图`；新设备使用同一固定地址安装。

### 扫描全能王

文件：[rewrite/Surge/camscanner-self.sgmodule](rewrite/Surge/camscanner-self.sgmodule)

订阅地址：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/rewrite/Surge/camscanner-self.sgmodule
```

旧架构独立稳定版（回滚用）：

```text
https://raw.githubusercontent.com/mulanshan/surge/camscanner-self-v1.0.0/rewrite/Surge/camscanner-self.sgmodule
```

这是自有可审计的扫描全能王 / CamScanner 专用模块。正式显示名统一为“扫描全能王”；固定 URL
保持不变，已安装设备直接更新即可。仓库里只维护这一个当前模块和一个响应脚本：

- 模块：`rewrite/Surge/camscanner-self.sgmodule`
- 脚本：`rewrite/Surge/scripts/camscanner/camscanner-self.response.js`

`camscanner-self-v1.0.0` 基于 iPhone 真机测试通过的 `753c2cb` 固化，仍包含 Google、腾讯、
AppsFlyer、Adjust 等旧架构全局规则与 MITM，只适合独立使用或回滚；它不代表当前“基础模块 + 专用模块”分层。
当前 `main` 已切换到新架构。已安装“扫描全能王 Self v2”的设备更新原订阅后会显示为“扫描全能王”；
旧架构“扫描全能王 Self”仍应停用。请同时启用“基础去广告模块”。本次脚本已固定到仓库级不可变 tag；模块仍按状态矩阵保留为 `candidate`，完成新版本真机专项回归后再晋升为 `stable`。

当前 `main` 功能范围：

- 拦截扫描全能王第一方广告、统计、崩溃和行为采集域名
- 清理启动弹窗、运营活动、广告配置、页面运营位、新功能弹窗、推荐广告和营销位 JSON 容器
- 对明显广告/统计路径和真机出现的 `upload_ad_record` 使用 Map Local 返回空响应
- 保留账号、云同步、OCR、PDF 转换、购买校验和主业务接口
- Google、腾讯等跨 App 广告域名统一由“基础去广告模块”处理
- AppsFlyer、Adjust、`app-measurement.com`、火山 APM 等归因/遥测默认不再全局拦截

安全边界：

- 不使用第三方脚本
- 只从 `mulanshan/surge` 加载 `rewrite/Surge/scripts/camscanner/camscanner-self.response.js`
- 脚本不发起外部请求
- 不上传请求、响应、账号、cookie 或 token
- 不整域拒绝或 MITM `intsig.net`、`camscanner.com`
- 不修改 `purchase/cs/query_property` 等会员、订阅、订单、额度、收据接口

### 基础去广告模块

文件：[rewrite/Surge/basic-adblock.sgmodule](rewrite/Surge/basic-adblock.sgmodule)

唯一推荐安装地址：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/rewrite/Surge/basic-adblock.sgmodule
```

这是以后统一使用的去广告入口。主配置 `[Rule]` 不再手工添加去广告 ruleset；模块集中维护跨 App
广告网络和少量日志确认的精确应用规则，模块规则由 Surge 自动插入主配置规则顶部。

当前范围：

- Google 广告：DoubleClick、Google Ad Services、Google Syndication 等
- 腾讯广告 SDK：GDT / 优量汇的明确广告入口
- 字节 / 穿山甲：广告 SDK、广告包、广告素材与日志已确认的广告主机
- 番茄小说：只拦真机日志确认的 `log` / `rtlog` / `mon` 精确主机
- 本机浏览器长期出现的 AppNexus、Integral Ad Science、AdKernel、Teads 等广告网络
- 仅使用精确 `DOMAIN` / `DOMAIN-SUFFIX` + Surge 内置 `REJECT`

安全边界：

- 无 JavaScript、无 MITM、无 URL Rewrite、无 Map Local、无 IP/关键词规则
- 不整域拒绝 `qq.com`、`snssdk.com`、`zijieapi.com`、`byteimg.com` 等混合业务域
- 番茄只包含精确日志主机，不包含阅读、图片、听书、视频、账号或支付接口
- 不包含扫描全能王、高德、京东、YouTube、Instagram 的第一方业务接口或 CDN
- 不拦截 Sentry/Crashlytics/OpenTelemetry、HTTPDNS、购买、订阅、账号、支付或收据接口
- AppsFlyer、Adjust、`app-measurement.com` 等归因/统计默认不进入基础核心规则
- 专用 App 的路径、响应体和界面广告继续由各自的专用模块处理

### 京东

文件：[rewrite/Surge/jd-self.sgmodule](rewrite/Surge/jd-self.sgmodule)

订阅地址：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/rewrite/Surge/jd-self.sgmodule
```

这是按 YouTube 的单模块、单脚本方式编写的自有京东去广告模块：

- 模块：`rewrite/Surge/jd-self.sgmodule`
- 脚本：`rewrite/Surge/scripts/jd/jd-self.response.js`
- 社区调研与设计边界：`docs/JD_SELF_RESEARCH.md`

当前范围：

- 处理开屏、启动弹窗、首页/我的页营销卡和浮层
- 清理搜索框热词、站内推荐和当前 `uniformRecommend`（兼容旧版 `uniformRecommend0/6`）
- 兼容京东 15.8.50 真机确认的 `/`、`/api`、`/client.action` 三种 API 入口，以及 POST 请求体中的 `functionId`
- 可关闭 `basicConfig` 中的 socket 诊断上报与 HTTPDNS 开关
- 可选择是否清理订单列表/物流页中的推广节点
- 仅拒绝随机 `jddebug.com/diagnose` 请求，不整域拦截京东

安全边界：

- 不使用第三方脚本，只从 `mulanshan/surge` 加载自有脚本
- 脚本不发起外部请求，不读取 Cookie，不上传请求、响应、账号或 token
- 未知 `functionId` 立即原样放行，且不解析其响应体
- 不改登录、购物车、商品、价格、订单主体、支付、退款、地址、物流主体、PLUS、会员、优惠券或钱包状态
- 不伪造会员、价格、余额、优惠或订单数据

首版以安全优先：识别不到的广告会原样放行，后续应根据当前京东版本的脱敏真机响应逐项补充明确字段，而不是扩大 MITM 或递归删除范围。

已安装当前订阅的设备直接更新模块即可，显示名会从 `京东 Self` 变为 `京东`；新设备使用同一固定地址安装。

### 微信

文件：[rewrite/Surge/wechat-self.sgmodule](rewrite/Surge/wechat-self.sgmodule)

订阅地址：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/rewrite/Surge/wechat-self.sgmodule
```

这是自有可审计的微信去广告模块：

- 清理公众号文章 `/mp/getappmsgad` 返回中的明确广告字段
- 对公众号商品推广接口 `/mp/cps_product_info` 返回空 JSON
- 精确拒绝三个社区长期交叉确认的小程序广告素材主机
- 不使用第三方脚本；脚本不联网、不读取 Cookie/token、不上传请求或响应

能力边界：

- 不承诺清除朋友圈、视频号或其他微信原生 Feed 广告；大量原生流量使用 MMTLS，Surge 无法安全改写
- 不整域拒绝 `weixin.qq.com`、`wxs.qq.com`、`servicewechat.com`、`tenpay.com`、`qpic.cn` 或 `qlogo.cn`
- 不修改消息、联系人、文章正文、评论、赞赏、小程序登录、微信支付、订单或会员状态
- 未知 JSON 结构和非目标路径立即原样放行

当前按微信 `8.0.75` 设计，模块状态为 `candidate`；详细调研、社区方案比较和真机回归清单见
[docs/WECHAT_SELF_RESEARCH.md](docs/WECHAT_SELF_RESEARCH.md)。

## rule / Surge

规则集不包含策略，使用时在主配置 `[Rule]` 里指定策略组。个人规则应放在广泛的 China、Google、Microsoft、GitHub 等社区规则前面。

### 自托管生成镜像

目录：[rule/Surge/generated](rule/Surge/generated)

这个目录保存从外部成熟规则源解析、去重并重新标注后的自托管生成镜像。它们不是完全独立原创内容，仍受各上游许可证和署名要求约束。来源、已审查哈希与许可证元数据在
[rule/Surge/sources/managed-rules.yaml](rule/Surge/sources/managed-rules.yaml)，生成脚本是
[scripts/generate-managed-surge-rules.py](scripts/generate-managed-surge-rules.py)。

只读检查当前快照：

```bash
scripts/generate-managed-surge-rules.py --check
```

接受并写入经过人工审查的 manifest 更新时，使用生成器的更新模式，并同时提交 manifest、规则文件和 JSON 元数据。详细流程见 [docs/RELEASE_PROCESS.md](docs/RELEASE_PROCESS.md)。

每个生成文件都会写入：

- 规则用途和建议策略
- 上游 URL
- 上游内容 SHA-256
- 上游规则数量
- 合并后的唯一规则数量

这样外部规则变动时，可以先由 `--check` 阻止漂移进入生产，再用 Git diff 查看具体变化并决定是否接受。当前主配置可逐步把
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

这个生成镜像从 blackmatrix7 Apple、Sukka Apple domains、Sukka Apple China domains 和 Sukka Apple
IP 规则合并生成，覆盖 iCloud、CloudKit、App Store、Maps、中国区 Apple 域名和 Apple IP 段。Apple TV
媒体条目单独放在 `generated/apple-tv.list`，必须在 Apple 系统 `DIRECT` 规则之前加载，避免 `TV` 进程和
AppleTV User-Agent 被系统规则抢先命中。

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
RULE-SET,https://raw.githubusercontent.com/mulanshan/surge/main/rule/Surge/fanqie-novel-cn.list,China,extended-matching
```

先启用“基础去广告模块”，再添加番茄回国分流。番茄广告/日志使用基础模块中的精确域名规则，
不再使用番茄专用模块，也不在主配置中额外维护番茄广告 ruleset。
如果人在中国大陆、不需要代理回国，策略可以用 `DIRECT`。

Loon 引用时不要加 Surge 的 `extended-matching` 参数，策略名按自己的配置替换，例如：

```ini
RULE-SET,https://raw.githubusercontent.com/mulanshan/surge/main/rule/Loon/fanqie-novel-cn.list,回国
```

命名为“番茄小说”的中文规则集地址仍然保留：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/rule/Surge/%E7%95%AA%E8%8C%84%E5%B0%8F%E8%AF%B4.list
```

### 示例配置

唯一推荐文件：[rule/Surge/generated/rule-section-managed.conf](rule/Surge/generated/rule-section-managed.conf)

这个示例展示已审查镜像、AI、Apple 系统、Apple TV 和流媒体规则的推荐顺序。使用前按自己的策略组名称替换策略名。旧 [rule/Surge/rule-section.conf](rule/Surge/rule-section.conf) 仅为兼容提示，不再作为推荐配置。

### 日志导出与候选规则开发

脚本：[rule/Surge/scripts/export-fanqie-candidates.sh](rule/Surge/scripts/export-fanqie-candidates.sh)

默认通过 iPhone Surge HTTPS HTTP API 读取最近请求并生成候选报告；设备地址必须由环境变量或 `--host` 明确提供，仓库不保存家庭 LAN 地址：

```bash
SURGE_REMOTE_HOST=192.168.1.50 rule/Surge/scripts/export-fanqie-candidates.sh
```

也可以复盘之前保存的 `dump request` JSON：

```bash
rule/Surge/scripts/export-fanqie-candidates.sh --input /private/tmp/ios-surge-requests-20260606-151744.json
```

输出会以仅当前用户可读的权限写入 `reports/fanqie/`，该目录已忽略，不会误提交到公开仓库。HTTP API key 通过标准输入交给 `curl`，不会作为命令行参数暴露。主要文件：

- `*.summary.tsv`：域名、次数、规则、策略、是否拒绝的聚合表
- `*.candidate-rules.list`：只包含高置信新候选，加入基础或专用模块前必须人工复核
- `*.report.md`：按 `candidate-reject`、`observe`、`existing-rule` 分类的审查报告

开发原则：

- 新域名先进入候选或观察，不直接整域拦截
- 跨 App 广告网络和真机确认的番茄精确日志主机进入 `rewrite/Surge/basic-adblock.sgmodule`
- 番茄主业务、账号、内容、图片、视频和路径级候选不进入基础模块
- `bytegecko`、`douyinpic`、`ecombdimg`、`ydycdn` 等 CDN/图片/动态资源域名默认观察，确认和广告强相关后再精确单域拦截

扫描全能王也有独立的候选导出脚本：

```bash
SURGE_REMOTE_HOST=192.168.1.50 rule/Surge/scripts/export-camscanner-candidates.sh
```

也可以复盘之前保存的 `dump request` JSON：

```bash
rule/Surge/scripts/export-camscanner-candidates.sh --input /private/tmp/ios-surge-requests.json
```

输出会写入 `reports/camscanner/`，该目录已忽略，不会误提交到公开仓库。开发原则：

- `purchase`、`receipt`、`order`、`payment`、`subscription`、`vip`、`premium`、`property`、`quota`、`account` 等购买/账号敏感路径一律跳过
- 新域名先进入候选或观察，不直接整域拦截 `intsig.net`、`camscanner.com`
- 静态资源、云同步、OCR、PDF 转换和文档接口默认观察，确认和广告强相关后再精确处理

## 授权与第三方来源

仓库自写代码的授权见 [LICENSE](LICENSE)。`rule/Surge/generated/` 中的生成规则包含来自多个上游项目的衍生内容，不能因为托管在本仓库就视为重新授权；具体来源、许可证和保留要求见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 与 manifest 元数据。
