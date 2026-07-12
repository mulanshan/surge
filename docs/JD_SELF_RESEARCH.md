# 京东 Self 社区调研与设计边界

调研日期：2026-07-12。

## 当前客户端

- Apple 中国区 App Store 的京东 App 当前页面显示版本 `15.8.50`，更新日期为 2026-07-02。
- App Store 页面：<https://apps.apple.com/cn/app/id414245413>
- 2026-07-12 在 iOS Surge 的脱敏真机请求中确认当前版本使用无后缀 `uniformRecommend`；自有模块同时兼容它和社区旧方案中的 `uniformRecommend0/6`。
- 第二轮脱敏真机监控确认 15.8.50 同时使用 `https://api.m.jd.com/`、`/api`、`/client.action`，部分 POST 请求把 `functionId` 放在请求体中。社区只匹配 `/client.action?functionId=...` 的写法会漏掉当前链路。

## 社区是否已有类似方案

有，但公开方案大多不是“完全自有、单仓库可审计”的实现。

1. QingRex/LoonKissSurge 的 `京东去广告.sgmodule` 汇总了 RuCu6、Maasea 等人的思路，模块本身仍从 `kelee.one` 加载远程 JavaScript。它覆盖的主要入口包括：
   - `basicConfig`
   - `deliverLayer`
   - `getTabHomeInfo`
   - `myOrderInfo`
   - `orderTrackBusiness`
   - `personinfoBusiness`
   - `searchBoxWord`
   - `start`
   - `stationPullService`
   - `uniformRecommend0` / `uniformRecommend6`
   - `welcomeHome`
2. 该社区模块还拒绝随机子域 `jddebug.com/diagnose`，并关闭 `basicConfig` 中的 socket 诊断上报和 HTTPDNS 开关。
3. Maasea 当前公开的 `sgmodule` 仓库仍在维护，但 2026-07-12 的公开树中没有京东相关文件；聚合模块引用的京东脚本并不在该作者当前公开仓库内。
4. blackmatrix7 的旧 AllInOne 大合集虽然存在“京东_开屏去广告”标签，但对应 URL 是 `hd.mina.mi.com/splashscreen/alert`，与京东 `api.m.jd.com` 主链路不一致，不适合作为当前京东实现依据。

参考页面：

- <https://github.com/QingRex/LoonKissSurge/blob/main/Surge/%E4%BA%AC%E4%B8%9C%E5%8E%BB%E5%B9%BF%E5%91%8A.sgmodule>
- <https://github.com/Maasea/sgmodule>
- <https://github.com/blackmatrix7/ios_rule_script/blob/master/rewrite/Surge/AllInOne/AllInOne.sgmodule>

本仓库只借鉴公开方案反复出现的接口分类，不复制其脚本、字段处理代码或远程依赖。

## 本仓库实现

- 模块：`rewrite/Surge/jd-self.sgmodule`
- 脚本：`rewrite/Surge/scripts/jd/jd-self.response.js`
- 测试：`rewrite/Surge/scripts/jd/jd-self.response.test.js`

设计原则：

- 只 MITM `api.m.jd.com`，不做 `jd.com` 整域 MITM 或拒绝。
- 模块覆盖当前观察到的 `/`、`/api`、`/client.action` 三种入口，但脚本先从 URL 或最多 1 MiB 的请求体中提取 `functionId`；不在内置白名单中的请求立即原样放行，不解析响应体。
- 当前版本真机出现的 `logConfig`、`netMonitor`、`weGameIcon`、`getStaticResource`、`interact_pre_executor`、`resources_delivery` 等接口暂不拦截：仅凭名称不足以证明它们是广告响应。
- 只清理具有明确广告标志、广告类型、广告字段名或“广告/推广”等标签的节点。
- 账号、购物车、商品、价格、订单、支付、退款、地址、物流、PLUS、会员、优惠券和钱包子树受到保护，不递归改写。
- 不伪造会员、价格、余额、优惠、订单或支付状态。
- 脚本没有网络请求、动态代码、Cookie 读取或数据上传能力。

## 需要真机继续确认的部分

京东响应结构会随版本和 AB 实验变化。首版采用“识别不到就原样放行”，因此安全优先，但不承诺一次清除所有广告。

真机验证时应打开模块调试参数，依次检查：

1. 冷启动开屏和启动弹窗。
2. 首页顶部横幅、浮层和营销楼层。
3. “我的”页面推广卡。
4. 订单列表和物流页是否只移除推广、保留订单主体。
5. 搜索框热词与推荐内容。
6. 登录、加购、结算、支付、退款、地址管理、物流详情和 PLUS 权益是否完全正常。

若某个广告未被清理，应只增加该响应中经过脱敏确认的明确字段，不扩大到未知接口或业务域。
