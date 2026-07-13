# Instagram 调研与真机边界

## 结论

截至 2026-07-12，App Store 美国区 Instagram 当前版本为 `437.2.0`（2026-07-07 发布）。在 iPhone Surge 真机上对 `i.instagram.com` 做单域 MITM 探针时，连接在 TLS 握手后立即由客户端关闭，Surge 连续记录：

```text
[MITM] MITM failed. Client closed connection just after TLS handshake, it might because of certificate pinning.
```

撤掉探针后，`i.instagram.com:443` 立即恢复正常 TCP 连接。由此确认：原生 App 的信息流、探索和 Reels 主响应目前不能通过 Surge HTTP Response Script 无损清理。

正式模块采用以下边界：

- 原生 `i.instagram.com`、`graph.instagram.com`、gateway、聊天和媒体 CDN 不做 MITM。
- `www.instagram.com` Web Feed 入口启用响应脚本，覆盖当前 Web GraphQL 和旧版 feed/discover/clips 路径。
- 仅删除具有明确广告、赞助、推广、付费合作标志的完整节点；未知结构原样保留。
- 规则层只拒绝同时满足 `netseer-ipaddr-assoc` 主机标记与 `fbcdn.net` 域名后缀的辅助探测请求；变化前缀由关键字条件覆盖，但不会扩大到其他 `ipaddr-assoc` 或 Meta SDK 域名。

## Surge 官方依据

- [HTTPS Decryption](https://manual.nssurge.com/http-processing/mitm.html)：Surge 只对 `[MITM] hostname` 指定的主机解密；官方明确说明，使用证书或 CA pinning 的应用在启用解密后可能发生问题。
- [HTTP Response](https://manual.nssurge.com/scripting/http-response.html)：`http-response` 脚本只有在 `requires-body=true` 且 Surge 能取得响应体时才能修改 `body`；`$done({})` 表示保持原响应不变。

这意味着：证书钉扎阻止 HTTPS 解密时，响应脚本看不到原生 Instagram JSON，无法在网络层识别并删除其中的广告对象。

## 社区实现核对

- [blackmatrix7/ios_rule_script Instagram](https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/Surge/Instagram) 当前公开内容是 `instagram.com`、`cdninstagram.com`、`instagr.am` 和 `DOMAIN-KEYWORD,instagram` 的分流规则，不是去广告响应脚本。
- 2026-07-12 核对 blackmatrix7、fmz200、app2smile、VirgilClyne、ddgksf2013、Maasea 等常见公开规则/脚本仓库，没有找到能绕过当前 iOS Instagram 证书钉扎、同时保持原生 App 正常联网的 Surge 专用实现。
- 浏览器 DOM 屏蔽、越狱 tweak 或 App 注入可以在客户端界面层隐藏广告，但不属于 Surge 模块能力范围，也不应伪装成可直接移植的网络脚本。

## 当前模块覆盖

主模块响应脚本只匹配 `www.instagram.com`：

- `/api/graphql`
- `/graphql/query`
- `/api/v1/feed/`
- `/api/v1/discover/`
- `/api/v1/clips/`

脚本识别直接布尔标志、广告 ID/元数据、广告类型、Sponsored/Promoted/广告/推广标签、paid partnership，以及 `edge -> node`、`media_or_ad`、`item` 等包装结构。没有任何明确广告标志时返回 `$done({})`，不重新序列化响应。

`injected_*` 只是 Instagram 对注入式 Feed 单元的容器命名，不等同于广告标志。脚本会递归检查其中的每个实体：保留正常推荐与未知结构，只删除带 `is_ad4ad`、`is_bloks_ad`、`ad_client_token`、`ad_tracking_params`、`sponsored_info`、广告类型或其他直接广告标志的实体。只有语义本身明确为广告集合的 `ads`、`injected_ads`、`sponsored_items` 等键才整组清空。

2026-07-13 的规则复核同时撤掉了两个缺乏 Instagram 专属证据的扩大项：

- 不拒绝 `connect.facebook.net`；它是跨 Meta 产品使用的 Web SDK 主机，当前真机日志不足以证明其请求只承载 Instagram 广告。
- 不使用通用 `DOMAIN-KEYWORD,ipaddr-assoc`；该条件可能命中无关应用或未来正常业务主机。

当前保留的规则等价于“主机名含 `netseer-ipaddr-assoc` 且域名后缀为 `fbcdn.net`”，既适配日志中变化的前缀，也把影响范围限制在已验证的探测形态。
