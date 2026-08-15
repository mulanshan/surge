const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const scriptPath = path.join(__dirname, "weibo-self.response.js");
const modulePath = path.join(__dirname, "..", "..", "candidates", "weibo-self.sgmodule");

assert.ok(fs.existsSync(scriptPath), "missing Weibo response script");
assert.ok(fs.existsSync(modulePath), "missing Weibo candidate module");

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

  vm.runInNewContext(script, context, { filename: "weibo-self.response.js" });
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

for (const bodyType of [undefined, "uint8array", "arraybuffer"]) {
  const result = bodyOf(run(
    "https://api.weibo.cn/2/statuses/container_timeline?containerid=redacted",
    {
      items: [
        { category: "feed", data: { id: "kept-post", mblogtypename: "普通", user: { id: "kept-user", vip: true } } },
        { category: "feed", data: { id: "synthetic-ad-1", mblogtypename: "广告" } },
        { category: "feed", data: { id: "synthetic-ad-2", promotion: { type: "ad" } } },
        { category: "card", data: { id: "kept-hot-topic", title: "热议话题" } },
      ],
      account: { uid: "kept-account", vip: false },
    },
    { bodyType },
  ));
  assert.deepEqual(result.items.map((item) => item.data.id), ["kept-post", "kept-hot-topic"]);
  assert.equal(result.items[0].data.user.vip, true);
  assert.equal(result.account.uid, "kept-account");
}

{
  const result = bodyOf(run(
    "https://api.weibo.cn/2/statuses/container_timeline?containerid=redacted",
    {
      items: [
        { category: "feed", data: { id: "synthetic-ad", is_ad: 1 } },
        {
          category: "feed",
          data: {
            id: "kept-post-with-business-state",
            account: {
              items: [{ id: "paid-benefit", is_ad: 1 }],
            },
            membership: {
              cards: [{ id: "membership-card", is_ad: 1 }],
            },
          },
        },
      ],
    },
  ));
  assert.equal(result.items.length, 1);
  assert.deepEqual(result.items[0].data.account.items, [{ id: "paid-benefit", is_ad: 1 }]);
  assert.deepEqual(result.items[0].data.membership.cards, [{ id: "membership-card", is_ad: 1 }]);
}

{
  const result = bodyOf(run(
    "https://mapi.weibo.com/2/statuses/unread_hot_timeline?since_id=redacted",
    {
      statuses: [
        { id: "kept-status", text: "normal", user: { id: "kept-user" } },
        { id: "synthetic-ad", content_auth_info: { content_auth_title: "广告" } },
      ],
      ad: [{ id: "root-ad" }],
      advertises: [{ id: "root-ad-2" }],
      cursor: "kept-cursor",
    },
  ));
  assert.deepEqual(result.statuses.map((item) => item.id), ["kept-status"]);
  assert.deepEqual(result.ad, []);
  assert.deepEqual(result.advertises, []);
  assert.equal(result.cursor, "kept-cursor");
}

{
  const result = bodyOf(run(
    "https://api.weibo.cn/2/search/container_timeline?q=redacted",
    {
      data: {
        cards: [
          { card_type: 42, is_ad: 1, id: "synthetic-card-ad" },
          { card_type: 42, title_extra_text: "话题", id: "kept-card" },
          { mblog: { id: "synthetic-mblog-ad", ads_material_info: { is_ads: true } } },
          { mblog: { id: "kept-mblog", user: { id: "kept-user" } } },
        ],
      },
    },
  ));
  assert.deepEqual(result.data.cards.map((item) => item.id || item.mblog.id), ["kept-card", "kept-mblog"]);
}

{
  const result = bodyOf(run(
    "https://api.weibo.cn/2/comments/build_comments?id=redacted",
    {
      root_comments: [
        { id: "kept-comment", text: "normal", user: { id: "kept-user" } },
        { id: "synthetic-comment-ad", ads_material_info: { is_ads: true } },
      ],
      comment_config: { can_reply: true },
    },
  ));
  assert.deepEqual(result.root_comments.map((item) => item.id), ["kept-comment"]);
  assert.equal(result.root_comments[0].user.id, "kept-user");
  assert.equal(result.comment_config.can_reply, true);
}

{
  const result = run(
    "https://api.weibo.cn/2/profile/me?uid=redacted",
    {
      items: [
        { category: "feed", data: { id: "synthetic-ad", is_ad: 1 } },
        { category: "service", data: { id: "wallet", balance: "88.00", vip: true } },
      ],
      user: { id: "kept-user", membership: { level: 3 } },
    },
  );
  assert.deepEqual(result, {});
}

{
  const result = bodyOf(run(
    "https://api.weibo.cn/2/statuses/container_timeline?containerid=redacted",
    {
      items: [
        {
          category: "service",
          data: {
            id: "ad-free-membership",
            title_extra_text: "会员免广告权益",
            wallet: { balance: "88.00" },
            benefits: [{ id: "nested-business-state", is_ad: 1 }],
          },
        },
        { category: "feed", data: { id: "synthetic-ad", is_ad: 1 } },
      ],
    },
  ));
  assert.equal(result.items.length, 1);
  assert.equal(result.items[0].data.id, "ad-free-membership");
  assert.equal(result.items[0].data.wallet.balance, "88.00");
  assert.equal(result.items[0].data.benefits[0].id, "nested-business-state");
}

assert.deepEqual(run(
  "https://api.weibo.cn/2/statuses/container_timeline?containerid=redacted",
  { items: [{ data: { id: "ad", is_ad: 1 } }] },
  { argument: { cleanAds: false } },
), {});
assert.deepEqual(run(
  "https://api.weibo.cn/2/account/get_uid?token=secret",
  { items: [{ data: { id: "ad", is_ad: 1 } }] },
), {});
assert.deepEqual(run(
  "https://api.weibo.cn/2/statuses/container_timeline?containerid=redacted",
  "not-json",
), {});
assert.deepEqual(run(
  "https://api.weibo.cn/2/statuses/container_timeline?containerid=redacted",
  [{ id: "array-root", is_ad: 1 }],
), {});
assert.deepEqual(run(
  "https://api.weibo.cn/2/statuses/container_timeline?containerid=redacted",
  { items: [{ data: { id: "ad", is_ad: 1 } }] },
  { status: 503 },
), {});

{
  const diagnostics = execute(
    "https://api.weibo.cn/2/statuses/container_timeline?containerid=sensitive-container",
    { items: [{ data: { id: "sensitive-post-id", mblogtypename: "广告" } }] },
    { argument: { debug: true } },
  );
  const logs = diagnostics.consoleLogs.concat(diagnostics.logbookLogs).join("\n");
  assert.match(logs, /removed_ads=1/);
  assert.doesNotMatch(logs, /sensitive-post-id|sensitive-container/);
}

assert.match(moduleText, /^#!name=微博 \(候选\)$/m);
assert.match(moduleText, /#!requirement=CORE_VERSION>=20 && SYSTEM = 'iOS'/);
assert.match(moduleText, /#!arguments=.*清理明确广告:true.*启用调试模式:false/);
assert.match(moduleText, /max-size=6291456/);
assert.ok(moduleText.includes(
  "script-path=https://raw.githubusercontent.com/mulanshan/surge/surge-self-v2026.08.15/rewrite/Surge/scripts/weibo/weibo-self.response.js",
));
assert.equal(moduleText.includes("script-path=https://raw.githubusercontent.com/mulanshan/surge/main/"), false);
assert.doesNotMatch(moduleText, /new\.vip\.weibo/);
assert.doesNotMatch(moduleText, /DOMAIN-SUFFIX,(?:biz\.)?weibo/);
assert.doesNotMatch(moduleText, /direct_messages\/user_list|messageflow\/notice|profile\/me/);

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
assert.match(scriptEntries[0], /^weibo\.self\.response = type=http-response,/);
assert.match(scriptEntries[0], /debug=\{\{\{启用调试模式\}\}\}/);
assert.deepEqual(sectionEntries("Rule"), [
  "DOMAIN,adpinpai.video.weibocdn.com,REJECT",
]);
assert.deepEqual(sectionEntries("MITM"), [
  "hostname = %APPEND% api.weibo.cn, mapi.weibo.cn, mapi.weibo.com, bootrealtime.uve.weibo.com, bootpreload.uve.weibo.com, sdkapp.uve.weibo.com, wbapp.uve.weibo.com",
]);

console.log("Weibo Self tests passed");
