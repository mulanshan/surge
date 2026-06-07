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

唯一远程安装地址：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/modules/youtube-self.sgmodule
```

这是当前仓库唯一维护的 YouTube 去广告与后台播放模块。仓库里只保留这一个 YouTube 模块和一个响应脚本：

- 模块：`modules/youtube-self.sgmodule`
- 脚本：`scripts/youtube/youtube-self.response.js`

安装或测试时，请在 Surge 里删除所有旧的 YouTube 模块，包括 `Youtube (Music) Enhance`、`YouTube Self Fast`、`YouTube Self iOS`、`YouTube Self Local`、`YouTube Safe Lite`、`YouTube Readable Enhance` 和所有抓包/调试模块，然后只添加上面的唯一安装地址。

安全边界：

- 不使用第三方脚本
- 只从 `mulanshan/surge` 加载 `scripts/youtube/youtube-self.response.js`
- 脚本不发起外部请求
- 不上传请求、响应、账号、cookie 或 token
- 不 MITM `www.google.com` / `www.google.com.hk` 这类更泛的 Google 主机名

功能范围：

- 只处理 `youtubei.googleapis.com` 的 `player`、`get_watch`、`account/get_setting`、`account/get_setting_values`
- 不处理 `browse`、`next`、`search`，避免首页、推荐、搜索和正常视频列表被误伤
- 不 MITM `*.googlevideo.com`
- 不拒绝 `googlevideo.com` UDP/QUIC
- 对 `www.youtube.com/pagead`、`pcs/activeview`、广告型 `ptracking` 和 `www.googleadservices.com` 广告跳转链路返回空响应
