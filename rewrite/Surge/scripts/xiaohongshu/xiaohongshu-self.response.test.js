const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const scriptPath = path.join(__dirname, "xiaohongshu-self.response.js");
const modulePath = path.join(__dirname, "..", "..", "candidates", "xiaohongshu-self.sgmodule");

assert.ok(fs.existsSync(scriptPath), "missing Xiaohongshu response script");
assert.ok(fs.existsSync(modulePath), "missing Xiaohongshu candidate module");

const script = fs.readFileSync(scriptPath, "utf8");
const moduleText = fs.readFileSync(modulePath, "utf8");

function execute(url, payload, options = {}) {
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
    $request: { url },
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

  vm.runInNewContext(script, context, { filename: "xiaohongshu-self.response.js" });
  assert.equal(doneCalls, 1, "script must call $done exactly once");
  return {
    result: output && typeof output === "object" ? JSON.parse(JSON.stringify(output)) : output,
    consoleLogs,
    logbookLogs,
  };
}

function run(url, payload, options = {}) {
  return execute(url, payload, options).result;
}

function bodyOf(result) {
  return result && result.body ? JSON.parse(result.body) : null;
}

{
  const result = bodyOf(run(
    "https://edith.xiaohongshu.com/api/sns/v6/homefeed?cursor=redacted",
    {
      data: [
        { id: "synthetic-ad-1", ads_info: { trace_id: "secret-ad-trace" } },
        { id: "synthetic-ad-2", is_ad: 1 },
        {
          id: "normal-note",
          model_type: "note",
          card_icon: "shopping",
          note_attributes: ["goods"],
          user: { user_id: "kept-user", vip: true },
          price: "19.90",
        },
        { id: "organic-promotion", promotion: { type: "organic" } },
      ],
      cursor: "kept-cursor",
    },
  ));
  assert.deepEqual(result.data.map((item) => item.id), ["normal-note", "organic-promotion"]);
  assert.equal(result.data[0].user.vip, true);
  assert.equal(result.data[0].price, "19.90");
  assert.equal(result.cursor, "kept-cursor");
}

{
  const result = bodyOf(run(
    "https://edith.xiaohongshu.com/api/sns/v6/homefeed?cursor=redacted",
    {
      data: [
        { id: "synthetic-ad", is_ad: 1 },
        {
          id: "kept-note-with-business-state",
          account: {
            items: [{ id: "paid-benefit", is_ad: 1 }],
          },
          membership: {
            cards: [{ id: "membership-card", is_ad: 1 }],
          },
        },
      ],
    },
  ));
  assert.equal(result.data.length, 1);
  assert.deepEqual(result.data[0].account.items, [{ id: "paid-benefit", is_ad: 1 }]);
  assert.deepEqual(result.data[0].membership.cards, [{ id: "membership-card", is_ad: 1 }]);
}

{
  const result = run(
    "https://edith.xiaohongshu.com/api/sns/v6/homefeed?cursor=redacted",
    { data: [{ id: "empty-ad-marker", ads_info: {} }] },
  );
  assert.deepEqual(result, {});
}

{
  const result = run(
    "https://edith.xiaohongshu.com/api/sns/v1/system_service/config",
    {
      data: {
        splash: { image: "kept-splash" },
        loading_img: { image: "kept-loading" },
      },
    },
  );
  assert.deepEqual(result, {});
}

{
  const result = bodyOf(run(
    "https://so.xiaohongshu.com/api/sns/v10/search/notes?keyword=redacted",
    {
      data: {
        items: [
          { model_type: "note", note: { id: "kept-note" } },
          { model_type: "note", ads_info: { id: "synthetic-ad" } },
          { model_type: "user", user: { id: "kept-user-result" } },
        ],
      },
    },
  ));
  assert.equal(result.data.items.length, 2);
  assert.equal(result.data.items[0].note.id, "kept-note");
  assert.equal(result.data.items[1].user.id, "kept-user-result");
}

for (const bodyType of ["uint8array", "arraybuffer"]) {
  const result = bodyOf(run(
    "https://edith.xiaohongshu.com/api/sns/v2/note/feed?note_id=redacted",
    {
      data: [
        {
          note_list: [
            {
              id: "kept-note",
              media_save_config: {
                disable_save: true,
                disable_watermark: false,
                disable_weibo_cover: false,
                keep: "unchanged",
              },
              function_switch: [
                { type: "image_download", enable: false, reason: "server-disabled" },
                { type: "share", enable: false },
              ],
              account: { vip: false },
            },
            { id: "synthetic-ad", is_ad: 1 },
          ],
        },
      ],
    },
    { bodyType },
  ));
  assert.equal(result.data[0].note_list.length, 1);
  const note = result.data[0].note_list[0];
  assert.equal(note.media_save_config.disable_save, true);
  assert.equal(note.media_save_config.disable_watermark, false);
  assert.equal(note.media_save_config.disable_weibo_cover, false);
  assert.equal(note.media_save_config.keep, "unchanged");
  assert.equal(note.function_switch[0].enable, false);
  assert.equal(note.function_switch[0].reason, "server-disabled");
  assert.equal(note.function_switch[1].enable, false);
  assert.equal(note.account.vip, false);
}

assert.deepEqual(run(
    "https://edith.xiaohongshu.com/api/sns/v4/search/trending?source=redacted",
    {
      data: {
        queries: [{ id: "synthetic-hot-query" }],
        hint_word: { text: "synthetic-hint" },
        navigation: [{ id: "must-stay" }],
      },
    },
  ), {});

{
  const result = bodyOf(run(
    "https://edith.xiaohongshu.com/api/sns/v2/system_service/splash_config",
    {
      data: {
        ads_groups: [
          { id: "synthetic-splash", is_ad: 1 },
          { id: "kept-launch-config", style: "normal" },
        ],
        account: { user_id: "kept-user" },
        feature_flags: { notes: true },
      },
    },
  ));
  assert.deepEqual(result.data.ads_groups.map((item) => item.id), ["kept-launch-config"]);
  assert.equal(result.data.account.user_id, "kept-user");
  assert.equal(result.data.feature_flags.notes, true);
}

assert.deepEqual(run(
  "https://edith.xiaohongshu.com/api/sns/v6/homefeed?cursor=redacted",
  { data: [{ id: "ad", ads_info: { trace_id: "synthetic" } }] },
  { argument: { cleanAds: false } },
), {});
assert.deepEqual(run(
  "https://edith.xiaohongshu.com/api/sns/v2/note/feed?note_id=redacted",
  { data: [{ note_list: [{ media_save_config: { disable_save: true } }] }] },
), {});

assert.deepEqual(run(
  "https://edith.xiaohongshu.com/api/sns/v1/user/profile?user_id=secret",
  { data: [{ id: "ad", ads_info: {} }] },
), {});
assert.deepEqual(run(
  "https://edith.xiaohongshu.com/api/sns/v6/homefeed?cursor=redacted",
  "not-json",
), {});
assert.deepEqual(run(
  "https://edith.xiaohongshu.com/api/sns/v6/homefeed?cursor=redacted",
  [{ id: "array-root", ads_info: {} }],
), {});
assert.deepEqual(run(
  "https://edith.xiaohongshu.com/api/sns/v6/homefeed?cursor=redacted",
  { data: [{ id: "ad", ads_info: { trace_id: "synthetic" } }] },
  { status: 500 },
), {});

{
  const diagnostics = execute(
    "https://edith.xiaohongshu.com/api/sns/v6/homefeed?cursor=sensitive-cursor",
    { data: [{ id: "sensitive-note-id", ads_info: { trace_id: "sensitive-trace" } }] },
    { argument: { debug: true } },
  );
  const logs = diagnostics.consoleLogs.concat(diagnostics.logbookLogs).join("\n");
  assert.match(logs, /removed_ads=1/);
  assert.doesNotMatch(logs, /sensitive-note-id|sensitive-trace|sensitive-cursor/);
}

assert.match(moduleText, /^#!name=小红书 \(候选\)$/m);
assert.match(moduleText, /#!requirement=CORE_VERSION>=20 && SYSTEM = 'iOS'/);
assert.match(moduleText, /#!arguments=.*清理明确广告:true.*启用调试模式:false/);
assert.doesNotMatch(moduleText, /恢复无水印保存:true|清理搜索提示:true/);
assert.match(moduleText, /max-size=6291456/);
assert.ok(moduleText.includes(
  "script-path=https://raw.githubusercontent.com/mulanshan/surge/surge-self-v2026.08.15/rewrite/Surge/scripts/xiaohongshu/xiaohongshu-self.response.js",
));
assert.equal(moduleText.includes("script-path=https://raw.githubusercontent.com/mulanshan/surge/main/"), false);
assert.doesNotMatch(moduleText, /DOMAIN-SUFFIX,xiaohongshu\.com/);

for (const forbiddenRuntimeApi of [
  /\$httpClient\b/,
  /\$task\s*\.\s*fetch\b/,
  /\$persistentStore\b/,
  /\$prefs\b/,
  /\bfetch\s*\(/,
  /\bXMLHttpRequest\b/,
  /\beval\s*\(/,
  /\bFunction\s*\(/,
]) {
  assert.doesNotMatch(script, forbiddenRuntimeApi);
}

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
assert.match(scriptEntries[0], /^xiaohongshu\.self\.response = type=http-response,/);
assert.match(scriptEntries[0], /debug=\{\{\{启用调试模式\}\}\}/);
assert.deepEqual(sectionEntries("MITM"), [
  "hostname = %APPEND% edith.xiaohongshu.com, rec.xiaohongshu.com, so.xiaohongshu.com, www.xiaohongshu.com",
]);
assert.deepEqual(sectionEntries("Map Local"), [
  '^https:\\/\\/www\\.xiaohongshu\\.com\\/api\\/sns\\/v\\d+\\/ads\\/resource(?:\\?.*)?$ data-type=text data="{}" status-code=200 header="Content-Type:application/json"',
]);

console.log("Xiaohongshu Self tests passed");
