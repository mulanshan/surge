# 微信去广告模块：调研、能力边界与真机验证计划

更新时间：2026-07-13

## 结论

首版只处理 Surge 能稳定观察到的普通 HTTP(S) 流量：公众号文章广告接口、公众号商品推广接口，
以及三个用途明确的小程序广告素材主机。它不能安全承诺清除朋友圈、视频号或微信原生信息流广告。

2026-07-13 通过 Apple Lookup API 核对的中国区微信版本为 `8.0.75`，发布日期为 2026-06-14。
这类版本信息会变化，因此模块最终行为仍以本次 iOS 真机请求为准。

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

## 首版实现

### 公众号文章广告

仅 MITM `mp.weixin.qq.com`，只对下列精确路径生效：

- `/mp/getappmsgad`：自写响应脚本只识别根对象中的 `advertisement_num` 和
  `advertisement_info`。字段不存在、类型未知、JSON 解析失败或路径不匹配时立即原样放行。
- `/mp/cps_product_info`：公众号文章商品推广专用接口，通过 Map Local 返回空 JSON。

响应脚本最大读取 `524288` 字节，不使用旧社区规则常见的无限制 `max-size=0`。脚本只处理成功的
HTTP 响应，接受 Surge 官方支持的字符串、`Uint8Array` 与 `ArrayBuffer` 响应体，兼容单个 UTF-8 BOM，
并保持字符串型广告计数字段的原始类型。所有出现的目标字段会先整体完成类型校验；任一字段属于未知
结构时整包原样放行，不做部分修改。调试模式只记录命中结果或安全的放行原因，不记录 URL 参数、
请求头、Cookie、token 或原始响应体。

`/mp/cps_product_info` 的 Map Local 响应显式设置 `Content-Type: application/json`。Surge 官方说明指出
`data-type=text` 未指定 header 时默认使用 `text/plain`；明确 JSON 类型可以避免客户端按错误 MIME 类型
处理空对象。

### 小程序广告素材

只拒绝三个精确主机：

- `wxa.wxs.qq.com`
- `wximg.wxs.qq.com`
- `wxsmw.wxs.qq.com`

不使用 `DOMAIN-SUFFIX,wxs.qq.com`。2025 年的 iOS 社区实测指出整后缀拒绝虽然可能挡住公众号广告图片，
但会留下广告位置并扩大误伤范围：
[V2EX discussion](https://www.v2ex.com/t/1135567)。

## 明确排除

- 不整域拒绝 `weixin.qq.com`、`wxs.qq.com`、`servicewechat.com`、`tenpay.com`、`qpic.cn`、
  `qlogo.cn` 或微信 IP 段。
- 不默认拦截 `relatedarticle`、`masonryfeed`、`relatedsearchword`；推荐内容不等于广告。
- 不默认拦截 `jsmonitor`、`report` 或 `ad_complaint`；遥测不等于广告，投诉接口也可能是用户功能。
- 不首版加入 `szextshort.weixin.qq.com/cgi-bin/mmoc-bin/ad/` 或更多视频素材域；只有当前真机日志证明
  它们仍走普通 HTTP(S) 且用途明确后再评估。
- 不修改账号、联系人、消息、文章正文、评论、赞赏、小程序登录、微信支付、订单或会员状态。

## 社区方案如何使用

社区材料只用于确认接口名称、误伤历史和能力限制，没有复制或运行第三方脚本。最终脚本全部在本仓库
重新实现，无外部请求、无 Cookie/token 读取、无请求或响应上传。

- [NobyDa historical WeChat script](https://github.com/NobyDa/Script/blob/master/QuantumultX/File/Wechat.js)：
  用于确认 `/mp/getappmsgad` 的历史字段名称。
- [2026-07 community module snapshot](https://github.com/Repcz/Tool/blob/699238c6148b9c279785911b867925d5fbbd0bc6/Surge/Module/Kelee/Weixin_Official_Accounts_remove_ads.sgmodule)：
  用于核对当前社区仍使用的接口范围；其中宽泛域名规则没有照搬。

## 真机验证清单

1. 在 iOS Surge 安装候选模块，确认 MITM、Rewrite 和 Scripting 已开启，且 Surge CA 已安装并信任。
2. 打开微信 8.0.75 的公众号文章，确认正文、图片、评论、赞赏和跳转正常。
3. 观察 `/mp/getappmsgad` 是否出现、是否由脚本修改、是否有脚本错误；只记录脱敏后的 hostname、path、
   状态和命中结果。
4. 打开包含商品推广的文章，确认 `/mp/cps_product_info` 返回空 JSON 且正文不受影响。
5. 使用常用小程序，确认三个精确素材主机被拒绝后登录、页面加载、支付和正常图片不受影响。
6. 朋友圈和视频号只观察，不把“仍有广告”当作脚本失效；它们属于已声明的 MMTLS 限制。

完成上述回归并确认无脚本错误后，模块才可从 `candidate` 调整为 `limited` 或 `stable`。

## 2026-07-13 iOS 运行时检查

- 目标 iOS Surge 实例的 External Controller 与 HTTPS HTTP API 均可认证。
- `微信` 模块同时出现在 `available` 与 `enabled`，Rewrite、Scripting、MITM 均已开启。
- `wechat.self.response` 已加载并启用，固定 tag 脚本与工作区源码 SHA-256 一致。
- 使用 Surge iOS 自身的脚本评估引擎和合成的 `/mp/getappmsgad` 响应验证，广告计数被清零，
  广告数组被清空，并产生不含敏感数据的完成日志。
- 当时最近请求缓冲区没有真实 `/mp/getappmsgad` 或 `/mp/cps_product_info` 命中，因此公众号文章、
  商品推广与常用小程序的人工回归仍需保留为发布前门禁，不能仅凭合成测试晋升为 `stable`。
