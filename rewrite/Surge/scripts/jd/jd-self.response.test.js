const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "jd-self.response.js"), "utf8");

function run(functionId, payload, argument = {}, requestOptions = {}) {
  let output;
  const context = {
    ArrayBuffer,
    TextDecoder,
    Uint8Array,
    console: { log() {} },
    decodeURIComponent,
    $argument: JSON.stringify(argument),
    $request: {
      url: requestOptions.url || `https://api.m.jd.com/client.action?functionId=${functionId}`,
      body: requestOptions.body,
    },
    $response: { body: typeof payload === "string" ? payload : JSON.stringify(payload) },
    $done(value) {
      output = value;
    },
  };
  vm.runInNewContext(script, context, { filename: "jd-self.response.js" });
  return output && typeof output === "object" ? JSON.parse(JSON.stringify(output)) : output;
}

function bodyOf(result) {
  return result && result.body ? JSON.parse(result.body) : null;
}

{
  const result = bodyOf(run("basicConfig", {
    code: "0",
    data: {
      JDMessage: { socketmonitor: { isSocketEstablishedAhead: 1, isSocketReport: true, keep: 1 } },
      JDHttpToolKit: { httpdns: { httpdns: 1, keep: 1 } },
    },
  }));
  assert.equal(result.data.JDMessage.socketmonitor.isSocketEstablishedAhead, 0);
  assert.equal(result.data.JDMessage.socketmonitor.isSocketReport, 0);
  assert.equal(result.data.JDMessage.socketmonitor.keep, 1);
  assert.equal(result.data.JDHttpToolKit.httpdns.httpdns, 0);
}

{
  const result = bodyOf(run("welcomeHome", {
    code: "0",
    data: {
      adList: [{ id: 1 }],
      popup: { url: "https://example.invalid/ad" },
      navigation: [{ title: "首页" }],
      account: { userName: "kept" },
    },
  }));
  assert.deepEqual(result.data.adList, []);
  assert.deepEqual(result.data.popup, {});
  assert.equal(result.data.navigation[0].title, "首页");
  assert.equal(result.data.account.userName, "kept");
}

{
  const result = bodyOf(run("getTabHomeInfo", {
    data: {
      floorList: [
        { cardType: "banner", title: "推广" },
        { cardType: "navigation", title: "京东超市" },
        { isAd: 1, title: "sponsored" },
      ],
      productList: [{ sku: "1001", promotionPrice: "9.90" }],
    },
  }));
  assert.equal(result.data.floorList.length, 1);
  assert.equal(result.data.floorList[0].title, "京东超市");
  assert.equal(result.data.productList[0].promotionPrice, "9.90");
}

{
  const result = bodyOf(run("personinfoBusiness", {
    data: {
      modules: [
        { type: "popup", title: "广告" },
        { type: "service", title: "客户服务" },
      ],
      order: { list: [{ orderId: "JD-1", banner: "must stay inside protected order subtree" }] },
      wallet: { balance: "88.00" },
    },
  }));
  assert.equal(result.data.modules.length, 1);
  assert.equal(result.data.modules[0].title, "客户服务");
  assert.equal(result.data.order.list[0].banner, "must stay inside protected order subtree");
  assert.equal(result.data.wallet.balance, "88.00");
}

{
  const unchanged = run("orderTrackBusiness", {
    data: { popup: { title: "广告" }, order: { orderId: "JD-2" } },
  }, { cleanOrderPromotions: false });
  assert.deepEqual(unchanged, {});
}

{
  const result = bodyOf(run("uniformRecommend", {
    code: "0",
    data: { wareList: [{ sku: "1001" }], traceId: "current-version" },
  }));
  assert.deepEqual(result.data.wareList, []);
  assert.equal(result.data.traceId, "current-version");
}

{
  const result = bodyOf(run("uniformRecommend6", {
    code: "0",
    data: { recommendList: [{ sku: "1002" }], traceId: "kept" },
  }));
  assert.deepEqual(result.data.recommendList, []);
  assert.equal(result.data.traceId, "kept");
}

assert.deepEqual(run("unknownFunction", { data: { adList: [1] } }), {});
assert.deepEqual(run("welcomeHome", "not-json"), {});

{
  const result = bodyOf(run("ignored", {
    data: { recommendList: [{ sku: "1003" }] },
  }, {}, {
    url: "https://api.m.jd.com/",
    body: "appid=jdapp&functionId=uniformRecommend&t=1",
  }));
  assert.deepEqual(result.data.recommendList, []);
}

{
  const result = bodyOf(run("ignored", {
    data: { wareList: [{ sku: "1004" }] },
  }, {}, {
    url: "https://api.m.jd.com/api",
    body: JSON.stringify({ functionId: "uniformRecommend" }),
  }));
  assert.deepEqual(result.data.wareList, []);
}

console.log("JD Self tests passed");
