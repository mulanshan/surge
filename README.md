# Mulanshan Surge

自用 Surge 大仓库。内容分成两类：

- `modules/`：各类模块、增强、去广告能力，可直接在 Surge 模块里订阅。
- `rules/`：分流用规则集，不自带策略，在主配置里通过 `RULE-SET` 指定策略组。

原 `mulanshan/surge-rules` 里的分流规则已迁入本仓库。旧仓库可继续保留作兼容入口；新配置建议统一使用 `mulanshan/surge`。

## 模块与去广告

### YouTube Self

文件：[modules/youtube-self.sgmodule](modules/youtube-self.sgmodule)

订阅地址：

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

### 番茄小说去广告

文件：[modules/fanqie-novel-adblock.sgmodule](modules/fanqie-novel-adblock.sgmodule)

模块订阅地址：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/modules/fanqie-novel-adblock.sgmodule
```

规则集地址：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/rules/fanqie-novel-adblock.list
```

如果不用模块，也可以在主配置 `[Rule]` 顶部加入：

```ini
RULE-SET,https://raw.githubusercontent.com/mulanshan/surge/main/rules/fanqie-novel-adblock.list,REJECT,extended-matching
```

功能范围：

- 拦截番茄小说和字节系广告、统计、监控、热更新资源域名
- 对穿山甲广告 SDK 和广告素材路径使用 URL Rewrite reject
- 不包含 JavaScript 脚本
- 仅对广告 SDK/素材域名追加 MITM hostname
- 不修改响应体

这个模块采用保守的域名拦截 + URL Rewrite 方式，不整域拒绝 `fqnovel.com`、`fanqienovel.com`、`snssdk.com` 等主业务域。规则参考 Surge 官方 Module 写法：`.sgmodule` 是模块，模块内的 `[Rule]` 需要带策略；`rules/fanqie-novel-adblock.list` 是规则集，规则集本身不带策略，由主配置里的 `RULE-SET,...,REJECT` 决定策略。

## 分流规则

规则集不包含策略，使用时在主配置 `[Rule]` 里指定策略组。个人规则应放在广泛的 China、Google、Microsoft、GitHub 等社区规则前面。

### AI / LLM / Coding

文件：[rules/ai.list](rules/ai.list)

```ini
RULE-SET,https://raw.githubusercontent.com/mulanshan/surge/main/rules/ai.list,Ai,extended-matching,no-resolve
```

用于补充 AI、LLM、AI 编程、模型服务和 AI 搜索域名。建议放在 Google、Microsoft、GitHub 等大规则前。

### 豆瓣

文件：[rules/douban.list](rules/douban.list)

```ini
RULE-SET,https://raw.githubusercontent.com/mulanshan/surge/main/rules/douban.list,Proxy,extended-matching,no-resolve
```

覆盖豆瓣网页、移动网页、App/API 和常见图片静态资源域名。

### TMDb

文件：[rules/tmdb.list](rules/tmdb.list)

```ini
RULE-SET,https://raw.githubusercontent.com/mulanshan/surge/main/rules/tmdb.list,TW,extended-matching,no-resolve
```

覆盖 The Movie Database 网站、API 和图片资源域名。

### 番茄小说回国分流

文件：[rules/fanqie-novel-cn.list](rules/fanqie-novel-cn.list)

```ini
RULE-SET,https://raw.githubusercontent.com/mulanshan/surge/main/rules/fanqie-novel-adblock.list,REJECT,extended-matching
RULE-SET,https://raw.githubusercontent.com/mulanshan/surge/main/rules/fanqie-novel-cn.list,China,extended-matching
```

如果人在中国大陆、不需要代理回国，第二行策略可以用 `DIRECT`。两条规则的顺序不要反过来，否则广告/日志域名会先被回国分流而不是拒绝。

命名为“番茄小说”的中文规则集地址仍然保留：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/rules/%E7%95%AA%E8%8C%84%E5%B0%8F%E8%AF%B4.list
```

## 示例配置

文件：[examples/rule-section.conf](examples/rule-section.conf)

这个示例展示个人规则、社区规则、流媒体规则和兜底规则的推荐顺序。使用前按自己的策略组名称替换 `Proxy`、`Ai`、`TW`、`Streaming`、`GreenCloud` 等名称。

## 日志导出与候选规则开发

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
