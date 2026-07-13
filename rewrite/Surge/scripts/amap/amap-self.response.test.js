const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "amap-self.response.js"), "utf8");
const moduleText = fs.readFileSync(path.join(__dirname, "..", "..", "amap-self.sgmodule"), "utf8");

function run(endpoint, payload, argument = {}, host = "m5.amap.com") {
  let output;
  const context = {
    ArrayBuffer,
    TextDecoder,
    Uint8Array,
    console: { log() {} },
    $argument: JSON.stringify(argument),
    $request: { url: `https://${host}/ws/${endpoint}` },
    $response: { body: typeof payload === "string" ? payload : JSON.stringify(payload) },
    $done(value) {
      output = value;
    },
  };
  vm.runInNewContext(script, context, { filename: "amap-self.response.js" });
  return output && typeof output === "object" ? JSON.parse(JSON.stringify(output)) : output;
}

function bodyOf(result) {
  return result && result.body ? JSON.parse(result.body) : null;
}

assert.deepEqual(run("faas/amap-navigation/main-page", {
  data: {
    address: { type: "address", value: "杭州市" },
    shadow: { type: "shadow", enabled: true },
    loading: { type: "loading", text: "加载中" },
    cards: [
      { dataType: "TravelCard", title: "行程" },
      { dataType: "shadow", title: "地图阴影" },
    ],
  },
}), {});

{
  const result = bodyOf(run("faas/amap-navigation/main-page", {
    data: {
      feedAd: { id: "ad-1" },
      address: { value: "kept" },
      cardList: {
        route: { dataType: "TravelCard", title: "出行" },
        sponsored: { dataType: "feedAd", title: "广告" },
      },
    },
  }));
  assert.equal(result.data.feedAd, undefined);
  assert.equal(result.data.address.value, "kept");
  assert.equal(result.data.cardList.route.title, "出行");
  assert.equal(result.data.cardList.sponsored, undefined);
}

assert.deepEqual(run("faas/amap-navigation/main-page", "not-json"), {});
assert.match(moduleText, /\(\?:m5\|m5-zb\|m5-x\)\\\.amap\\\.com/);
assert.match(moduleText, /hostname = %APPEND% m5\.amap\.com, m5-zb\.amap\.com, m5-x\.amap\.com, awaken\.amap\.com/);

{
  const result = bodyOf(run("valueadded/alimama/splash_screen", {
    data: [{ id: "splash-ad" }],
    status: 1,
  }));
  assert.deepEqual(result.data, []);
  assert.equal(result.status, 1);
}

{
  const result = bodyOf(run("msgbox/pull", {
    data: {
      msgs: [
        { id: "service-1", type: "traffic_alert", title: "道路拥堵提醒" },
        { id: "service-flag-0", is_ad: "0", title: "路线更新" },
        { id: "service-flag-false", is_ad: "false", title: "收藏地点提醒" },
        { id: "ad-1", is_ad: true, title: "推广" },
        { id: "ad-string-flag", is_ad: "1", title: "推广活动" },
      ],
      noticeList: [
        { id: "notice-1", title: "账户安全通知" },
        { id: "ad-2", ad_id: "campaign-2" },
      ],
    },
  }));
  assert.deepEqual(result.data.msgs.map((item) => item.id), [
    "service-1",
    "service-flag-0",
    "service-flag-false",
  ]);
  assert.deepEqual(result.data.noticeList.map((item) => item.id), ["notice-1"]);
}

{
  const result = bodyOf(run("shield/dsp/profile/index/nodefaas", {
    data: {
      banners: [
        { id: "organic-1", type: "navigation_tip", title: "出行提示" },
        { id: "ad-3", type: "feedAd", title: "广告" },
      ],
      popup: {
        cards: [
          { id: "organic-2", dataType: "TravelCard" },
          { id: "ad-4", sponsored: true },
        ],
      },
    },
  }));
  assert.deepEqual(result.data.banners.map((item) => item.id), ["organic-1"]);
  assert.deepEqual(result.data.popup.cards.map((item) => item.id), ["organic-2"]);
}

{
  const result = bodyOf(run("shield/search/new_hotword", {
    data: {
      normal: { status: 0, version: "1", value: "景点" },
      recommend_ad: { status: 0, version: "2", value: "推广词" },
    },
  }, {}, "m5-x.amap.com"));
  assert.equal(result.data.normal.value, "景点");
  assert.deepEqual(result.data.recommend_ad, { status: 1, version: "", value: "" });
}

console.log("Amap Self tests passed");
