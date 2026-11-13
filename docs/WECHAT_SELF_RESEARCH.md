# 微信去广告模块：调研、能力边界与真机验证计划

更新时间：2026-11-13

## 结论

本模块只处理 Surge 能稳定解密与审计的普通 HTTP(S) 公众号流量与精确主机规则：覆盖公众号文章广告接口
（`/mp/getappmsgad` 与 `/mp/getappmsgext` 中的内嵌广告字段）、公众号带货返佣商品卡（`/mp/cps_product_info`），
并提供可选的公众号文末推荐流精简开关（`/mp/masonryfeed` 与 `/mp/relatedarticle`）、小程序广告素材策略开关与
WebView 前端异常遥测开关。它不能安全承诺清除朋友圈、视频号或微信原生 MMTLS 信息流广告。

## 为什么不做“全微信递归去广告”

微信大量原生流量使用 MMTLS，而不是 Surge 可直接解密和改写的常规 HTTPS。朋友圈、视频号和部分
原生 Feed 即使能看到目标 IP 或素材域，也未必能看到可安全修改的 JSON；强行整域拒绝容易留下空白卡片，
并可能影响文章、登录、小程序、支付或正常媒体。

- [Surge HTTPS Decryption](https://manual.nssurge.com/http-processing/mitm.html)：MITM 只处理配置的
  hostname；证书钉扎、自定义协议或不信任 CA 时会失败。
- [Surge Scripting](https://manual.nssurge.com/scripting/common.html)：响应脚本会占用 Network Extension
  内存，响应体大小必须有限制。
- [Citizen Lab MMTLS analysis](https://citizenlab.ca/research/should-we-chat-too-security-analysis-of-wechats-mmtls-encryption-protocol/)：
  微信使用独立的 MMTLS 协议承载大量核心流量，普通 HTTPS 工具无法覆盖全部链路。

## 2026-11-13 运行日志与社区调研升级要点

结合 iPhone（`Surge iOS 5.23.0`）与 Mac（`Surge Mac 6.9.1`）运行日志、`traffic-stat-host` 流量统计、
`https://mp.weixin.qq.com/` 实时 CSP 响应头以及 2025–2026 社区反馈，模块在 `surge-self-v2026.11.13.1`
完成以下增强：

### 1. 公众号接口精准覆盖与业务数据无损保留（仅 MITM `mp.weixin.qq.com`）

- `/mp/getappmsgad` 与 `/mp/getappmsgext`：除专用广告接口外，部分公众号图文模板会在扩展互动接口
  `/mp/getappmsgext` 中下发根级 `advertisement_num`、`advertisement_info`、`promotion_info`、
  `cps_ad_info` 或 `drama_advertisement_info`。自写脚本严格验证目标字段类型与 `base_resp.ret === 0`：
  仅清空明确广告字段，**100% 原样保留 `appmsgstat`（阅读数、点赞、在看）、`appmsg_album_info`（合集）、
  赞赏与评论开关**；无广告字段、后端返回错误码或结构未知时直接 `$done({})` 零改动直通。
- `/mp/cps_product_info`：由早期写死的 `[Map Local]` 空 `{}` 升级为脚本纳管，既受 `清理明确广告` 参数开关控制，
  又保留标准 `base_resp: { ret: 0 }` 与空列表结构，避免前端读取 `res.base_resp.ret` 抛出异常。
- `/mp/masonryfeed` 与 `/mp/relatedarticle`（默认直通）：通过 `隐藏文末推荐流:false` 默认保留相关阅读；
  用户主动改为 `true` 时，清空瀑布流列表并同步归零 `continue_flag` / `has_more` / `is_continue`，防止底部无限滚动重试。
- `max-size` 由 `524288` 提升至 `1048576`（`1 MiB`），兼顾富媒体互动元数据与 iOS Network Extension 内存安全边界。

### 2. 小程序广告素材防误杀与前端遥测参数化

- `小程序广告素材策略`（默认 `REJECT`，可选 `DIRECT`）：精确控制 `wxa.wxs.qq.com`、`wximg.wxs.qq.com`、
  `wxsmw.wxs.qq.com`。社区实测与微信官方 CSP 头（`style-src ... wxa.wxs.qq.com ...`）表明，当用户主动使用小程序
  “看激励视频领优惠券/小游戏奖励”时，硬编码 `REJECT` 可能导致回调失败；参数化后可一键切回 `DIRECT`，无需停用整个模块。
- `前端遥测策略`（默认 `REJECT-NO-DROP`，可选 `DIRECT`）：iPhone 月度流量统计确认 `badjs.weixinbridge.com`
  持续产生内置浏览器前端异常上报流量，默认采用 `REJECT-NO-DROP` 静默拒绝且不触发重试风暴；小程序开发者调试时可切回 `DIRECT`。

## 明确排除（防误伤边界）

- 不整域拒绝 `weixin.qq.com`、`wxs.qq.com`、`servicewechat.com`、`tenpay.com`、`wechatpay.cn`、
  `qpic.cn`、`qlogo.cn` 或微信 IP 段。
- 不拦截 `gdtimg.com` / `ugdtimg.com`（位于公众号官方 CSP 样式/图片源白名单，整域拦截会导致公众号裂图与小程序 UI 残缺；
  广点通控制入口由 `基础去广告模块` 精确拦截）。
- 不拦截 `wxsnsdy.wxs.qq.com` / `wxsnsdythumb.wxs.qq.com`（与视频号及公众号内嵌视频共用分发，拦截会导致视频转圈与封面丢失）。
- 不拦截 `dns.weixin.qq.com` / `aedns.weixin.qq.com`（封禁微信 HTTPDNS 无法解开 MMTLS 原生广告，反而引发弱网连接缓慢）。
- 不默认拦截 `/mp/appmsg_comment` 或 `/mp/ad_complaint`；不修改账号、联系人、消息、文章正文、评论、赞赏、小程序登录或微信支付。

## 社区方案如何使用

社区材料只用于确认接口名称、误伤历史和能力限制，没有复制或运行第三方脚本。最终脚本全部在本仓库
重新实现，无外部请求、无 Cookie/token 读取、无请求或响应上传。

- [NobyDa historical WeChat script](https://github.com/NobyDa/Script/blob/master/QuantumultX/File/Wechat.js)：
  用于确认 `/mp/getappmsgad` 的历史字段名称。
- [V2EX iOS WeChat domain discussion](https://www.v2ex.com/t/1135567)：
  用于交叉核对 `wxs.qq.com` 泛后缀与激励视频误伤边界。

## 真机验证清单

1. 在 iOS Surge 加载候选模块 `微信 (候选 2026.11.13.1)`（Mac 端保持不安装候选模块），确认外部资源全部 `ready=1`，
   且 `wechat.self.response` 锁定到不可变标签 `surge-self-v2026.11.13.1`。
2. 验证规则匹配：`wxa.wxs.qq.com` -> `REJECT`，`badjs.weixinbridge.com` -> `REJECT-NO-DROP`，
   `mp.weixin.qq.com` / `mmbiz.qpic.cn` / `wxsnsdy.wxs.qq.com` -> `DIRECT`。
3. 打开微信内的公众号文章与常用小程序，确认正文、图片、阅读点赞数、评论、跳转与小程序加载正常，无残留公众号文章广告，
   且 Surge 脚本与系统日志零报错后，将模块生命周期从 `candidate` 晋升为 `limited`。
