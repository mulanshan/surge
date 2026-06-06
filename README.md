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

如果不用模块，也可以在主配置 `[Rule]` 顶部加入：

```ini
RULE-SET,https://raw.githubusercontent.com/mulanshan/surge/main/rules/fanqie-novel-adblock.list,REJECT
```

功能范围：

- 拦截番茄小说和字节系广告、统计、监控、热更新资源域名
- 对穿山甲广告 SDK 和广告素材路径使用 URL Rewrite reject
- 不包含 JavaScript 脚本
- 仅对广告 SDK/素材域名追加 MITM hostname
- 不修改响应体

说明：

这个模块采用保守的域名拦截 + URL Rewrite 方式，不整域拒绝 `fqnovel.com`、`fanqienovel.com`、`snssdk.com` 等主业务域。规则参考 Surge 官方 Module 写法：`.sgmodule` 是模块，模块内的 `[Rule]` 需要带策略；`rules/fanqie-novel-adblock.list` 是规则集，规则集本身不带策略，由主配置里的 `RULE-SET,...,REJECT` 决定策略。

如果番茄小说后续新增广告域名，可以把域名追加到模块的 `[Rule]` 区域和规则集文件，然后重新推送仓库。Surge 里更新模块或外部资源即可生效。

## Youtube (Music) Enhance

文件：[modules/youtube-enhance.sgmodule](modules/youtube-enhance.sgmodule)

安装地址：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/modules/youtube-enhance.sgmodule
```

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

安装地址：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/modules/youtube-safe-lite.sgmodule
```

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

安装地址：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/modules/youtube-readable-enhance.sgmodule
```

说明：

这是完全自写的可读脚本版本，脚本在 [scripts/youtube/youtube-readable.response.js](scripts/youtube/youtube-readable.response.js)。它处理 JSON 形态的 YouTube `youtubei` 响应，可以清理常见广告字段、屏蔽部分入口、增加字幕翻译轨道和播放能力字段。它不包含第三方脚本，也不解析 protobuf，因此不能完整替代面向 iOS/YouTube Music App 的深度增强模块。

## YouTube Self Enhance

文件：[modules/youtube-self-enhance.sgmodule](modules/youtube-self-enhance.sgmodule)

安装地址：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/modules/youtube-self-enhance.sgmodule
```

说明：

这是完全自写实验版，脚本在 [scripts/youtube/youtube-self.response.js](scripts/youtube/youtube-self.response.js)。它包含 JSON 响应增强和 protobuf 通用广告字段清理。iOS 兼容模块会处理 `player/get_watch` 的已知 player 字段，清理 `adPlacements`、`adSlots`、`pageadViewthroughconversion`，并注入后台播放和画中画能力字段。它还会处理 `account/get_setting`，向设置响应中补入后台播放入口和开关项。脚本命中记录会写入 Surge 普通日志；在支持 Logbook 的 Surge 版本中，也会同步写入日志簿，便于远程查看脚本输入、输出和运行细节。

调试方式：

- 通过 Surge Mac Dashboard 连接 iOS 远程实例，可以查看 Logbook 中的脚本运行细节。
- 当前 `surge-cli` 可读取远程 `dump request`、`dump active`、`dump event`，但尚不能通过 `dump logbook` 直接导出 Logbook；脚本是否命中可先看请求备注中的 `Modified by script youtube.self.response` 和响应脚本记录。

注意：如果仓库保持私有，`raw.githubusercontent.com` 安装地址不能被 Surge 客户端直接拉取。需要将仓库公开、使用可访问的镜像地址，或改成你自己的带鉴权分发方式。

iOS 兼容安装地址：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/modules/youtube-ios.sgmodule
```

iCloud 本地同步版：

- 文件：[modules/youtube-ios-local.sgmodule](modules/youtube-ios-local.sgmodule)
- 调试与制作流程：[docs/youtube-ios-local-debug.md](docs/youtube-ios-local-debug.md)

这个版本用于私有仓库场景。模块本体在 iOS 上通过“新建本地模块”粘贴安装，脚本通过 Surge iCloud Documents 同步并以相对路径加载：

```ini
script-path=scripts/youtube/youtube-self.response.js
```
