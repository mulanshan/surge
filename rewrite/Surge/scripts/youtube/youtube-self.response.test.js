const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "youtube-self.response.js"), "utf8");
const fixture = JSON.parse(
  fs.readFileSync(path.join(__dirname, "fixtures", "player-equal-length-capability.json"), "utf8"),
);

function run(bytes, endpoint = fixture.endpoint, argument = fixture.argument) {
  let output;
  const context = {
    ArrayBuffer,
    TextDecoder,
    Uint8Array,
    console: { log() {} },
    $argument: JSON.stringify(argument),
    $request: { url: `https://youtubei.googleapis.com/youtubei/v1/${endpoint}` },
    $response: { bodyBytes: new Uint8Array(bytes) },
    $done(value) {
      output = value;
    },
  };
  vm.runInNewContext(script, context, { filename: "youtube-self.response.js" });
  return output;
}

{
  const result = run(fixture.before);
  assert.ok(result && result.body instanceof Uint8Array, "equal-length byte edits must be returned");
  assert.equal(result.body.length, fixture.before.length);
  assert.deepEqual(Array.from(result.body), fixture.after);
}

assert.equal(Object.keys(run(fixture.after)).length, 0);

console.log("YouTube Self tests passed");
