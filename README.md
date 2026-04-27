# Surge Modules

自用 Surge 模块仓库。所有模块尽量保持可审计、少权限、无远程脚本依赖。

## 番茄小说去广告

文件：[modules/fanqie-novel-adblock.sgmodule](modules/fanqie-novel-adblock.sgmodule)

安装地址：

```text
https://raw.githubusercontent.com/mulanshan/surge/main/modules/fanqie-novel-adblock.sgmodule
```

功能范围：

- 拦截番茄小说和字节系广告、统计、监控、热更新资源域名
- 不包含 JavaScript 脚本
- 不启用 MITM
- 不修改响应体

说明：

这个模块采用保守的域名拦截方式，只使用 Surge 内置 `REJECT` 策略。因为没有脚本和 MITM，安全风险比需要解密流量或执行远程 JS 的模块低很多；代价是只能处理域名层面的广告和统计请求，无法精细清理 App 内部接口返回字段。

如果番茄小说后续新增广告域名，可以把域名追加到模块的 `[Rule]` 区域，然后重新推送仓库。Surge 里更新模块即可生效。
