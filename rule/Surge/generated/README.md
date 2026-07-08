# Generated Surge Rules

这些文件是公开分发版规则集。每个 `.list` 文件都是不带策略组决策的 Surge
`RULE-SET` 文件，具体策略由主配置中的 `RULE-SET,...,<policy>` 决定。

生成脚本和上游源清单保存在私有维护仓库中，不在公开分发仓库发布。

| ID | File | Suggested policy | Unique rules |
| --- | --- | --- | ---: |
| microsoft | `microsoft.list` | `DIRECT` | 671 |
| china-direct | `china-direct.list` | `DIRECT` | 3754 |
| private-tracker | `private-tracker.list` | `DIRECT` | 248 |
| apple | `apple.list` | `DIRECT` | 81 |
| google | `google.list` | `自动` | 698 |
| openai | `openai.list` | `自动` | 35 |
| telegram | `telegram.list` | `Proxy` | 30 |
| apple-tv | `apple-tv.list` | `流媒体` | 9 |
| youtube | `youtube.list` | `自动` | 190 |
| netflix | `netflix.list` | `绿云` | 1157 |
| bahamut | `bahamut.list` | `流媒体` | 8 |
| disney | `disney.list` | `流媒体` | 173 |
| hbo-usa | `hbo-usa.list` | `流媒体` | 11 |
| prime-video | `prime-video.list` | `流媒体` | 18 |
| streaming | `streaming.list` | `自动` | 321 |
| paypal | `paypal.list` | `自动` | 248 |
| global | `global.list` | `Proxy` | 1265 |
