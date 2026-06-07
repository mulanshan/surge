# YouTube iOS 本地模块制作与调试

本文记录当前 YouTube iOS 自写模块的制作方式、Mac 连接 iOS Surge 的方法，以及后续调试时的固定流程。

## 目标

- 仓库保持私有，不在 iPhone 上使用 `raw.githubusercontent.com` 拉取私有文件。
- 模块和脚本通过 Surge 的 iCloud Documents 同步到 iOS。
- iOS 只加载本地脚本：`scripts/youtube/youtube-self.response.js`。
- Mac 使用 Surge 远程控制端口调试 iOS 请求、配置和脚本命中情况。

## 当前文件

Mac 上的 Surge iCloud 容器：

```text
/Users/mulanshan/Library/Mobile Documents/iCloud~com~nssurge~inc/Documents
```

推荐本地模块：

```text
modules/youtube-self-local.sgmodule
```

兼容旧本地模块：

```text
modules/youtube-ios-local.sgmodule
```

本地脚本：

```text
scripts/youtube/youtube-self.response.js
```

模块中必须使用相对脚本路径：

```ini
script-path=scripts/youtube/youtube-self.response.js
```

不要在 iOS 本地版模块中使用私有仓库 raw URL。私有仓库的 raw URL 在未鉴权时会 404，Surge iOS 不会自动带 Mac 上的 GitHub 登录态或 `gh` token。

## iOS 安装方式

Surge iOS 当前没有“从文件导入本地模块”的入口时，使用：

```text
模块 -> 新建本地模块
```

将 `modules/youtube-self-local.sgmodule` 的完整内容粘贴进去并保存。

安装后：

- 关闭旧的第三方 `Youtube (Music) Enhance`
- 启用 `YouTube Self Local`
- 重载配置
- 确认脚本资源 ready

## Mac 连接 iOS

iOS 配置里需要开启远程控制：

```ini
external-controller-access = 6170@0.0.0.0:6170
```

当前 iPhone 远程地址：

```text
6170@192.168.50.101:6170
```

Mac 使用：

```bash
/Applications/Surge.app/Contents/Applications/surge-cli --remote 6170@192.168.50.101:6170 --raw environment
```

应确认这些开关为 `true`：

```text
MitMEnabled
RewriteEnabled
ScriptingEnabled
```

HTTP API `1132` 在本次调试中不稳定，优先使用 `6170` remote controller。

## 常用调试命令

查看环境：

```bash
/Applications/Surge.app/Contents/Applications/surge-cli --remote 6170@192.168.50.101:6170 --raw environment
```

查看生效配置：

```bash
/Applications/Surge.app/Contents/Applications/surge-cli --remote 6170@192.168.50.101:6170 --raw dump profile effective
```

查看本地脚本资源：

```bash
/Applications/Surge.app/Contents/Applications/surge-cli --remote 6170@192.168.50.101:6170 --raw external-resource list
```

当前本地脚本资源 key：

```text
845662e2e79113cf1fd4459799396b8f
```

更新本地脚本资源：

```bash
/Applications/Surge.app/Contents/Applications/surge-cli --remote 6170@192.168.50.101:6170 --raw external-resource update 845662e2e79113cf1fd4459799396b8f
```

重载配置：

```bash
/Applications/Surge.app/Contents/Applications/surge-cli --remote 6170@192.168.50.101:6170 --raw reload
```

查看事件：

```bash
/Applications/Surge.app/Contents/Applications/surge-cli --remote 6170@192.168.50.101:6170 --raw dump event
```

查看 YouTube 请求命中：

```bash
/Applications/Surge.app/Contents/Applications/surge-cli --remote 6170@192.168.50.101:6170 --raw dump request
```

关注这些端点：

```text
youtubei/v1/player
youtubei/v1/get_watch
youtubei/v1/account/get_setting
youtubei/v1/browse
youtubei/v1/search
youtubei/v1/next
```

脚本命中时，请求备注应出现类似：

```text
Modified by script youtube.self.response
```

QUIC 被正确阻断时，会看到：

```text
Rule matched: AND ((DOMAIN,youtubei.googleapis.com), (PROTOCOL,UDP))
Block QUIC traffic due to MITM host matched
```

`surge-cli` 当前不能直接 `dump logbook`，会返回 `Unknown dump type`。Logbook 需要通过 Surge Mac Dashboard 查看远程 iOS 实例。

## 制作与更新流程

1. 在仓库中修改：

```text
scripts/youtube/youtube-self.response.js
modules/youtube-self-local.sgmodule
```

2. 语法检查：

```bash
node --check scripts/youtube/youtube-self.response.js
```

3. 同步脚本到 Mac 的 Surge iCloud 容器：

```bash
cp scripts/youtube/youtube-self.response.js "/Users/mulanshan/Library/Mobile Documents/iCloud~com~nssurge~inc/Documents/scripts/youtube/youtube-self.response.js"
```

4. 等待 iCloud 同步到 iPhone。

5. 在 Mac 上刷新 iOS 本地脚本资源：

```bash
/Applications/Surge.app/Contents/Applications/surge-cli --remote 6170@192.168.50.101:6170 --raw external-resource update 845662e2e79113cf1fd4459799396b8f
```

6. 重载 iOS Surge：

```bash
/Applications/Surge.app/Contents/Applications/surge-cli --remote 6170@192.168.50.101:6170 --raw reload
```

7. 将 YouTube 从 iOS 后台彻底划掉后重开。

8. 按测试清单验证。

## 当前脚本策略

稳定功能：

- `player`：清理播放广告字段，注入后台播放和画中画能力。
- `get_watch`：只处理其中的 player，不递归删除推荐/下一集容器。
- `account/get_setting`：注入后台播放设置入口和开关项。
- `googlevideo.com` 和 `youtubei.googleapis.com` 的 QUIC/UDP：模块规则拒绝，迫使回落到可 MITM 的 HTTPS。

保守处理：

- `next`：完全放行，避免破坏下一集、评论、播放列表和推荐容器。
- `browse/search`：只删除明确像单个广告卡片的 protobuf 块。

首页广告卡片识别标记包括：

```text
赞助商广告
Sponsored
ad_badge.eml-fe
inline_injection_entrypoint_layout.eml
googleads
pagead
doubleclick
```

重要经验：

- 不要对 `browse/search/next` 做无边界递归删除。
- 首页空白、搜索无结果、下一集无反应，通常说明列表容器被误删。
- 修这类问题时优先回到保守放行，再只针对单个广告卡片加窄规则。

## 测试清单

每次更新后测试：

- YouTube 首页能正常加载。
- 首页可以连续下滑。
- 搜索有新结果。
- 点视频可以播放。
- 点下一集有反应。
- 后台播放正常。
- 没有贴片视频广告。
- 首页 `赞助商广告` 卡片被隐藏。
- `account/get_setting` 仍被脚本改写，后台播放设置保留。

## 故障判断

如果本地脚本未生效：

- 检查 `external-resource list` 中脚本是否 `local=true` 且 `ready=true`。
- 检查生效配置里是否有 `FROM-MODULE:YouTube Self Local`。
- 检查 `[Script]` 是否为 `youtube.self.response`，且 `script-path=scripts/youtube/youtube-self.response.js`。
- 运行 `external-resource update <key>` 后再 `reload`。
- 重开 YouTube。

如果首页/搜索/下一集坏了：

- 先让 `browse/search/next` 放行。
- 保留 `player/get_watch/account/get_setting` 的处理。
- 再只针对明确广告卡片添加窄规则。

如果去广告或后台播放失效：

- 检查 `MitMEnabled=true`、`RewriteEnabled=true`、`ScriptingEnabled=true`。
- 检查 `youtubei.googleapis.com` 是否 MITM。
- 检查 QUIC 是否被拒绝。
- 检查 `player/get_watch/account/get_setting` 是否出现 `Modified by script youtube.self.response`。
