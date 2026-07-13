const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "wechat-self.response.js"), "utf8");
const moduleText = fs.readFileSync(path.join(__dirname, "..", "..", "wechat-self.sgmodule"), "utf8");

function run(payload, options = {}) {
  let output;
  const responseBody = typeof payload === "string" ? payload : JSON.stringify(payload);
  const context = {
    ArrayBuffer,
    TextDecoder,
    Uint8Array,
    console: { log() {} },
    $argument: JSON.stringify(options.argument || {}),
    $request: {
      url: options.url || "https://mp.weixin.qq.com/mp/getappmsgad?__biz=redacted",
    },
    $response: { body: responseBody },
    $done(value) {
      output = value;
    },
  };
  vm.runInNewContext(script, context, { filename: "wechat-self.response.js" });
  return output && typeof output === "object" ? JSON.parse(JSON.stringify(output)) : output;
}

function bodyOf(result) {
  return result && result.body ? JSON.parse(result.body) : null;
}

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
  assert.equal(result.advertisement_num, 0);
  assert.equal(result.other, "kept");
}

assert.deepEqual(run({ advertisement_num: 0, advertisement_info: [] }), {});
assert.deepEqual(run({ article_context: { title: "normal article" } }), {});
assert.deepEqual(run({ advertisement_num: "unknown", advertisement_info: { item: "unknown schema" } }), {});
assert.deepEqual(run("not-json"), {});
assert.deepEqual(run({ advertisement_num: 1, advertisement_info: [{ id: "ad" }] }, {
  url: "https://mp.weixin.qq.com/mp/getappmsgext?__biz=redacted",
}), {});

assert.match(moduleText, /DOMAIN,wxa\.wxs\.qq\.com,REJECT/);
assert.match(moduleText, /DOMAIN,wximg\.wxs\.qq\.com,REJECT/);
assert.match(moduleText, /DOMAIN,wxsmw\.wxs\.qq\.com,REJECT/);
assert.doesNotMatch(moduleText, /DOMAIN-SUFFIX,wxs\.qq\.com/);
assert.match(moduleText, /\/mp\\\/getappmsgad/);
assert.match(moduleText, /\/mp\\\/cps_product_info/);
assert.match(moduleText, /max-size=524288/);
assert.match(moduleText, /hostname = %APPEND% mp\.weixin\.qq\.com/);

console.log("WeChat Self tests passed");
