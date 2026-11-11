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

// Text-fallback structural guards. Community reports against the same
// protobuf-rewrite approach (Maasea/sgmodule issues, 2026: get_watch layout
// changes, new serving domains, YouTube Music breakage) show the failure mode
// is usually silent over- or under-matching, so the fallback must never fire
// on organic text or on sub-card fragments.
function textFilledItem(text, size) {
  const item = new Uint8Array(size);
  item.set(new TextEncoder().encode(text));
  return item;
}

{
  // Organic card mentioning "sponsored" in lowercase prose must survive.
  const organicCard = textFilledItem("weekly sponsored segment review episode", 8192);
  const section = encodeLengthField(
    50195462,
    concatBytes(encodeLengthField(1, organicCard), encodeLengthField(1, cleanItem)),
  );
  const result = execute(section, "browse");
  assertNoLogs(result, "organic sponsored-text passthrough");
  assert.equal(Object.keys(result.output).length, 0);
}

{
  // Card-sized payload carrying the exact sponsor badge must be removed.
  const badgeCard = textFilledItem("赞助商广告", 8192);
  const section = encodeLengthField(
    50195462,
    concatBytes(encodeLengthField(1, badgeCard), encodeLengthField(1, cleanItem)),
  );
  const result = execute(section, "browse");
  assertNoLogs(result, "badge card cleanup");
  assert.ok(result.output && result.output.body instanceof Uint8Array, "badge cleanup bytes must be returned");
  assert.ok(result.output.body.length < section.length);
}

{
  // Sub-card fragments with badge text stay untouched (size guard).
  const badgeFragment = textFilledItem("赞助商广告", 512);
  const section = encodeLengthField(
    50195462,
    concatBytes(encodeLengthField(1, badgeFragment), encodeLengthField(1, cleanItem)),
  );
  const result = execute(section, "browse");
  assertNoLogs(result, "badge fragment passthrough");
  assert.equal(Object.keys(result.output).length, 0);
}

// Caption translation (recovered feature): JSON player path only.
const playerWithCaptions = JSON.stringify({
  playabilityStatus: {},
  captions: {
    playerCaptionsTracklistRenderer: {
      captionTracks: [
        { baseUrl: "https://example.com/api/timedtext?v=1", languageCode: "en", vssId: ".en" },
      ],
    },
  },
});

{
  const result = execute(playerWithCaptions, "player", { captionLang: "zh-Hans" });
  const payload = JSON.parse(result.output.body);
  const tracks = payload.captions.playerCaptionsTracklistRenderer.captionTracks;
  assert.equal(tracks.length, 2, "translated caption track must be appended");
  assert.ok(tracks[1].baseUrl.endsWith("&tlang=zh-Hans"));
  assert.equal(tracks[1].languageCode, "zh-Hans");
  assert.ok(tracks.every((track) => track.isTranslatable === true));
}

{
  const result = execute(playerWithCaptions, "player", {});
  const payload = JSON.parse(result.output.body);
  const tracks = payload.captions.playerCaptionsTracklistRenderer.captionTracks;
  assert.equal(tracks.length, 1, "captionLang off must leave tracks untouched");
  assert.equal("isTranslatable" in tracks[0], false);
}

{
  const existing = JSON.stringify({
    playabilityStatus: {},
    captions: {
      playerCaptionsTracklistRenderer: {
        captionTracks: [
          { baseUrl: "https://example.com/api/timedtext?v=1", languageCode: "zh-Hans", vssId: ".zh-Hans" },
        ],
      },
    },
  });
  const result = execute(existing, "player", { captionLang: "zh-Hans" });
  const payload = JSON.parse(result.output.body);
  const tracks = payload.captions.playerCaptionsTracklistRenderer.captionTracks;
  assert.equal(tracks.length, 1, "no duplicate track when target language already exists");
}

{
  // Recovered renderer keys must be removed from JSON feeds.
  const feed = JSON.stringify({
    items: [{ promotedItemRenderer: { x: 1 } }, { videoRenderer: { videoId: "ok" } }],
  });
  const result = execute(feed, "browse", {});
  const payload = JSON.parse(result.output.body);
  assert.equal(payload.items.length, 1);
  assert.ok(payload.items[0].videoRenderer);
}

{
  // account/get_setting background-playback injection (+101 bytes: 26683 -> 26784)
  // must succeed without triggering protobuf-inflation-abort or protobuf-growth-abort.
  const categoryIdField = concatBytes(
    encodeVarint((4n << 3n) | 0n),
    encodeVarint(10135n),
  );
  const categoryItem = encodeLengthField(66930374, categoryIdField);
  const settingItem = encodeLengthField(6, categoryItem);
  const collectionItem = encodeLengthField(7, categoryItem);
  const paddingPayload = new Uint8Array(
    26683 - settingItem.length - collectionItem.length - 4,
  );
  const paddingField = encodeLengthField(1, paddingPayload);
  const settingResponse = concatBytes(paddingField, settingItem, collectionItem);
  assert.equal(settingResponse.length, 26683);

  for (const settingEndpoint of ["account/get_setting", "account/get_setting_values"]) {
    const result = execute(settingResponse, settingEndpoint);
    assertNoLogs(result, `${settingEndpoint} background playback injection`);
    assert.ok(result.output && result.output.body instanceof Uint8Array);
    assert.equal(result.output.body.length, 26784);
  }

  // Multiple setting categories that inflate by >256 bytes must still abort safely.
  const excessiveSetting = concatBytes(
    settingItem,
    settingItem,
    settingItem,
    settingItem,
    settingItem,
    settingItem,
    settingItem,
  );
  const aborted = execute(excessiveSetting, "account/get_setting");
  assert.equal(Object.keys(aborted.output).length, 0);
  assert.ok(aborted.logbookLogs.some((line) => line.includes("protobuf-inflation-abort")));
}

{
  // Performance & lazy-decoding regression:
  // 1) When debug=false and no safety abort fires, browse feed cleanup must not
  //    UTF-8 decode the full multi-megabyte buffer for markerHits() or decode
  //    unrelated non-ItemSectionRenderer blobs.
  // 2) Deeply nested ItemSectionRenderers and next ad fragments must still be
  //    cleaned identically in a few milliseconds on ~2 MB payloads.
  const organicCardBytes = textFilledItem("organic video title and description", 1024);
  const sponsoredCardBytes = textFilledItem("ad_badge.eml-fe promoted card", 1024);
  const cleanSection = encodeLengthField(
    50195462,
    concatBytes(
      encodeLengthField(1, organicCardBytes),
      encodeLengthField(1, organicCardBytes),
      encodeLengthField(1, sponsoredCardBytes),
    ),
  );
  const nestedSectionTree = encodeLengthField(
    9,
    encodeLengthField(49399797, encodeLengthField(1, cleanSection)),
  );
  const heavyBlob = new Uint8Array(65536);
  heavyBlob.fill(0x61); // 'a'
  const metadataTree = encodeLengthField(
    12,
    concatBytes(
      ...Array.from({ length: 32 }, (_, idx) =>
        encodeLengthField((idx % 7) + 2, heavyBlob),
      ),
    ),
  );
  const largeBrowse = concatBytes(metadataTree, nestedSectionTree);
  assert.ok(largeBrowse.length > 2 * 1024 * 1024, "synthetic browse fixture must exceed 2 MB");

  const decodedLengths = [];
  class CountingTextDecoder extends TextDecoder {
    decode(input, options) {
      if (input) decodedLengths.push(input.byteLength ?? input.length ?? 0);
      return super.decode(input, options);
    }
  }

  let browseOutput;
  const startMs = Date.now();
  vm.runInNewContext(
    script,
    {
      ArrayBuffer,
      TextDecoder: CountingTextDecoder,
      Uint8Array,
      console: { log() {} },
      $surge: { logbook() {} },
      $argument: JSON.stringify({ debug: false }),
      $request: { url: "https://youtubei.googleapis.com/youtubei/v1/browse" },
      $response: { bodyBytes: largeBrowse },
      $done(value) {
        browseOutput = value;
      },
    },
    { filename: "youtube-self.response.js" },
  );
  const elapsedMs = Date.now() - startMs;

  assert.ok(browseOutput && browseOutput.body instanceof Uint8Array);
  assert.equal(
    browseOutput.body.length,
    largeBrowse.length - encodeLengthField(1, sponsoredCardBytes).length,
    "nested sponsored RichItemContent must be stripped cleanly",
  );
  assert.equal(
    decodedLengths.some((len) => len >= 65536),
    false,
    "full-buffer markerHits() and unrelated 64 KB blobs must never be UTF-8 decoded when debug=false",
  );
  assert.equal(
    decodedLengths.length,
    3,
    "each RichItemContent must be UTF-8 decoded at most once",
  );
  assert.ok(elapsedMs < 150, `2 MB browse cleanup took ${elapsedMs}ms (expected < 150ms)`);

  // Verify nested next ad fragment removal still works with subtree marker guard.
  const nextAdLeaf = textFilledItem("googleadservices.com/pagead/aclk", 256);
  const nextCleanLeaf = textFilledItem("related video metadata item", 4096);
  const nextPayload = concatBytes(
    encodeLengthField(7, encodeLengthField(3, nextAdLeaf)),
    encodeLengthField(8, nextCleanLeaf),
  );
  const nextResult = execute(nextPayload, "next");
  assertNoLogs(nextResult, "nested next ad fragment cleanup");
  assert.ok(nextResult.output && nextResult.output.body instanceof Uint8Array);
  assert.deepEqual(
    Array.from(nextResult.output.body),
    Array.from(
      concatBytes(
        encodeLengthField(7, new Uint8Array(0)),
        encodeLengthField(8, nextCleanLeaf),
      ),
    ),
  );
}

console.log("YouTube Self tests passed");
