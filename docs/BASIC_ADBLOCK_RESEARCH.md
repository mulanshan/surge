# 基础去广告模块：调研、日志证据与维护边界

更新时间：2026-07-12

## 结论

仓库以后只保留一个通用入口：`rewrite/Surge/basic-adblock.sgmodule`。它只做域名级
`REJECT`，不包含 JavaScript、MITM、URL Rewrite、Map Local、IP 规则或宽泛关键词。

番茄小说、YouTube、Instagram、高德地图、扫描全能王、京东等专用模块继续处理各自的路径、响应体、
证书钉扎和界面广告。基础模块不接管这些 App 的第一方 API、CDN、登录、购买、同步或内容域名。

旧地址 `rewrite/Surge/fanqie-novel-adblock.sgmodule` 保留为兼容入口，并与新模块使用相同规则；
新旧地址不要同时启用。旧 `rule/Surge/fanqie-novel-adblock.list` 只为已有配置冻结保留，主配置不再引用。
旧番茄专用能力迁入 `rewrite/Surge/fanqie-novel-self.sgmodule`，与基础模块配合使用。

## Surge 官方约束

- [Module](https://manual.nssurge.com/others/module.html)：模块是主配置补丁，模块规则插入主配置
  `[Rule]` 顶部；模块规则只能使用 `DIRECT`、`REJECT`、`REJECT-TINYGIF`。模块启用状态不会跨设备同步。
- [Rule](https://manual.nssurge.com/rule.html)：规则自上而下匹配，首条命中即结束。基础模块必须避免
  把混合业务域名放到顶部误杀。
- [Domain-based Rule](https://manual.nssurge.com/rule/domain-based.html)：`extended-matching` 和
  `DOMAIN-SET` 适合大规模域名匹配；当前自有规则量很小，因此直接使用可审计的精确
  `DOMAIN` / `DOMAIN-SUFFIX`。
- [Reject Policy](https://manual.nssurge.com/policy/reject.html)：常规场景优先使用 `REJECT`。
  `REJECT-DROP` 不在模块允许的策略范围内，`REJECT-TINYGIF` 也不适合 JSON/API。
- [URL Rewrite](https://manual.nssurge.com/http-processing/url-rewrite.html)、
  [Map Local](https://manual.nssurge.com/http-processing/mock.html) 与
  [MITM](https://manual.nssurge.com/http-processing/mitm.html)：HTTPS 路径处理依赖 MITM，证书钉扎、
  QUIC 回落和错误响应形状都可能破坏 App，因此全部留给专用模块。
- [URL Scheme](https://manual.nssurge.com/others/url-scheme.html)：新模块可用
  `surge:///install-module?url=...` 安装；启用后仍须逐台设备确认。

首版也不使用 `pre-matching`。它会在 DNS/TCP 阶段以更高优先级拒绝连接，误杀后更难由后续规则纠正。

## 社区方案核对

下列方案只用于范围、误杀和维护方式对照，没有把第三方清单复制或运行时混载进本模块：

| 方案 | 2026-07-12 核对结果 | 本仓库决定 |
| --- | --- | --- |
| [blackmatrix7 AdvertisingLite](https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/Surge/AdvertisingLite) | 38,069 条规则，另有广域 Rewrite/MITM 模块 | 不引入 1,229 条 URL Rewrite 与 902 个 MITM hostname；避免移动端误杀和证书问题 |
| [Sukka reject](https://github.com/SukkaW/Surge) | 基础 Domain-set 约 115,510 条，并另分 non-IP、drop、no-drop、URL regex、IP | 不把广告、隐私、反挖矿、恶意网址、HTTPDNS 等不同目标合并进基础层 |
| [anti-AD](https://github.com/privacy-protection-tools/anti-AD) | Surge Domain-set 约 98,803 条，有长期白名单和误杀讨论 | 用作候选复核，不直接复制近十万条聚合数据 |
| [app2smile rules](https://github.com/app2smile/rules) | 通用广告联盟与起点、B 站、贴吧等专用模块分开 | 采用“基础网络层 + 专用 App 模块”的分层思路，不复制第三方脚本 |

社区历史误杀也用于确定排除边界，例如 `imasdk.googleapis.com` 可能影响视频播放、
`activity.windows.com` 可能影响 Microsoft 同步、`mmstat.com` 可能影响登录/验证码。
这些混合用途域名不会因为名称像统计或广告就加入基础模块。

## 本机 Surge 日志证据

### Google 广告网络

- iPhone 最近请求中出现 `pagead2.googlesyndication.com/pagead/js/adsbygoogle.js`。
- Mac TrafficStat 2026-06：`doubleclick.net` 294 次、`googleadservices.com` 103 次、
  `googlesyndication.com` 82 次。
- Mac TrafficStat 2026-07：三者分别 85、13、15 次；来源包含 Chrome，也出现于其他 App 的 Web 内容。

因此 Google 广告域从扫描全能王专用模块中的“通用能力”提升到基础层。扫描全能王模块同步移除
Google、腾讯、AppsFlyer、Adjust 等全局第三方规则，只保留自身第一方接口与响应处理。新分层实例
显示为“扫描全能王 Self v2”，用于和设备上可能缓存的旧模块区分。

### 腾讯与字节广告 SDK

- 扫描全能王日志确认 `a.gdt.qq.com`、`sdk.e.qq.com` 的 `/sdk`、`/perf`、`/event`、`/ola/v2` 请求。
- 番茄历史日志中 `dig.bdurl.net` 多轮稳定命中，汇总拒绝 110 次。
- `ads5-normal-lq.zijieapi.com` 有真机命中；`ma.zijieapi.com` 虽高频，但更像共享遥测，未进入核心规则。
- 旧模块的穿山甲路径明确指向 `/obj/ad-app-package/`、`/obj/ad-pattern/` 和
  `/api/ad/union/sdk/`。基础模块只拒绝名称和用途均明确的广告专用主机，不再 MITM
  `is.snssdk.com` 或混合内容 CDN。

### 浏览器广告网络

Mac 月度统计还持续出现 `adnxs.com`、`adnxs-simple.com`、`adsafeprotected.com`、
`ad-score.com`、`ad-m.net`、`adkernel.com`、`teads.tv` 与 `googleadsserving.cn`。
这些都是独立广告网络域名，适合基础层精确拒绝。

本轮实时快照读取了 Mac 最近 200 条和 iPhone 最近 50 条请求。除既有广告网络外，没有发现足够安全的
新候选；`QUIC-BLOCK`、Sentry、Crashlytics、OpenTelemetry 等不能当作广告证据。

## 明确排除

- 番茄第一方：主业务、图片和音视频域名不进基础层；精确 `log/rtlog/mon` 主机只放在番茄 Self。
- 字节混合用途：`snssdk.com`、`zijieapi.com`、`byteimg.com`、`bytegecko.com`、
  `douyinpic.com`、`ecombdapi.com`、`ecombdimg.com`、直播/小游戏/动态资源。
- 专用 App：`intsig.net`、`camscanner.com`、`amap.com`、京东、YouTube、Instagram 第一方域名与接口。
- 诊断与配置：Sentry、Crashlytics、Datadog、OpenTelemetry、`oaistatsig.com`。
- 购买与归因：收据、订单、订阅、支付、AppsFlyer、Adjust、`app-measurement.com`。
- 系统与网络：Apple 分析、HTTPDNS、DoH、PCDN、恶意网址、反挖矿；这些应是独立可选模块，而不是基础广告层。

## 维护流程

1. 从 Surge 日志只聚合域名、次数、策略和规则，不公开 URL 参数、Cookie、账号或 token。
2. 候选必须满足：本机真实出现且用途明确，或得到至少两个成熟社区来源交叉确认且不存在混合业务证据。
3. 第一方 App 接口、路径规则、响应体清理和任何 MITM 一律进入专用模块。
4. 修改后运行 `python3 scripts/check-basic-adblock.py`，确认新旧入口一致、没有高风险域名和禁止节。
5. 先在 `main` 验证，再更新外部资源；Mac、iPhone、iPad 分别检查 `available` 与 `enabled`。
6. 出现误杀时直接从基础模块删除该规则。不要用模块内 `DIRECT` 白名单掩盖，因为这会绕过主配置原有分流策略。
