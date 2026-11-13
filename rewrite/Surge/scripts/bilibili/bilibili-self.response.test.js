const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const scriptPath = path.join(__dirname, "bilibili-self.response.js");
const modulePath = path.join(__dirname, "..", "..", "candidates", "bilibili-self.sgmodule");

assert.ok(fs.existsSync(scriptPath), "missing Bilibili response script");
assert.ok(fs.existsSync(modulePath), "missing Bilibili staged candidate module");

const script = fs.readFileSync(scriptPath, "utf8");
const moduleText = fs.readFileSync(modulePath, "utf8");

function writeVarint(value) {
  const out = [];
  let n = Math.floor(value);
  while (n > 0x7f) {
    out.push((n & 0x7f) | 0x80);
    n = Math.floor(n / 128);
  }
  out.push(n);
  return new Uint8Array(out);
}

function concatBytes(parts) {
  let total = 0;
  for (const part of parts) total += part.length;
  const out = new Uint8Array(total);
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

function fVarint(fieldNo, value) {
  return concatBytes([writeVarint(fieldNo * 8 + 0), writeVarint(value)]);
}

function fBytes(fieldNo, bytes) {
  const payload = typeof bytes === "string" ? new TextEncoder().encode(bytes) : bytes;
  return concatBytes([writeVarint(fieldNo * 8 + 2), writeVarint(payload.length), payload]);
}

function wrapGrpc(payload, compressedFlag = 0x00) {
  const out = new Uint8Array(5 + payload.length);
  out[0] = compressedFlag;
  out[1] = (payload.length >>> 24) & 0xff;
  out[2] = (payload.length >>> 16) & 0xff;
  out[3] = (payload.length >>> 8) & 0xff;
  out[4] = payload.length & 0xff;
  out.set(payload, 5);
  return out;
}

function unwrapGrpc(frame) {
  assert.ok(frame instanceof Uint8Array, "expected Uint8Array gRPC output");
  assert.equal(frame[0], 0x00, "expected uncompressed gRPC flag");
  const len = ((frame[1] << 24) >>> 0) + (frame[2] << 16) + (frame[3] << 8) + frame[4];
  assert.equal(5 + len, frame.length, "gRPC length prefix must match frame body");
  return frame.subarray(5);
}

function execute(url, payload, options = {}) {
  let output;
  let doneCalls = 0;
  const consoleLogs = [];
  const logbookLogs = [];

  let responseBody;
  if (payload instanceof Uint8Array || payload instanceof ArrayBuffer) {
    responseBody = payload;
  } else if (typeof payload === "string") {
    responseBody =
      options.bodyType === "uint8array" ? new TextEncoder().encode(payload) : payload;
  } else {
    const jsonText = JSON.stringify(payload);
    responseBody =
      options.bodyType === "uint8array" ? new TextEncoder().encode(jsonText) : jsonText;
  }

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
    $surge: { logbook(message) { logbookLogs.push(String(message)); } },
    $done(value) {
      doneCalls += 1;
      output = value && typeof value === "object" ? Object.assign({}, value) : value;
    },
  };

  vm.runInNewContext(script, context, { filename: scriptPath });
  assert.equal(doneCalls, 1, "expected exactly one $done call");
  return { output, consoleLogs, logbookLogs };
}

function runJson(url, payload, options = {}) {
  const { output } = execute(url, payload, options);
  if (!output || output.body === undefined) return null;
  if (output.body instanceof Uint8Array) {
    return JSON.parse(new TextDecoder().decode(output.body));
  }
  return JSON.parse(output.body);
}

// 1. Splash JSON endpoints (/x/v2/splash/list, show, brand/list)
{
  const cleaned = runJson(
    "https://app.bilibili.com/x/v2/splash/list?build=91900100",
    {
      code: 0,
      data: {
        max_time: 5,
        min_interval: 300,
        pull_interval: 1800,
        show: [{ id: 101, ad_cb: "splash-ad" }],
        list: [{ id: 101, duration: 5, begin_time: 1700000000, end_time: 1900000000, enable_pre_download: true }],
      },
    },
    { bodyType: "uint8array" },
  );
  assert.deepEqual(cleaned.data.show, []);
  assert.equal(cleaned.data.max_time, 0);
  assert.equal(cleaned.data.min_interval, 86400);
  assert.equal(cleaned.data.pull_interval, 86400);
  assert.equal(cleaned.data.list[0].duration, 0);
  assert.equal(cleaned.data.list[0].enable_pre_download, false);

  // Brand splash preserves user-selectable logos in `list` while clearing `show`.
  const brand = runJson(
    "https://app.bilibili.com/x/v2/splash/brand/list",
    {
      code: 0,
      data: {
        show: [{ id: 1 }],
        list: [{ id: 2, title: "经典粉" }],
      },
    },
  );
  assert.deepEqual(brand.data.show, []);
  assert.equal(brand.data.list.length, 1);
  assert.equal(brand.data.list[0].title, "经典粉");
}

// 2. Home feed & vertical story feed: remove real ads, preserve organic `is_ad_loc` slots!
{
  const feed = runJson(
    "https://app.bilibili.com/x/v2/feed/index?idx=1",
    {
      code: 0,
      data: {
        items: [
          { card_goto: "av", goto: "av", param: "10001", title: "正常视频但处于广告候选槽", is_ad_loc: true },
          { card_goto: "ad_av", goto: "ad", param: "90001", ad_info: { creative_id: 123 } },
          { card_goto: "cm_double", goto: "cm", param: "90002" },
          {
            card_goto: "banner",
            banner_item: [
              { id: 1, type: "static", title: "正常分区活动" },
              { id: 2, type: "ad", is_ad: true, title: "商业轮播广告" },
            ],
          },
          {
            card_goto: "banner",
            banner_item: [{ id: 3, type: "ad", ad_cb: "only-ad-banner" }],
          },
        ],
      },
    },
    { bodyType: "uint8array" },
  );
  assert.equal(feed.data.items.length, 2);
  assert.equal(feed.data.items[0].param, "10001");
  assert.equal(feed.data.items[1].banner_item.length, 1);
  assert.equal(feed.data.items[1].banner_item[0].id, 1);

  const story = runJson(
    "https://app.bilibili.com/x/v2/feed/index/story",
    {
      code: 0,
      data: {
        items: [
          { card_goto: "vertical_av", goto: "vertical_av", param: "20001" },
          { card_goto: "ad_player", goto: "ad", is_ad: true, param: "90003" },
        ],
      },
    },
  );
  assert.deepEqual(story.data.items.map((x) => x.param), ["20001"]);
}

// 3. Search square & Live room banners
{
  const square = runJson(
    "https://app.bilibili.com/x/v2/search/square",
    {
      code: 0,
      data: [
        { type: "trending", data: { list: [{ keyword: "正常热搜" }, { keyword: "商业推广词", is_ad: true }] } },
        { type: "ada", data: { list: [{ keyword: "整块推广位" }] } },
      ],
    },
  );
  assert.equal(square.data.length, 1);
  assert.deepEqual(square.data[0].data.list, [{ keyword: "正常热搜" }]);

  const live = runJson(
    "https://api.live.bilibili.com/xlive/app-room/v1/index/getInfoByRoom?room_id=1",
    {
      code: 0,
      data: {
        room_info: { room_id: 1, title: "正常直播间" },
        activity_banner_info: { id: 88 },
        ad_banner_info: { id: 99 },
      },
    },
  );
  assert.equal(live.data.room_info.room_id, 1);
  assert.equal(live.data.activity_banner_info, null);
  assert.equal(live.data.ad_banner_info, null);
}

// 4. Optional bottom Mall tab hiding (off by default, active when hideMallTab=true)
{
  const tabPayload = {
    code: 0,
    data: {
      bottom: [
        { id: 1, name: "首页", tab_id: "home", pos: 1 },
        { id: 2, name: "动态", tab_id: "dynamic", pos: 2 },
        { id: 3, name: "会员购", tab_id: "global_mall", uri: "bilibili://mall/home", pos: 3 },
        { id: 4, name: "我的", tab_id: "mine", pos: 4 },
      ],
    },
  };
  assert.equal(
    runJson("https://app.bilibili.com/x/resource/show/tab/v2", tabPayload),
    null,
  );
  const hidden = runJson(
    "https://app.bilibili.com/x/resource/show/tab/v2",
    tabPayload,
    { argument: { hideMallTab: true } },
  );
  assert.deepEqual(
    hidden.data.bottom.map((t) => ({ name: t.name, pos: t.pos })),
    [
      { name: "首页", pos: 1 },
      { name: "动态", pos: 2 },
      { name: "我的", pos: 3 },
    ],
  );
}

// 5. gRPC View/View & RelatesFeed (both viewunite.v1 and view.v1)
{
  const organicCard = concatBytes([fVarint(1, 1), fBytes(2, fBytes(1, "organic-av"))]);
  const cmCardByType = concatBytes([fVarint(1, 5), fBytes(6, fBytes(1, "ad-card"))]);
  const cmCardByStock = concatBytes([fVarint(1, 1), fBytes(11, fBytes(1, "cm-stock-any"))]);
  const relatesMsg = concatBytes([
    fBytes(1, organicCard),
    fBytes(1, cmCardByType),
    fBytes(1, cmCardByStock),
  ]);
  const introModule = concatBytes([fVarint(1, 28), fBytes(22, relatesMsg)]);
  const introTab = fBytes(2, introModule);
  const tabModule = concatBytes([fVarint(1, 1), fBytes(2, introTab)]);
  const tab = fBytes(1, tabModule);
  const viewUniteReply = concatBytes([
    fBytes(2, fBytes(1, "arc-metadata")),
    fBytes(5, tab),
    fBytes(7, fBytes(1, "top-level-cm")),
  ]);

  const { output } = execute(
    "https://grpc.biliapi.net/bilibili.app.viewunite.v1.View/View",
    wrapGrpc(viewUniteReply),
  );
  const decoded = unwrapGrpc(output.body);
  assert.ok(decoded.length < viewUniteReply.length);
  const textView = new TextDecoder().decode(decoded);
  assert.match(textView, /arc-metadata/);
  assert.match(textView, /organic-av/);
  assert.doesNotMatch(textView, /top-level-cm|ad-card|cm-stock-any/);

  // RelatesFeed (viewunite.v1)
  const relatesFeedReply = concatBytes([fBytes(1, organicCard), fBytes(1, cmCardByType)]);
  const relatesRes = execute(
    "https://grpc.biliapi.net/bilibili.app.viewunite.v1.View/RelatesFeed",
    wrapGrpc(relatesFeedReply),
  );
  const relatesDecoded = new TextDecoder().decode(unwrapGrpc(relatesRes.output.body));
  assert.match(relatesDecoded, /organic-av/);
  assert.doesNotMatch(relatesDecoded, /ad-card/);

  // Legacy View/View (view.v1): strips cms=30, cm_config=31, cm_under_player=48, and cm Relate
  const v1OrganicRelate = concatBytes([fVarint(1, 100), fBytes(3, "organic-v1"), fBytes(7, "av")]);
  const v1AdRelate = concatBytes([fVarint(1, 999), fBytes(3, "sponsored-v1"), fBytes(7, "cm"), fBytes(28, fBytes(1, "cm-blob"))]);
  const viewV1Reply = concatBytes([
    fBytes(1, fBytes(1, "v1-arc")),
    fBytes(10, v1OrganicRelate),
    fBytes(10, v1AdRelate),
    fBytes(30, fBytes(1, "v1-cms-30")),
    fBytes(31, fBytes(1, "v1-cm-config-31")),
    fBytes(48, fBytes(1, "v1-cm-under-player-48")),
  ]);
  const v1Res = execute(
    "https://app.bilibili.com/bilibili.app.view.v1.View/View",
    wrapGrpc(viewV1Reply),
  );
  const v1Decoded = new TextDecoder().decode(unwrapGrpc(v1Res.output.body));
  assert.match(v1Decoded, /v1-arc/);
  assert.match(v1Decoded, /organic-v1/);
  assert.doesNotMatch(v1Decoded, /sponsored-v1|v1-cms-30|v1-cm-config-31|v1-cm-under-player-48/);
}

// 6. gRPC Reply/MainList: strips `cm = 11` while preserving `up_top = 4` creator pinned comment
{
  const mainListReply = concatBytes([
    fBytes(2, fBytes(1, "normal-comment")),
    fBytes(4, fBytes(1, "creator-up-top-note")),
    fBytes(11, fBytes(1, "comment-commercial-ad")),
  ]);
  const replyRes = execute(
    "https://grpc.biliapi.net/bilibili.main.community.reply.v1.Reply/MainList",
    wrapGrpc(mainListReply),
  );
  const replyDecoded = new TextDecoder().decode(unwrapGrpc(replyRes.output.body));
  assert.match(replyDecoded, /normal-comment/);
  assert.match(replyDecoded, /creator-up-top-note/);
  assert.doesNotMatch(replyDecoded, /comment-commercial-ad/);
}

// 7. gRPC Dynamic/DynAll: strips DYNAMIC_TYPE_AD (15) while keeping AV (2) & DRAW (7)
{
  const avDyn = concatBytes([fVarint(1, 2), fBytes(6, "organic-video-dyn")]);
  const adDyn = concatBytes([fVarint(1, 15), fBytes(6, "promoted-ad-dyn")]);
  const forwardAdDyn = concatBytes([fVarint(1, 1), fVarint(2, 15), fBytes(6, "forwarded-ad-dyn")]);
  const dynList = concatBytes([fBytes(1, avDyn), fBytes(1, adDyn), fBytes(1, forwardAdDyn), fVarint(5, 1)]);
  const dynAllReply = fBytes(1, dynList);

  const dynRes = execute(
    "https://grpc.biliapi.net/bilibili.app.dynamic.v2.Dynamic/DynAll",
    wrapGrpc(dynAllReply),
  );
  const dynDecoded = new TextDecoder().decode(unwrapGrpc(dynRes.output.body));
  assert.match(dynDecoded, /organic-video-dyn/);
  assert.doesNotMatch(dynDecoded, /promoted-ad-dyn|forwarded-ad-dyn/);
}

// 8. Safety guards: compressed gRPC frame (0x01), non-whitelisted account/VIP URLs, HTTP 500, malformed JSON, cleanAds=false
{
  const compressedFrame = wrapGrpc(fBytes(11, fBytes(1, "gzip-like-bytes")), 0x01);
  assert.deepEqual(
    execute("https://grpc.biliapi.net/bilibili.main.community.reply.v1.Reply/MainList", compressedFrame).output,
    {},
  );

  // Account/VIP/passport endpoints must NEVER be touched
  assert.deepEqual(
    execute(
      "https://app.bilibili.com/x/v2/account/mine?access_key=secret-token",
      { code: 0, data: { vip_section: { title: "大会员" }, is_ad: true, ad_info: { id: 1 } } },
    ).output,
    {},
  );

  // cleanAds=false passes ads through untouched
  assert.deepEqual(
    execute(
      "https://app.bilibili.com/x/v2/feed/index",
      { code: 0, data: { items: [{ card_goto: "ad_av", goto: "ad", ad_info: { id: 1 } }] } },
      { argument: { cleanAds: false } },
    ).output,
    {},
  );

  // HTTP 500 or malformed body passes through untouched
  assert.deepEqual(
    execute(
      "https://app.bilibili.com/x/v2/feed/index",
      { code: 0, data: { items: [{ card_goto: "ad_av", goto: "ad", ad_info: { id: 1 } }] } },
      { status: 502 },
    ).output,
    {},
  );
  assert.deepEqual(
    execute("https://app.bilibili.com/x/v2/feed/index", "not-valid-json").output,
    {},
  );
}

// 9. Redacted count-only debug diagnostics
{
  const diag = execute(
    "https://app.bilibili.com/x/v2/feed/index?access_key=super-secret-ak&mid=999888",
    {
      code: 0,
      data: {
        items: [{ card_goto: "ad_av", goto: "ad", title: "敏感广告标题", ad_info: { trace: "secret-trace-id" } }],
      },
    },
    { argument: { debug: true } },
  );
  const combinedLogs = diag.consoleLogs.concat(diag.logbookLogs).join("\n");
  assert.match(combinedLogs, /removed_ads=1/);
  assert.doesNotMatch(combinedLogs, /super-secret-ak|999888|敏感广告标题|secret-trace-id/);
}

// 10. Module & supply-chain assertions
assert.match(moduleText, /^#!name=哔哩哔哩 \(候选 2026\.11\.13\)$/m);
assert.doesNotMatch(moduleText, /^#!name=.*self/im);
assert.match(moduleText, /#!requirement=CORE_VERSION>=20 && SYSTEM = 'iOS'/);
assert.match(
  moduleText,
  /#!arguments=清理明确广告:true,隐藏底栏会员购:false,PCDN节点策略:DIRECT,启用调试模式:false/,
);
assert.match(moduleText, /binary-body-mode=1/);
assert.match(moduleText, /max-size=6291456/);
assert.ok(
  moduleText.includes(
    "script-path=https://raw.githubusercontent.com/mulanshan/surge/surge-self-v2026.11.13/rewrite/Surge/scripts/bilibili/bilibili-self.response.js?v=20261113-1",
  ),
);
assert.equal(
  moduleText.includes("script-path=https://raw.githubusercontent.com/mulanshan/surge/main/"),
  false,
);
assert.doesNotMatch(moduleText, /^DOMAIN(?:-SUFFIX)?,bilibili\.com/m);
assert.doesNotMatch(moduleText, /^DOMAIN(?:-SUFFIX)?,cm\.bilibili\.com/m);
assert.doesNotMatch(moduleText, /^PROTOCOL,UDP,REJECT/m);

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

assert.equal(sectionEntries("Script").length, 1);
assert.deepEqual(sectionEntries("MITM"), [
  "hostname = %APPEND% app.bilibili.com, api.bilibili.com, api.live.bilibili.com, grpc.biliapi.net",
]);
assert.ok(sectionEntries("Rule").includes("DOMAIN,httpdns.bilivideo.com,REJECT"));

console.log("Bilibili Self tests passed");
