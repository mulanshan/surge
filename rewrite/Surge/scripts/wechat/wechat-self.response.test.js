const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "wechat-self.response.js"), "utf8");
const moduleText = fs.readFileSync(path.join(__dirname, "..", "..", "wechat-self.sgmodule"), "utf8");

function execute(payload, options = {}) {
  let output;
  let doneCalls = 0;
  const consoleLogs = [];
  const logbookLogs = [];
  const textBody = typeof payload === "string" ? payload : JSON.stringify(payload);
  let responseBody = textBody;
  if (options.bodyType === "uint8array") responseBody = new TextEncoder().encode(textBody);
  if (options.bodyType === "arraybuffer") responseBody = new TextEncoder().encode(textBody).buffer;
  const context = {
    ArrayBuffer,
    TextDecoder,
    TextEncoder,
    Uint8Array,
    console: { log(message) { consoleLogs.push(String(message)); } },
    $argument: Object.prototype.hasOwnProperty.call(options, "rawArgument")
      ? options.rawArgument
      : JSON.stringify(options.argument || {}),
    $request: {
      url: options.url || "https://mp.weixin.qq.com/mp/getappmsgad?__biz=redacted",
    },
    $response: { body: responseBody, status: options.status ?? 200 },
    $surge: {
      logbook(message) {
        logbookLogs.push(String(message));
      },
    },
    $done(value) {
      doneCalls += 1;
      output = value;
    },
  };
  vm.runInNewContext(script, context, { filename: "wechat-self.response.js" });
  assert.equal(doneCalls, 1, "script must call $done exactly once");
  return {
    result: output && typeof output === "object" ? JSON.parse(JSON.stringify(output)) : output,
    consoleLogs,
    logbookLogs,
    doneCalls,
  };
}

function run(payload, options = {}) {
  return execute(payload, options).result;
}

function bodyOf(result) {
  return result && result.body ? JSON.parse(result.body) : null;
}

// 1. Official Account getappmsgad cleaning
{
  const result = bodyOf(run({
    advertisement_num: 2,
    advertisement_info: [
      { id: "synthetic-ad-1", trace_id: "redacted" },
      { id: "synthetic-ad-2", trace_id: "redacted" },
    ],
    appid: "kept-app-id",
    base_resp: { ret: 0 },
    article_context: { comment_enabled: true, reward_enabled: true },
  }));
  assert.equal(result.advertisement_num, 0);
  assert.deepEqual(result.advertisement_info, []);
  assert.equal(result.appid, "kept-app-id");
  assert.deepEqual(result.base_resp, { ret: 0 });
  assert.deepEqual(result.article_context, { comment_enabled: true, reward_enabled: true });
}

{
  const result = bodyOf(run({
    advertisement_num: "1",
    advertisement_info: [],
    other: "kept",
  }));
  assert.equal(result.advertisement_num, "0");
  assert.equal(result.other, "kept");
}

for (const bodyType of ["uint8array", "arraybuffer"]) {
  const result = bodyOf(run({ advertisement_num: 1, advertisement_info: [{ id: "ad" }] }, { bodyType }));
  assert.equal(result.advertisement_num, 0);
  assert.deepEqual(result.advertisement_info, []);
}

{
  const result = bodyOf(run("\ufeff{\"advertisement_num\":1,\"advertisement_info\":[]}"));
  assert.equal(result.advertisement_num, 0);
}

{
  const result = bodyOf(run({
    advertisement_num: 0,
    advertisement_info: [{ id: "synthetic-ad" }],
  }));
  assert.equal(result.advertisement_num, 0);
  assert.deepEqual(result.advertisement_info, []);
}

// 2. Official Account getappmsgext cleaning while strictly preserving stats/albums/rewards
{
  const result = bodyOf(run({
    base_resp: { ret: 0, errmsg: "ok" },
    appmsgstat: {
      read_num: 10240,
      like_num: 356,
      old_like_num: 289,
      watching_num: 42,
    },
    appmsg_album_info: { id: "album-1", title: "Series" },
    reward_head_imgs: ["https://wx.qlogo.cn/avatar1"],
    advertisement_num: 2,
    advertisement_info: [{ ad_id: "ad-1" }, { ad_id: "ad-2" }],
    promotion_info: [{ promo_id: "p-1" }],
    drama_advertisement_info: [{ drama_id: "d-1" }],
  }, {
    url: "https://mp.weixin.qq.com/mp/getappmsgext?__biz=redacted",
  }));
  assert.equal(result.advertisement_num, 0);
  assert.deepEqual(result.advertisement_info, []);
  assert.deepEqual(result.promotion_info, []);
  assert.deepEqual(result.drama_advertisement_info, []);
  assert.deepEqual(result.appmsgstat, {
    read_num: 10240,
    like_num: 356,
    old_like_num: 289,
    watching_num: 42,
  });
  assert.deepEqual(result.appmsg_album_info, { id: "album-1", title: "Series" });
  assert.deepEqual(result.reward_head_imgs, ["https://wx.qlogo.cn/avatar1"]);
}

// getappmsgext without ad fields passes through untouched
assert.deepEqual(run({
  base_resp: { ret: 0 },
  appmsgstat: { read_num: 512, like_num: 18 },
}, {
  url: "https://mp.weixin.qq.com/mp/getappmsgext?__biz=redacted",
}), {});

// getappmsgext backend error envelope (ret != 0) is never rewritten
assert.deepEqual(run({
  base_resp: { ret: 1200001, err_msg: "invalid key" },
  advertisement_num: 1,
  advertisement_info: [{ id: "ad" }],
}, {
  url: "https://mp.weixin.qq.com/mp/getappmsgext?__biz=redacted",
}), {});

// 3. CPS affiliate product card (cps_product_info) cleaning & cleanAds switch
{
  const result = bodyOf(run({
    base_resp: { ret: 0 },
    product_list: [{ product_id: "p1", price: 9900 }],
    cps_info: { pid: "cps-1" },
    total_count: 1,
  }, {
    url: "https://mp.weixin.qq.com/mp/cps_product_info?action=get",
  }));
  assert.deepEqual(result, {
    base_resp: { ret: 0 },
    product_list: [],
    total_count: 0,
  });
}

{
  const result = bodyOf(run({
    product: { product_id: "p2" },
  }, {
    url: "https://mp.weixin.qq.com/mp/cps_product_info",
  }));
  assert.deepEqual(result, {
    base_resp: { ret: 0 },
  });
}

assert.deepEqual(run({
  base_resp: { ret: 0 },
  product_list: [],
  total_count: 0,
}, {
  url: "https://mp.weixin.qq.com/mp/cps_product_info",
}), {});

// cleanAds: false bypasses getappmsgad, getappmsgext, and cps_product_info immediately
for (const url of [
  "https://mp.weixin.qq.com/mp/getappmsgad?__biz=redacted",
  "https://mp.weixin.qq.com/mp/getappmsgext?__biz=redacted",
  "https://mp.weixin.qq.com/mp/cps_product_info?action=get",
]) {
  assert.deepEqual(run("not-even-parsed-when-disabled", {
    url,
    argument: { cleanAds: false },
  }), {});
}

// 4. Optional bottom waterfall / related feed (masonryfeed & relatedarticle)
assert.deepEqual(run({
  base_resp: { ret: 0 },
  list: [{ title: "Recommended article" }],
  continue_flag: 1,
}, {
  url: "https://mp.weixin.qq.com/mp/masonryfeed?action=get",
}), {});

assert.deepEqual(run({
  base_resp: { ret: 0 },
  related_article_list: [{ title: "Related article" }],
}, {
  url: "https://mp.weixin.qq.com/mp/relatedarticle?action=get",
}), {});

{
  const result = bodyOf(run({
    base_resp: { ret: 0 },
    list: [{ title: "Waterfall item 1" }, { title: "Waterfall item 2" }],
    continue_flag: 1,
    has_more: true,
    total_count: "2",
  }, {
    url: "https://mp.weixin.qq.com/mp/masonryfeed?action=get",
    argument: { hideBottomFeed: true },
  }));
  assert.deepEqual(result, {
    base_resp: { ret: 0 },
    list: [],
    continue_flag: 0,
    has_more: false,
    total_count: "0",
  });
}

{
  const result = bodyOf(run({
    base_resp: { ret: 0 },
    related_article_list: [{ title: "Related item 1" }],
    is_continue: "1",
  }, {
    url: "https://mp.weixin.qq.com/mp/relatedarticle?action=get",
    argument: { hideBottomFeed: true },
  }));
  assert.deepEqual(result, {
    base_resp: { ret: 0 },
    related_article_list: [],
    is_continue: "0",
  });
}

// 5. Defensive schema & boundary pass-through invariants
assert.deepEqual(run({ advertisement_num: 0, advertisement_info: [] }), {});
assert.deepEqual(run({ article_context: { title: "normal article" } }), {});
assert.deepEqual(run({ advertisement_num: "unknown", advertisement_info: { item: "unknown schema" } }), {});
assert.deepEqual(run({ advertisement_num: 1, advertisement_info: { future: true } }), {});
assert.deepEqual(run({ advertisement_num: "future", advertisement_info: [{ id: "must-stay" }] }), {});
assert.deepEqual(run({ advertisement_num: null, advertisement_info: [{ id: "must-stay" }] }), {});
assert.deepEqual(run({ advertisement_num: -1, advertisement_info: [] }), {});
assert.deepEqual(run({ advertisement_num: 1.5, advertisement_info: [] }), {});
assert.deepEqual(run({ advertisement_num: Number.MAX_SAFE_INTEGER + 1, advertisement_info: [] }), {});
assert.deepEqual(run({ advertisement_num: "9007199254740992", advertisement_info: [] }), {});
assert.deepEqual(run({ advertisement_num: [], advertisement_info: [] }), {});
assert.deepEqual(run([{
  advertisement_num: 1,
  advertisement_info: [{ id: "nested-array-root" }],
}]), {});
assert.deepEqual(run("not-json"), {});
assert.deepEqual(run({ advertisement_num: 1, advertisement_info: [{ id: "ad" }] }, { status: 500 }), {});
assert.deepEqual(run({ advertisement_num: 1, advertisement_info: [{ id: "ad" }] }, {
  url: "https://mp.weixin.qq.com/mp/appmsg_comment?action=getcomment",
}), {});
assert.deepEqual(run({ advertisement_num: 1, advertisement_info: [{ id: "ad" }] }, {
  url: "https://mp.weixin.qq.com/mp/getappmsgad#fragment",
}), {});

{
  const diagnostics = execute({ advertisement_num: 1, advertisement_info: [{ id: "ad" }] }, {
    argument: { debug: true },
  });
  assert.match(diagnostics.consoleLogs.join("\n"), /cleaned getappmsgad; reset_count=1; removed_items=1/);
  assert.match(diagnostics.logbookLogs.join("\n"), /cleaned getappmsgad; reset_count=1; removed_items=1/);
  assert.doesNotMatch(diagnostics.consoleLogs.join("\n"), /synthetic-ad|advertisement_num|advertisement_info|redacted/);
}

{
  const diagnostics = execute({ article_context: { title: "normal article" } }, {
    argument: { debug: true },
  });
  assert.match(diagnostics.consoleLogs.join("\n"), /pass-through: unrecognized schema/);
}

{
  const diagnostics = execute("not-json", { argument: { debug: true } });
  assert.match(diagnostics.consoleLogs.join("\n"), /pass-through: invalid JSON/);
}

{
  const diagnostics = execute({ advertisement_num: 1, advertisement_info: { future: true } }, {
    argument: { debug: true },
  });
  assert.match(diagnostics.consoleLogs.join("\n"), /pass-through: invalid advertisement schema/);
}

{
  const diagnostics = execute({ advertisement_num: 1, advertisement_info: [{ id: "ad" }] }, {
    rawArgument: "{invalid",
  });
  assert.deepEqual(diagnostics.consoleLogs, []);
  assert.equal(bodyOf(diagnostics.result).advertisement_num, 0);
}

{
  const diagnostics = execute({ advertisement_num: 1, advertisement_info: [{ id: "ad" }] }, {
    argument: { debug: "true" },
  });
  assert.deepEqual(diagnostics.consoleLogs, []);
}

// 6. Module safety invariants
assert.doesNotMatch(moduleText, /DOMAIN-SUFFIX,wxs\.qq\.com/);
assert.doesNotMatch(moduleText, /DOMAIN(?:-SUFFIX)?,gdtimg\.com/);
assert.doesNotMatch(moduleText, /DOMAIN(?:-SUFFIX)?,ugdtimg\.com/);
assert.doesNotMatch(moduleText, /DOMAIN(?:-SUFFIX)?,wxsnsdy\.wxs\.qq\.com/);
assert.doesNotMatch(moduleText, /DOMAIN(?:-SUFFIX)?,dns\.weixin\.qq\.com/);
assert.match(moduleText, /wxa\.wxs\.qq\.com/);
assert.match(moduleText, /wximg\.wxs\.qq\.com/);
assert.match(moduleText, /wxsmw\.wxs\.qq\.com/);
assert.match(moduleText, /getappmsgad/);
assert.match(moduleText, /cps_product_info/);
assert.match(moduleText, /debug=\{\{\{启用调试模式\}\}\}/);
assert.match(moduleText, /hostname = %APPEND% mp\.weixin\.qq\.com/);

function sectionEntries(sectionName) {
  const lines = moduleText.split(/\r?\n/);
  const start = lines.indexOf(`[${sectionName}]`);
  assert.notEqual(start, -1, `missing [${sectionName}] section`);
  const entries = [];
  for (let index = start + 1; index < lines.length; index += 1) {
    const line = lines[index].trim();
    if (/^\[.+\]$/.test(line)) break;
    if (line && !line.startsWith("#")) entries.push(line);
  }
  return entries;
}

const scriptEntries = sectionEntries("Script");
assert.equal(scriptEntries.length, 1);
assert.match(scriptEntries[0], /^wechat\.self\.response = type=http-response,/);
assert.match(scriptEntries[0], /pattern=\^https:\\\/\\\/mp\\\.weixin\\\.qq\\\.com/);
assert.match(scriptEntries[0], /requires-body=1/);
assert.match(scriptEntries[0], /script-path=https:\/\/raw\.githubusercontent\.com\/mulanshan\/surge\/surge-self-v\d{4}\.\d{2}\.\d{2}(?:\.\d+)?\//);

assert.deepEqual(sectionEntries("MITM"), [
  "hostname = %APPEND% mp.weixin.qq.com",
]);

console.log("WeChat Self tests passed");
