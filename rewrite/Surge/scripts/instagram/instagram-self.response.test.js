const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "instagram-self.response.js"), "utf8");

function run(url, payload, argument = {}) {
  let output;
  const context = {
    ArrayBuffer,
    TextDecoder,
    Uint8Array,
    console: { log() {} },
    $argument: JSON.stringify(argument),
    $request: { url },
    $response: { body: typeof payload === "string" ? payload : JSON.stringify(payload) },
    $done(value) {
      output = value;
    },
  };
  vm.runInNewContext(script, context, { filename: "instagram-self.response.js" });
  return output && typeof output === "object" ? JSON.parse(JSON.stringify(output)) : output;
}

function bodyOf(result) {
  return result && result.body ? JSON.parse(result.body) : null;
}

{
  const result = bodyOf(run("https://www.instagram.com/api/graphql", {
    data: {
      feed: {
        edges: [
          { cursor: "1", node: { id: "organic-1", caption: "normal post" } },
          { cursor: "2", node: { id: "ad-1", is_sponsored: true, title: "Sponsored" } },
        ],
      },
    },
  }));
  assert.equal(result.data.feed.edges.length, 1);
  assert.equal(result.data.feed.edges[0].node.id, "organic-1");
}

{
  const result = bodyOf(run("https://www.instagram.com/api/v1/feed/timeline/", {
    feed_items: [
      { media_or_ad: { media: { id: "organic-2" } } },
      { media_or_ad: { ad: { ad_id: "ad-2" } } },
      { item: { id: "ad-3", ad_metadata: { advertiser_name: "shop" } } },
    ],
  }));
  assert.equal(result.feed_items.length, 1);
  assert.equal(result.feed_items[0].media_or_ad.media.id, "organic-2");
}

{
  const result = bodyOf(run("https://www.instagram.com/graphql/query/", {
    data: {
      clips: [
        { id: "organic-3", additional_data: { badge: "new" }, address: "kept" },
        { id: "ad-4", __typename: "XDTAdReel", advertiser_id: "42" },
        { id: "ad-5", commerciality_status: "paid_partnership" },
      ],
    },
  }));
  assert.equal(result.data.clips.length, 1);
  assert.equal(result.data.clips[0].id, "organic-3");
  assert.equal(result.data.clips[0].additional_data.badge, "new");
  assert.equal(result.data.clips[0].address, "kept");
}

{
  const result = bodyOf(run("https://www.instagram.com/api/v1/discover/topical_explore/", {
    data: {
      ads: [{ id: "ad-6" }, { id: "ad-7" }],
      items: [{ id: "organic-4" }],
    },
  }));
  assert.deepEqual(result.data.ads, []);
  assert.equal(result.data.items[0].id, "organic-4");
}

{
  const result = bodyOf(run("https://www.instagram.com/api/graphql", {
    data: {
      injected_story_units: [
        { id: "organic-injected", reason: "Because you follow this account" },
        { id: "ad-injected-1", is_ad4ad: true },
        { id: "ad-injected-2", ad_tracking_params: { source: "feed" } },
        { id: "unknown-injected", experimental_payload: { kind: "future_unit", value: 1 } },
      ],
      injected_recommendations: [
        { id: "normal-recommendation", context: "Suggested for you" },
      ],
    },
  }));
  assert.deepEqual(result.data.injected_story_units.map((item) => item.id), [
    "organic-injected",
    "unknown-injected",
  ]);
  assert.equal(result.data.injected_story_units[1].experimental_payload.kind, "future_unit");
  assert.equal(result.data.injected_recommendations[0].id, "normal-recommendation");
}

{
  const result = bodyOf(run("https://www.instagram.com/graphql/query/", {
    data: {
      items: [
        { id: "organic-latest-markers" },
        { id: "ad-bloks", is_bloks_ad: "true" },
        { id: "ad-client", ad_client_token: "client-token" },
        { id: "ad-sponsored-info", sponsored_info: { label: "Sponsored" } },
        { id: "ad-type", item_type: "bloks_ad" },
      ],
    },
  }));
  assert.deepEqual(result.data.items.map((item) => item.id), ["organic-latest-markers"]);
}

{
  const result = run("https://www.instagram.com/api/graphql", "for (;;);" + JSON.stringify({
    data: { edges: [{ node: { id: "ad-8", sponsored_label: "Sponsored" } }] },
  }));
  assert.ok(result.body.startsWith("for (;;);"));
  assert.equal(JSON.parse(result.body.slice("for (;;);".length)).data.edges.length, 0);
}

assert.deepEqual(run("https://www.instagram.com/accounts/login/", { ads: [1] }), {});
assert.deepEqual(run("https://www.instagram.com/api/graphql", "not-json"), {});
assert.deepEqual(run("https://www.instagram.com/api/graphql", { data: { items: [{ id: "normal" }] } }), {});
assert.deepEqual(run("https://www.instagram.com/api/graphql", {
  data: { items: [{ id: "industry-news", title: "广告行业观察", headline: "广告技术发展史" }] },
}), {});
assert.deepEqual(run("https://www.instagram.com/api/graphql", {
  data: {
    injected_future_units: [
      { id: "unknown-future-unit", payload: { opaque_key: "keep-me" } },
    ],
  },
}), {});

console.log("Instagram Self tests passed");
