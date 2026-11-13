# 高德地图去广告模块：社区调研与安全边界

更新日期：2026-11-13。

## 设计定位

高德地图去广告模块采用“单模块 + 单自有响应脚本 + 最小 MITM 主机集合”维护，专注清理开屏广告、消息盒子推广、首页流广告卡片与搜索框热词推广，不触碰地图瓦片、定位、路线规划、导航语音、打车订单与账号接口。

- 模块：`rewrite/Surge/amap-self.sgmodule`
- 脚本：`rewrite/Surge/scripts/amap/amap-self.response.js`
- 测试：`rewrite/Surge/scripts/amap/amap-self.response.test.js`

## 社区对照与阿里系 `amdc` 安全边界

1. **API 网关覆盖**：覆盖真机确认的 `m5.amap.com`、`m5-zb.amap.com`、`m5-x.amap.com` 及新版网关 `m6.amap.com`。
2. **`amdc.m.taobao.com` 精准防绕过**：高德客户端会通过明文 HTTP 请求 `amdc.m.taobao.com` 获取 HTTPDNS 直连 IP 绕过 `m5/m6.amap.com` 的域名规则与 MITM。社区部分激进方案直接全局 `DOMAIN,amdc.m.taobao.com,REJECT` 或将其加入 `[MITM]`，会导致淘宝、闲鱼出现商品加载缓慢、加购异常或滑块验证循环。
   - 本仓库采用复合规则 `AND,((DOMAIN,amdc.m.taobao.com),(USER-AGENT,AMap*)),{{{高德HTTPDNS策略}}}`（默认 `REJECT`），且**绝不将 `amdc.m.taobao.com` 加入 `[MITM]`**：淘宝/闲鱼的 HTTPS 请求不解密、不含明文 `User-Agent` 故 100% 正常放行，而高德发起的明文 HTTP 调度请求被精准拦截回退系统 DNS。
3. **可选精简开关**：提供 `精简周边与出行推广`（默认 `false`），按需清理 `/ws/shield/frogserver/afootprint` 足迹打卡横幅与首页 `nearby` / `activity` 营销卡，始终保护 `FrequentLocation`、`CommuteCard`、`TravelCard`、`MyOrderCard` 等核心出行卡片。
