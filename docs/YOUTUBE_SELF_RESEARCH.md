# YouTube 增强模块：架构设计与能力边界

更新日期：2026-11-13。

## 设计定位

`rewrite/Surge/youtube-self.sgmodule` 是仓库唯一维护的 YouTube / YouTube Music 自有可审计模块，以零第三方依赖的原生 Protobuf 线格式编辑器处理客户端插入的播放广告、信息流赞助卡、Shorts 插播广告、后台播放/画中画能力注入及可选底栏精简。

- 模块：`rewrite/Surge/youtube-self.sgmodule`
- 脚本：`rewrite/Surge/scripts/youtube/youtube-self.response.js`
- 测试：`rewrite/Surge/scripts/youtube/youtube-self.response.test.js`

## 核心机制与安全护栏

1. **零 UTF-8 解码的 Protobuf 字节序列扫描**：针对 `browse`、`search`、`next`、`get_watch` 等可达数 MiB 的二进制响应，直接以预编码 UTF-8 `Uint8Array` 子序列匹配 `ItemSectionRenderer (50195462) -> RichItemContent (1)` 内的 EML/广告特征，在 `debug=false` 常态下实现 `0` 次大缓冲区 `TextDecoder.decode()` 分配，降低 iOS Network Extension 内存峰值与脚本延迟。
2. **Shorts 短视频流去广告（`reel/reel_watch_sequence`）**：识别并整条剥离顶层重复序列条目中携带明确广告 UI/网络特征（如 `reel_player_overlay_ad`、`ad_badge.eml-fe`、`adSlotRenderer`、`pagead`）的插播广告，保留 `ResponseContext` 与正常短视频条目，并设 `>50%` 误删熔断保护。
3. **iOS Protobuf 底栏精简开关（`guide` / `PivotBarRenderer 117866661`）**：暴露可选参数 `隐藏上传按钮`（`FEuploads` / `pivotBarIconOnlyItemRenderer 318370163`）、`隐藏Shorts入口`（`FEshorts`）与 `隐藏选段入口`（`FEmusic_immersive`），全部默认 `false`；仅按精确 Protobuf 字符串字段删除对应单标签，永不清空整条底栏。
4. **体积膨胀熔断与能力边界（SSAP）**：`account/get_setting*` 允许最高 `+256 B` 后台播放设置注入，其余端点严格限制 `+64 B` 防止损坏二进制消息；对于 YouTube 服务端直接拼接进音视频流的 SSAI/SSAP 实验广告，客户端 Protobuf 改写天然无法剥离，属已知上游边界。
