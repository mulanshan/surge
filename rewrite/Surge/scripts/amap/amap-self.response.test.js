const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "amap-self.response.js"), "utf8");

function run(endpoint, payload, argument = {}) {
  let output;
  const context = {
    ArrayBuffer,
    TextDecoder,
    Uint8Array,
    console: { log() {} },
    $argument: JSON.stringify(argument),
    $request: { url: `https://m5.amap.com/ws/${endpoint}` },
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

console.log("Amap Self tests passed");
