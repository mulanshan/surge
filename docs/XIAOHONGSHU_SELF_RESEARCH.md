# 小红书增强模块：社区调研、安全边界与真机计划

更新日期：2026-08-15。

## 结论

社区有多个仍可找到的 Surge 小红书模块。常见能力包括信息流/搜索/开屏去广告、
恢复图片与视频保存、去水印、实况照片与评论媒体下载。但大部分方案从可变 `main`
或第三方域名加载脚本，有些脚本记录原始响应或在本地持久化签名媒体 URL。这些做法不符合
本仓库的不可变发布、有限日志和最小数据处理要求。

本仓库因此新增一个自有单模块、单响应脚本的候选实现，不执行或复制第三方代码。
候选运行时代码随本仓库以 MIT 许可开源。

## 当前版本基线

- Apple Lookup API 于 2026-08-15 返回中国区小红书版本 `9.43`，发布日期为
  2026-08-14，Bundle ID 为 `com.xingin.discover`。
- 开发时本机为 Surge Mac `6.8.1 (12030)`。它可以校验模块和脚本语法，但不能代替
  小红书 9.43 在 iPhone 上的真实请求回归。
- Surge 官方文档确认：模块是主配置补丁；HTTPS 响应脚本必须命中 MITM hostname；
  同一响应最多执行一个 `http-response` 脚本。因此候选模块使用一个统一脚本，并把
  `max-size` 限制为 6 MiB。

参考：

- <https://manual.nssurge.com/profile/module.html>
- <https://manual.nssurge.com/http/mitm.html>
- <https://manual.nssurge.com/scripting/http-response.html>
- <https://apps.apple.com/cn/app/id741292507>

## 社区现状

1. [fmz200/wool_scripts](https://github.com/fmz200/wool_scripts) 是当前最活跃的同类项目之一。
   其 GPL-3.0 小红书脚本在提交
   [`2dfe1fa129085015a9abed46b4474d34d4426269`](https://github.com/fmz200/wool_scripts/commit/2dfe1fa129085015a9abed46b4474d34d4426269)
   更新至 2026-06-05，功能范围很广，包括评论视频/实况照片缓存和最佳码流选择。
   它同时存在打印原始 body 与持久化媒体 URL 的代码路径，本仓库没有采用。
2. [zirawell/R-Store](https://github.com/zirawell/R-Store) 的 GPL-3.0 Surge 模块于提交
   [`7e7b3f0603455b41866dce0814c79497990134a5`](https://github.com/zirawell/R-Store/commit/7e7b3f0603455b41866dce0814c79497990134a5)
   更新至 2026-07-13，覆盖去广告、去水印和保存开关。它的远程脚本仍指向可变
   `main`，而不是已审核的不可变 tag。
3. [QingRex/LoonKissSurge](https://github.com/QingRex/LoonKissSurge) 在提交
   [`150129485a2a697ded696d4c2e7013df76e6146c`](https://github.com/QingRex/LoonKissSurge/commit/150129485a2a697ded696d4c2e7013df76e6146c)
   于 2026-03-03 同步过小红书 Surge 模块。模块标注 RuCu6/fmz200 来源，但执行代码从
   `kelee.one` 加载，无法用本仓库的 manifest 重建完整字节。
4. Google 与 GitHub 代码搜索还能找到大量镜像、合集和个人备份。它们大多从上述项目或
   `kelee.one` 再引用，不算独立证据。

## 本仓库候选实现

- 候选模块：`rewrite/Surge/candidates/xiaohongshu-self.sgmodule`
- 自有脚本：`rewrite/Surge/scripts/xiaohongshu/xiaohongshu-self.response.js`
- 行为测试：`rewrite/Surge/scripts/xiaohongshu/xiaohongshu-self.response.test.js`
- 候选发布：`surge-self-v2026.08.15`，在 manifest 注册和 tag 创建前不能安装。

功能边界：

- 信息流、搜索结果和笔记容器只删除带非空 `ads_info`、`is_ad`、明确广告 `type`
  等强标志的整条目；空 `ads_info: {}`、商品笔记、直播、话题和普通推荐保留。
- 首个候选版不修改 `media_save_config`、下载开关、搜索提示或通用系统配置。这些私有字段
  只见于社区实现，在本仓库获得小红书 9.43 的自采、脱敏一方结构证据前不会纳入。
- 不加入整个 `xiaohongshu.com` 的拒绝规则，不修改账号、购买、发布、评论或聊天接口。
- 调试日志只记录端点分类和计数，不记录 URL、查询参数、笔记 ID 或响应内容。

## 真机验证门禁

1. 先按发布流程注册候选 manifest，创建不可变 tag，并核对脚本 SHA-256。
2. 在非关键 iPhone 上用候选模块测试小红书 9.43：冷启动、首页、关注、搜索、
   图文笔记和视频笔记；反向确认保存、下载和搜索提示未被改写。
3. 反向检查登录、关注/取关、点赞、收藏、评论、发布、分享、商品和聊天功能。
4. 确认没有 MITM 失败、脚本异常、超限响应或被删除的正常卡片。
5. 在上述证据入库前保持 `candidate`，不将合成测试或社区更新日期当作真机结论。
