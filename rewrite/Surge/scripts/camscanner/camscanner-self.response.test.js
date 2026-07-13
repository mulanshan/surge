const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "camscanner-self.response.js"), "utf8");

function run(endpoint, payload, argument = {}) {
  let output;
  const context = {
    ArrayBuffer,
    TextDecoder,
    Uint8Array,
    URL,
    console: { log() {} },
    $argument: JSON.stringify(argument),
    $request: { url: `https://open.camscanner.com/${endpoint}` },
    $response: { body: typeof payload === "string" ? payload : JSON.stringify(payload) },
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
      noticeList: [{ id: "notice-1" }],
      operation: { id: "operation-1" },
    },
  }));
  assert.deepEqual(result.data.adList, []);
  assert.deepEqual(result.data.popup, {});
  assert.equal(result.data.noticeList[0].id, "notice-1");
  assert.equal(result.data.operation.id, "operation-1");
}

assert.deepEqual(run("sync/query_property", { data: { adList: [1] } }), {});
assert.deepEqual(run("sync/get_page_cfg", "not-json"), {});

console.log("CamScanner Self tests passed");
