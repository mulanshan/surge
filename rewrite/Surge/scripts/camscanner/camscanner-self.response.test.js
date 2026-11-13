const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "camscanner-self.response.js"), "utf8");

function run(endpoint, payload, argument = {}, host = "open.camscanner.com") {
  let output;
  const context = {
    ArrayBuffer,
    TextDecoder,
    Uint8Array,
    URL,
    console: { log() {} },
    $argument: JSON.stringify(argument),
    $request: { url: `https://${host}/${endpoint}` },
    $response: { body: typeof payload === "string" ? payload : JSON.stringify(payload), status: 200 },
    $done(value) {
      output = value;
    },
  };
  vm.runInNewContext(script, context, { filename: "camscanner-self.response.js" });
  return output && typeof output === "object" ? JSON.parse(JSON.stringify(output)) : output;
}

function bodyOf(result) {
  return result && result.body ? JSON.parse(result.body) : null;
}

assert.deepEqual(run("sync/get_page_cfg_v2", {
  data: {
    notice: { type: "notice", title: "版本通知" },
    noticeList: [{ type: "notice", title: "服务公告" }],
    operate: { type: "operate", enabled: true },
    operation: { type: "operation", value: "scan" },
    operationList: [{ type: "operation", title: "批量扫描" }],
    float_btn: { visible: true, action: "camera" },
    ocr_config: { lang: "zh" },
    pdf_export: { enabled: true },
    address: "kept",
    name: "广告行业研究中心",
    title: "广告行业观察",
  },
}), {});

{
  const result = bodyOf(run("sync/get_page_cfg", {
    data: {
      adList: [{ id: "ad-1" }],
      popup: { title: "推广" },
      float_ad: { id: "float-ad-1" },
      float_btn: { visible: true },
      user_property: { vip_level: 1 },
      noticeList: [{ id: "notice-1" }],
      operation: { id: "operation-1" },
    },
  }, {}, "api.intsig.net"));
  assert.deepEqual(result.data.adList, []);
  assert.deepEqual(result.data.popup, {});
  assert.deepEqual(result.data.float_ad, {});
  assert.equal(result.data.float_btn.visible, true);
  assert.equal(result.data.user_property.vip_level, 1);
  assert.equal(result.data.noticeList[0].id, "notice-1");
  assert.equal(result.data.operation.id, "operation-1");
}

{
  const startpic = bodyOf(run("user/cs/operating/app/get_startpic?client=ios", {
    ret: 0,
    data: {
      pic_list: [{ id: "splash-1" }],
      interval: 5,
    },
  }, {}, "api-cs.intsig.net"));
  assert.equal(startpic.ret, 0);
  assert.deepEqual(startpic.data, {});
}

{
  const adCfg = bodyOf(run("sync/get_ad_data", {
    ret: 0,
    data: { slots: [{ id: "slot-1" }] },
  }));
  assert.equal(adCfg.ret, 0);
  assert.deepEqual(adCfg.data, {});
}

assert.deepEqual(
  run("sync/get_ad_data", { ret: 0, data: { slots: [1] } }, { cleanAds: false }),
  {},
);
assert.deepEqual(run("sync/query_property", { data: { adList: [1] } }), {});
assert.deepEqual(run("purchase/cs/query_property", { data: { adList: [1], vip: 0 } }, {}, "api.intsig.net"), {});
assert.deepEqual(run("sync/get_page_cfg", "not-json"), {});

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

console.log("CamScanner Self tests passed");
