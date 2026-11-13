# 扫描全能王专用模块：社区调研与安全边界

更新日期：2026-11-13。

## 设计定位

本仓库将跨应用通用广告网络（Google / AdMob、优量汇 GDT 等）统一收归 `rewrite/Surge/basic-adblock.sgmodule`，`rewrite/Surge/camscanner-self.sgmodule` 只负责合合信息（INTSIG / CamScanner）第一方的开屏、广告配置、页面运营位、新功能强推弹窗与遥测采集域名。

- 模块：`rewrite/Surge/camscanner-self.sgmodule`
- 脚本：`rewrite/Surge/scripts/camscanner/camscanner-self.response.js`
- 测试：`rewrite/Surge/scripts/camscanner/camscanner-self.response.test.js`

## 社区方案对照与严格排除边界

1. 社区公开方案中存在大量针对 `purchase/cs/query_property` 的“伪造黄金会员”重写脚本：不仅违背软件授权合规要求，而且服务端 OCR、云空间与 PDF 导出均在后端二次校验收据，伪造本地属性会导致云同步异常甚至账号风控。**本模块严格排除所有购买、会员、额度、收据与订阅接口**。
2. 2026-11-13 真机流量审计确认 `intsig.net` 承载主客户端开屏与配置请求：模块除 `open.camscanner.com` 外，仅对 `api.intsig.net` 与 `api-cs.intsig.net` 的明确只读开屏与页面配置路径（`/user/cs/operating/app/get_startpic`、`/sync/get_ad_(data|control|cfg)`、`/sync/get_page_cfg(_v2)`、`/sync/get_new_func_popup_cfg`）执行 JSON 广告容器清理。
3. 移除历史 `[Map Local]` 与 `[Script]` 在 `get_ad_(data|control|cfg)` 上的重复挂载，统一交由响应脚本在 `清理明确广告` 开关下保留响应外壳并清空广告槽；`upload_ad_record` 继续由 `[Map Local]` 返回带 `Content-Type:application/json` 的空对象。
4. 字段匹配收紧为精确广告令牌（如 `floatad`、`startpic`、`funcpopup`），明确保护 `float_btn`、`camera`、`scan`、`ocr`、`pdf`、`cloud`、`sync`、`user` 等核心业务字段。
