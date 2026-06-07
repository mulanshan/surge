# Surge Modules

自用 Surge 模块仓库。所有模块尽量保持可审计、少权限、无远程脚本依赖。

## 番茄小说去广告

文件：[modules/fanqie-novel-adblock.sgmodule](modules/fanqie-novel-adblock.sgmodule)

模块安装地址：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/modules/fanqie-novel-adblock.sgmodule
```

规则集地址：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/rules/fanqie-novel-adblock.list
```

回国分流规则集地址：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/rules/fanqie-novel-cn.list
```

命名为“番茄小说”的云端规则集地址：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/rules/%E7%95%AA%E8%8C%84%E5%B0%8F%E8%AF%B4.list
```

如果不用模块，也可以在主配置 `[Rule]` 顶部加入：

```ini
RULE-SET,https://raw.githubusercontent.com/mulanshan/surge/main/rules/fanqie-novel-adblock.list,REJECT,extended-matching
```

如果在海外使用番茄小说，可以把广告规则放前面，再把业务流量交给你的回国策略组：

```ini
RULE-SET,https://raw.githubusercontent.com/mulanshan/surge/main/rules/fanqie-novel-adblock.list,REJECT,extended-matching
RULE-SET,https://raw.githubusercontent.com/mulanshan/surge/main/rules/fanqie-novel-cn.list,你的回国策略,extended-matching
```

也可以使用命名为“番茄小说”的中文规则集地址：

```ini
RULE-SET,https://raw.githubusercontent.com/mulanshan/surge/main/rules/%E7%95%AA%E8%8C%84%E5%B0%8F%E8%AF%B4.list,你的回国策略,extended-matching
```

如果人在中国大陆、不需要代理回国，第二行策略可以用 `DIRECT`。两条规则的顺序不要反过来，否则广告/日志域名会先被回国分流而不是拒绝。

功能范围：

- 拦截番茄小说和字节系广告、统计、监控、热更新资源域名
- 可选把番茄小说业务、阅读图片、阅读视频和动态资源分流到回国策略
- 对穿山甲广告 SDK 和广告素材路径使用 URL Rewrite reject
- 不包含 JavaScript 脚本
- 仅对广告 SDK/素材域名追加 MITM hostname
- 不修改响应体

说明：

这个模块采用保守的域名拦截 + URL Rewrite 方式，不整域拒绝 `fqnovel.com`、`fanqienovel.com`、`snssdk.com` 等主业务域。规则参考 Surge 官方 Module 写法：`.sgmodule` 是模块，模块内的 `[Rule]` 需要带策略；`rules/fanqie-novel-adblock.list` 是规则集，规则集本身不带策略，由主配置里的 `RULE-SET,...,REJECT` 决定策略。

如果番茄小说后续新增广告域名，可以把域名追加到模块的 `[Rule]` 区域和规则集文件，然后重新推送仓库。Surge 里更新模块或外部资源即可生效。

### 日志导出与候选规则开发

脚本：[scripts/export-fanqie-candidates.sh](scripts/export-fanqie-candidates.sh)

默认连接 iPhone Surge External Controller，读取最近请求并生成候选报告：

```bash
scripts/export-fanqie-candidates.sh
```

也可以复盘之前保存的 `dump request` JSON：

```bash
scripts/export-fanqie-candidates.sh --input /private/tmp/ios-surge-requests-20260606-151744.json
```

输出会写入 `reports/fanqie/`，该目录已忽略，不会误提交到公开仓库。主要文件：

- `*.summary.tsv`：域名、次数、规则、策略、是否拒绝的聚合表
- `*.candidate-rules.list`：只包含高置信新候选，复制到生产规则前必须人工复核
- `*.report.md`：按 `candidate-reject`、`observe`、`existing-rule` 分类的审查报告

开发原则：

- 已被 `fanqie-novel-adblock.list` 拦截的域名保持在生产规则里
- 新域名先进入候选或观察，不直接整域拦截
- `bytegecko`、`douyinpic`、`ecombdimg`、`ydycdn` 等 CDN/图片/动态资源域名默认观察，确认和广告强相关后再精确单域拦截

## YouTube Self

文件：[modules/youtube-self.sgmodule](modules/youtube-self.sgmodule)

安装地址：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/modules/youtube-self.sgmodule
```

说明：

这是当前唯一推荐的公开仓库安装地址。模块和脚本都从自己的公开仓库加载，不包含第三方代码。以后 YouTube 规则只维护这个主入口，旧的 Fast/iOS/实验模块文件保留为兼容和调试用途。

安全边界：

- 不使用第三方脚本
- 只从 `mulanshan/surge` 加载 `scripts/youtube/youtube-self.response.js`
- 脚本不发起外部请求
- 不上传请求、响应、账号、cookie 或 token
- 不 MITM `www.google.com` / `www.google.com.hk` 这类更泛的 Google 主机名

功能范围：

- YouTube `browse` 首页信息流广告削弱
- YouTube `player/get_watch` 已知播放广告字段清理
- 后台播放、画中画能力增强
- 拒绝 YouTube QUIC/HTTP3，使请求回落到可处理的 HTTPS
- 对 `googlevideo.com/initplayback` 广告初始化请求返回空响应

速度边界：

- 只对 `youtubei.googleapis.com` 的 `browse/player/get_watch` 执行响应脚本
- 不处理 `next/search/guide/account/get_setting/reel`，减少首屏脚本负担
- 不 MITM `www.youtube.com`、`s.youtube.com`、`googleads.g.doubleclick.net`、`www.google.com`
- 已安装 `youtube-self-fast.sgmodule` 的设备可以继续更新，但新安装统一使用 `youtube-self.sgmodule`

## YouTube Self Local

文件：[modules/youtube-self-local.sgmodule](modules/youtube-self-local.sgmodule)

说明：

这是不依赖 GitHub raw 的本地版。模块本体可以在 Surge 里新建本地模块后粘贴；脚本从 Surge 本地 Documents 目录读取：

```ini
script-path=scripts/youtube/youtube-self.response.js
```

安全边界：

- 不使用第三方脚本
- 不使用远程 `script-path`
- 不发起外部请求
- 不上传请求、响应、账号、cookie 或 token
- 不 MITM `www.google.com` / `www.google.com.hk` 这类更泛的 Google 主机名

安装时把 [scripts/youtube/youtube-self.response.js](scripts/youtube/youtube-self.response.js) 同步到 Surge Documents 的同名路径。iOS 私有仓库/本地调试流程见 [docs/youtube-ios-local-debug.md](docs/youtube-ios-local-debug.md)。

## Youtube (Music) Enhance

文件：[modules/youtube-enhance.sgmodule](modules/youtube-enhance.sgmodule)

说明：历史第三方固定副本，保留作对照；新安装统一使用 `YouTube Self`。

功能范围：

- YouTube 视频广告请求清理
- 后台播放、画中画能力增强
- 可选字幕翻译增强
- 可选隐藏上传、沉浸式入口、Shorts 入口
- 拒绝 YouTube 相关 UDP/QUIC 连接，使流量回落到可处理的 HTTPS
- 对 `googlevideo.com/initplayback` 的广告初始化请求返回空响应

脚本来源：

- 上游文件：`Maasea/sgmodule/Script/Youtube/youtube.response.js`
- 上游 blob SHA：`ee08380ee9bb7889f653022d7a3229f8d8b6ea5b`
- 本仓库固定副本：[scripts/youtube/youtube.response.js](scripts/youtube/youtube.response.js)

安全说明：

这个模块保留为历史第三方固定副本，不再作为首选。现在建议优先使用上面的 `YouTube Self`；只有在自写版失效、且你愿意接受第三方脚本审计成本时，再临时启用这一版。

YouTube 增强必须处理 `youtubei.googleapis.com` 的 HTTPS 响应体，所以这个模块需要启用 MITM，并且会执行响应脚本。`*.googlevideo.com` 用于配合 `[Map Local]` 处理部分播放初始化广告请求；这是更完整但权限更大的配置。脚本只引用本仓库固定副本，不继续引用不受控的第三方 raw 地址。

默认参数：

```json
{
  "lyricLang": "off",
  "captionLang": "off",
  "blockUpload": true,
  "blockImmersive": true,
  "blockShorts": false,
  "debug": false
}
```

## YouTube Safe Lite

文件：[modules/youtube-safe-lite.sgmodule](modules/youtube-safe-lite.sgmodule)

说明：历史最小权限版本，保留作调试对照；新安装统一使用 `YouTube Self`。

功能范围：

- 拒绝 YouTube 相关 UDP/QUIC 连接，使流量回落到 TCP/HTTPS
- 对 `googlevideo.com/initplayback` 的部分广告初始化请求返回空响应
- 不执行任何 JavaScript
- 不 MITM `youtubei.googleapis.com`
- 不修改 YouTube protobuf API 响应

说明：

这是完全自写、最小权限的安全版。它的目标是减少可通过网络层识别的广告请求，而不是完整替代 `Youtube (Music) Enhance`。后台播放、画中画、字幕增强、信息流广告清理等功能都依赖解析并修改 YouTube protobuf 响应，安全版不会做这些高风险操作。

## YouTube Readable Enhance

文件：[modules/youtube-readable-enhance.sgmodule](modules/youtube-readable-enhance.sgmodule)

说明：

这是完全自写的可读脚本版本，脚本在 [scripts/youtube/youtube-readable.response.js](scripts/youtube/youtube-readable.response.js)。它处理 JSON 形态的 YouTube `youtubei` 响应，可以清理常见广告字段、屏蔽部分入口、增加字幕翻译轨道和播放能力字段。它不包含第三方脚本，也不解析 protobuf，因此不能完整替代面向 iOS/YouTube Music App 的深度增强模块。

## YouTube Self Enhance

文件：[modules/youtube-self-enhance.sgmodule](modules/youtube-self-enhance.sgmodule)

说明：

这是完全自写实验版，脚本在 [scripts/youtube/youtube-self.response.js](scripts/youtube/youtube-self.response.js)。它包含 JSON 响应增强和 protobuf 通用广告字段清理。iOS 兼容模块会处理 `player/get_watch` 的已知 player 字段，清理 `adPlacements`、`adSlots`、`pageadViewthroughconversion`，并注入后台播放和画中画能力字段。它还会处理 `account/get_setting`，向设置响应中补入后台播放入口和开关项。脚本命中记录会写入 Surge 普通日志；在支持 Logbook 的 Surge 版本中，也会同步写入日志簿，便于远程查看脚本输入、输出和运行细节。

调试方式：

- 通过 Surge Mac Dashboard 连接 iOS 远程实例，可以查看 Logbook 中的脚本运行细节。
- 当前 `surge-cli` 可读取远程 `dump request`、`dump active`、`dump event`，但尚不能通过 `dump logbook` 直接导出 Logbook；脚本是否命中可先看请求备注中的 `Modified by script youtube.self.response` 和响应脚本记录。

注意：如果仓库保持私有，`raw.githubusercontent.com` 安装地址不能被 Surge 客户端直接拉取。需要将仓库公开、使用可访问的镜像地址，或改成你自己的带鉴权分发方式。

iOS 兼容远程版保留在 [modules/youtube-ios.sgmodule](modules/youtube-ios.sgmodule)，仅用于历史兼容和调试。新安装统一使用 `YouTube Self` 主入口。

iCloud 本地同步版：

- 推荐文件：[modules/youtube-self-local.sgmodule](modules/youtube-self-local.sgmodule)
- 兼容旧文件：[modules/youtube-ios-local.sgmodule](modules/youtube-ios-local.sgmodule)
- 调试与制作流程：[docs/youtube-ios-local-debug.md](docs/youtube-ios-local-debug.md)

这个版本用于私有仓库场景。模块本体在 iOS 上通过“新建本地模块”粘贴安装，脚本通过 Surge iCloud Documents 同步并以相对路径加载：

```ini
script-path=scripts/youtube/youtube-self.response.js
```
