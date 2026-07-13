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
  url: "https://mp.weixin.qq.com/mp/getappmsgext?__biz=redacted",
}), {});
assert.deepEqual(run({ advertisement_num: 1, advertisement_info: [{ id: "ad" }] }, {
  url: "https://mp.weixin.qq.com/mp/getappmsgad#fragment",
}), {});

{
  const diagnostics = execute({ advertisement_num: 1, advertisement_info: [{ id: "ad" }] }, {
    argument: { debug: true },
  });
  assert.match(diagnostics.consoleLogs.join("\n"), /reset_count=1; removed_items=1/);
  assert.match(diagnostics.logbookLogs.join("\n"), /reset_count=1; removed_items=1/);
  assert.doesNotMatch(diagnostics.consoleLogs.join("\n"), /synthetic-ad|advertisement_num|advertisement_info/);
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

assert.match(moduleText, /DOMAIN,wxa\.wxs\.qq\.com,REJECT/);
assert.match(moduleText, /DOMAIN,wximg\.wxs\.qq\.com,REJECT/);
assert.match(moduleText, /DOMAIN,wxsmw\.wxs\.qq\.com,REJECT/);
assert.doesNotMatch(moduleText, /DOMAIN-SUFFIX,wxs\.qq\.com/);
assert.match(moduleText, /\/mp\\\/getappmsgad/);
assert.match(moduleText, /\/mp\\\/cps_product_info/);
assert.match(moduleText, /max-size=524288/);
assert.match(moduleText, /debug=\{\{\{启用调试模式\}\}\}/);
assert.match(moduleText, /header="Content-Type:application\/json"/);
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

assert.deepEqual(sectionEntries("Rule"), [
  "DOMAIN,wxa.wxs.qq.com,REJECT",
  "DOMAIN,wximg.wxs.qq.com,REJECT",
  "DOMAIN,wxsmw.wxs.qq.com,REJECT",
]);

const scriptEntries = sectionEntries("Script");
assert.equal(scriptEntries.length, 1);
assert.match(scriptEntries[0], /^wechat\.self\.response = type=http-response,/);
assert.match(scriptEntries[0], /pattern=\^https:\\\/\\\/mp\\\.weixin\\\.qq\\\.com/);
assert.match(scriptEntries[0], /requires-body=1/);
assert.match(scriptEntries[0], /max-size=524288/);
assert.match(scriptEntries[0], /script-path=https:\/\/raw\.githubusercontent\.com\/mulanshan\/surge\/surge-self-v\d{4}\.\d{2}\.\d{2}(?:\.\d+)?\//);

assert.deepEqual(sectionEntries("Map Local"), [
  '^https:\\/\\/mp\\.weixin\\.qq\\.com\\/mp\\/cps_product_info(?:\\?.*)?$ data-type=text data="{}" status-code=200 header="Content-Type:application/json"',
]);

assert.deepEqual(sectionEntries("MITM"), [
  "hostname = %APPEND% mp.weixin.qq.com",
]);

console.log("WeChat Self tests passed");
