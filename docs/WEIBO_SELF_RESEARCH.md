# 微博去广告模块：社区调研、安全边界与真机计划

更新日期：2026-08-15。

## 结论

Surge 社区中有多个微博国内版/国际版去广告方案。它们通常处理开屏、首页、热搜、搜索、
详情、评论和超话推广。部分方案还会伪造会员 App 图标、非会员皮肤或大幅删除导航/
推荐内容。这些能力不属于安全的去广告范围，本仓库明确排除。

本仓库新增的候选版只依赖自有响应脚本，对已知 Feed 类接口中具有强广告标志的
整个数组条目进行删除，未知结构原样放行。
候选运行时代码随本仓库以 MIT 许可开源，不执行或复制第三方代码。

## 当前版本基线

- Apple Lookup API 于 2026-08-14 返回中国区微博版本 `16.8.1`，发布日期为
  2026-08-13，Bundle ID 为 `com.sina.weibo`。
- 开发时本机为 Surge Mac `6.8.1 (12030)`；尚无微博 16.8.1 的 iPhone 真机请求和功能回归证据。
- 官方文档要求 HTTPS 脚本与 Map Local 使用的主机必须进入 MITM，并提醒 iOS 对缓冲
  响应有内存限制。候选脚本使用精确端点正则与 6 MiB `max-size`。

参考：

- <https://manual.nssurge.com/profile/module.html>
- <https://manual.nssurge.com/http/mitm.html>
- <https://manual.nssurge.com/scripting/http-response.html>
- <https://apps.apple.com/cn/app/id350962117>

## 社区现状

1. [fmz200/wool_scripts](https://github.com/fmz200/wool_scripts) 的 GPL-3.0 微博模块包含两个自有脚本、
   `zmqcherish/proxy-script` 第三方脚本以及“解锁微博会员 APP 图标”脚本。其专用广告脚本在
   [`ed3fb8e1267ce14279c5b234dd4e47b06162e512`](https://github.com/fmz200/wool_scripts/commit/ed3fb8e1267ce14279c5b234dd4e47b06162e512)
   于 2026-06-24 更新，证明社区仍在跟进微博结构，但其功能与供应链范围大于本仓库。
2. [zirawell/R-Store](https://github.com/zirawell/R-Store) 的 GPL-3.0 模块于提交
   [`6c1089cf3a552aca8db15583de4f2199391cf43d`](https://github.com/zirawell/R-Store/commit/6c1089cf3a552aca8db15583de4f2199391cf43d)
   在 2026-05-09 更新。它覆盖大量 API，并包含会员图标响应改写；脚本 URL 指向可变 `main`。
3. [QingRex/LoonKissSurge](https://github.com/QingRex/LoonKissSurge) 于提交
   [`150129485a2a697ded696d4c2e7013df76e6146c`](https://github.com/QingRex/LoonKissSurge/commit/150129485a2a697ded696d4c2e7013df76e6146c)
   在 2026-03-03 同步过模块。模块标注 RuCu6/zmqcherish 来源，执行代码由 `kelee.one`
   提供，不具备本仓库所要求的不可变脚本 manifest。
4. [ddgksf2013/Rewrite](https://github.com/ddgksf2013/Rewrite) 的微博/微博国际版合并配置标注
   `V2.0.114`、`2025-09-16`，其对应脚本最后一次可见更新是
   [`4ff1d89274c694454ac3a494ae1a2d4cfd1edf56`](https://github.com/ddgksf2013/Scripts/commit/4ff1d89274c694454ac3a494ae1a2d4cfd1edf56)
   。它的功能列表证明微博广告位长期变动，不能只凭历史端点就声称当前版本有效。

上述项目只用于交叉确认端点家族和广告强标志。本仓库没有复制、分发或执行它们的脚本。

## 本仓库候选实现

- 候选模块：`rewrite/Surge/candidates/weibo-self.sgmodule`
- 自有脚本：`rewrite/Surge/scripts/weibo/weibo-self.response.js`
- 行为测试：`rewrite/Surge/scripts/weibo/weibo-self.response.test.js`
- 候选发布：`surge-self-v2026.08.15`，在 manifest 注册和 tag 创建前不能安装。

功能边界：

- 脚本只处理已列入白名单的 `api.weibo.cn` / `mapi.weibo.cn` / `mapi.weibo.com`
  Feed、搜索、详情和评论 JSON 接口；个人页、账号、私信和通知接口排除。
- 只删除带 `is_ad`、`mblogtypename` 明确含“广告”、`promotion.type=ad`、
  `ads_material_info.is_ads=true` 等强标志的整个数组条目。普通热议、话题、用户、商品或未知卡片不因
  `card_type` 数字被删除。
- Map Local 只覆盖路径名明确为广告实时、预加载或素材接口的精确路径；
  不整域拒绝 `biz.weibo.com` 或 `uve.weibo.com`。
- 只在已知 Feed 容器键中过滤，不递归删除未知数组；不调用 `new.vip.weibo.*`，不修改会员、皮肤、
  App 图标、余额、钱包、关注关系或账号状态。
- 调试日志只记录删除计数或放行原因，不记录 URL、微博 ID、用户 ID 或响应内容。

## 真机验证门禁

1. 注册并创建不可变候选 tag，在测试设备上确认脚本 SHA-256 与 manifest 一致。
2. 在微博 16.8.1 上测试冷启动、关注/推荐 Feed、搜索、热搜、详情、评论、转发、超话和视频流。
3. 反向检查登录、发博、图片/视频上传、关注/取关、私信、收藏、会员、钱包和购买链路。
4. 检查 Surge 请求记录中的 `modified`、脚本异常、MITM 失败、超限响应和错误空白卡片。
5. 在候选 tag 的真机证据入库前保持 `candidate`，不从社区提交日期推断微博 16.8.1 已验证。
