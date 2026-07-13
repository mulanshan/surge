const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "youtube-self.response.js"), "utf8");
const fixture = JSON.parse(
  fs.readFileSync(path.join(__dirname, "fixtures", "player-equal-length-capability.json"), "utf8"),
);

function execute(body, endpoint = fixture.endpoint, argument = fixture.argument) {
  let output;
  const consoleLogs = [];
  const logbookLogs = [];
  const response =
    typeof body === "string"
      ? { body }
      : { bodyBytes: body instanceof Uint8Array ? body : new Uint8Array(body) };
  const context = {
    ArrayBuffer,
    TextDecoder,
    Uint8Array,
    console: { log(message) { consoleLogs.push(String(message)); } },
    $surge: { logbook(message) { logbookLogs.push(String(message)); } },
    $argument: JSON.stringify(argument),
    $request: { url: `https://youtubei.googleapis.com/youtubei/v1/${endpoint}` },
    $response: response,
    $done(value) {
      output = value;
    },
  };
  vm.runInNewContext(script, context, { filename: "youtube-self.response.js" });
  return { output, consoleLogs, logbookLogs };
}

function assertNoLogs(result, message) {
  assert.deepEqual(result.consoleLogs, [], `${message}: console must stay quiet`);
  assert.deepEqual(result.logbookLogs, [], `${message}: Logbook must stay quiet`);
}

function encodeVarint(value) {
  let remaining = BigInt(value);
  const output = [];
  do {
    let byte = Number(remaining & 0x7fn);
    remaining >>= 7n;
    if (remaining) byte |= 0x80;
    output.push(byte);
  } while (remaining);
  return output;
}

function concatBytes(...chunks) {
  return Uint8Array.from(chunks.flatMap((chunk) => Array.from(chunk)));
}

function encodeLengthField(fieldNumber, payload) {
  const bytes = payload instanceof Uint8Array ? payload : Uint8Array.from(payload);
  return concatBytes(
    encodeVarint((BigInt(fieldNumber) << 3n) | 2n),
    encodeVarint(bytes.length),
    bytes,
  );
}

{
  const result = execute(fixture.before);
  assertNoLogs(result, "default protobuf edit");
  assert.ok(result.output && result.output.body instanceof Uint8Array, "equal-length byte edits must be returned");
  assert.equal(result.output.body.length, fixture.before.length);
  assert.deepEqual(Array.from(result.output.body), fixture.after);
}

{
  const result = execute(fixture.after);
  assertNoLogs(result, "default protobuf passthrough");
  assert.equal(Object.keys(result.output).length, 0);
}

{
  const result = execute(fixture.before, fixture.endpoint, { ...fixture.argument, debug: true });
  assert.ok(result.consoleLogs.some((line) => line.includes("protobuf player")));
  assert.ok(result.logbookLogs.some((line) => line.includes("protobuf player")));
}

{
  const result = execute(fixture.before, fixture.endpoint, { ...fixture.argument, debug: "false" });
  assertNoLogs(result, "string false debug value");
}

{
  const result = execute('{"adPlacements":[1],"value":2}', "player");
  assertNoLogs(result, "default JSON cleanup");
  assert.equal(JSON.parse(result.output.body).value, 2);
  assert.equal("adPlacements" in JSON.parse(result.output.body), false);
}

{
  const result = execute('{"adPlacements":[1]}', "player", { debug: true });
  assert.ok(result.consoleLogs.some((line) => line.includes("json player")));
}

{
  const result = execute("{", "player");
  assert.equal(Object.keys(result.output).length, 0);
  assert.ok(result.consoleLogs.some((line) => line.includes("error player")));
  assert.ok(result.logbookLogs.some((line) => line.includes("error player")));
}

const emptyPlayer = encodeLengthField(2, []);

{
  const twoPlayers = encodeLengthField(1, concatBytes(emptyPlayer, emptyPlayer));
  const result = execute(twoPlayers, "get_watch");
  assert.equal(Object.keys(result.output).length, 0);
  assert.ok(result.consoleLogs.some((line) => line.includes("protobuf-growth-abort")));
  assert.ok(result.logbookLogs.some((line) => line.includes("protobuf-growth-abort")));
}

{
  const threePlayers = encodeLengthField(1, concatBytes(emptyPlayer, emptyPlayer, emptyPlayer));
  const result = execute(threePlayers, "get_watch");
  assert.equal(Object.keys(result.output).length, 0);
  assert.ok(result.consoleLogs.some((line) => line.includes("protobuf-inflation-abort")));
  assert.ok(result.logbookLogs.some((line) => line.includes("protobuf-inflation-abort")));
}

const adItem = new Uint8Array(64);
adItem.set(new TextEncoder().encode("ad_badge.eml-fe"));
const cleanItem = new Uint8Array(64);
cleanItem.set(new TextEncoder().encode("ordinary-feed-item"));

{
  const oneAdSection = encodeLengthField(50195462, encodeLengthField(1, adItem));
  const result = execute(oneAdSection, "browse");
  assert.equal(Object.keys(result.output).length, 0);
  assert.equal(result.consoleLogs.filter((line) => line.includes("browse-schema-safety")).length, 1);
  assert.equal(result.logbookLogs.filter((line) => line.includes("browse-schema-safety")).length, 1);
  assert.equal(result.consoleLogs.some((line) => line.includes("protobuf-passthrough")), false);
}

{
  const mixedSection = encodeLengthField(
    50195462,
    concatBytes(encodeLengthField(1, adItem), encodeLengthField(1, cleanItem)),
  );
  const result = execute(mixedSection, "browse");
  assertNoLogs(result, "default browse cleanup");
  assert.ok(result.output && result.output.body instanceof Uint8Array, "browse cleanup bytes must be returned");
  assert.ok(result.output.body.length < mixedSection.length);
}

{
  const noAdSection = encodeLengthField(50195462, encodeLengthField(1, cleanItem));
  const result = execute(noAdSection, "browse");
  assertNoLogs(result, "default browse no-op");
  assert.equal(Object.keys(result.output).length, 0);
}

console.log("YouTube Self tests passed");
