/*
 * Self-written Amap cleaner for Surge.
 *
 * Behavior:
 * - Keeps the cleanup conservative and schema-tolerant.
 * - Removes known ad/message/hotword payload containers from selected Amap
 *   JSON responses only.
 * - Does not issue network requests, read cookies, upload data, or include
 *   third-party source code.
 */

const DEFAULTS = {
  debug: false,
};

const config = parseArgument();

function parseArgument() {
  try {
    return Object.assign({}, DEFAULTS, JSON.parse(typeof $argument === "string" ? $argument : "{}"));
  } catch {
    return DEFAULTS;
  }
}

function logbook(message) {
  const text = `[Amap Self] ${message}`;
  console.log(text);
  try {
    if (typeof $surge !== "undefined" && typeof $surge.logbook === "function") {
      $surge.logbook(text);
    }
  } catch {
    // Diagnostics only.
  }
}

function debug(message) {
  if (config.debug) logbook(message);
}

function endpointFromUrl(url) {
  const match = String(url || "").match(/\/ws\/([^?]+)/);
  return match ? match[1] : "";
}

function bodyText(body) {
  if (typeof body === "string") return body;
  if (body instanceof Uint8Array) return new TextDecoder().decode(body);
  if (body instanceof ArrayBuffer) return new TextDecoder().decode(new Uint8Array(body));
  return "";
}

function hasOwn(value, key) {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function setEmptyArray(target, key, stats) {
  if (target && typeof target === "object" && Array.isArray(target[key]) && target[key].length) {
    stats.arrays += 1;
    target[key] = [];
  }
}

function deleteKey(target, key, stats) {
  if (target && typeof target === "object" && hasOwn(target, key)) {
    stats.deleted += 1;
    delete target[key];
  }
}

function safeObjectValues(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  return Object.values(value);
}

function isPlainObject(value) {
  return value && typeof value === "object" && !Array.isArray(value);
}

function textOf(value) {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

const AD_TOKEN_MARKERS = new Set([
  "ad",
  "ads",
  "banner",
  "dsp",
  "marketing",
  "promotion",
  "splash",
]);

const AD_COMPOUND_MARKERS = new Set([
  "alimama",
  "bizad",
  "feedad",
  "recommendad",
]);

const SAFE_MAIN_PAGE_TYPES = new Set([
  "FrequentLocation",
  "MyOrderCard",
  "TravelCard",
]);

function keyLooksLikeAd(key) {
  const raw = String(key || "");
  const tokens = raw
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
  const compact = tokens.join("");
  return tokens.some((token) => AD_TOKEN_MARKERS.has(token)) || AD_COMPOUND_MARKERS.has(compact);
}

function valueLooksLikeAd(value) {
  if (!isPlainObject(value)) return false;
  const structuredValues = [
    value.dataType,
    value.type,
    value.cardType,
    value.template,
    value.scene,
    value.source,
  ]
    .map(textOf)
    .filter(Boolean);

  for (const candidate of structuredValues) {
    if (keyLooksLikeAd(candidate)) return true;
  }

  const label = `${textOf(value.name)} ${textOf(value.title)}`.trim();
  return /^(?:ad|ads|advertisement|sponsored|promoted|广告|赞助|推广)$/i.test(label);
}

function cleanSplash(payload, stats) {
  setEmptyArray(payload, "ad", stats);
  setEmptyArray(payload, "ads", stats);
  setEmptyArray(payload, "data", stats);
  if (isPlainObject(payload.data)) {
    setEmptyArray(payload.data, "ad", stats);
    setEmptyArray(payload.data, "ads", stats);
    setEmptyArray(payload.data, "splash", stats);
    setEmptyArray(payload.data, "splash_screen", stats);
    deleteKey(payload.data, "ad_info", stats);
    deleteKey(payload.data, "alimama", stats);
  }
}

function cleanMessages(payload, stats) {
  setEmptyArray(payload, "msgs", stats);
  if (isPlainObject(payload.pull3)) setEmptyArray(payload.pull3, "msgs", stats);
  if (isPlainObject(payload.data)) {
    setEmptyArray(payload.data, "msgs", stats);
    setEmptyArray(payload.data, "noticeList", stats);
    setEmptyArray(payload.data, "messageList", stats);
    if (isPlainObject(payload.data.pull3)) setEmptyArray(payload.data.pull3, "msgs", stats);
  }
}

function cleanDspProfile(payload, stats) {
  const roots = [payload, payload && payload.data].filter(isPlainObject);
  const props = [
    "ad",
    "ads",
    "banner",
    "banners",
    "bizad",
    "cardList",
    "dsp",
    "feedAd",
    "marketing",
    "popup",
    "promotion",
    "recommend",
    "scene",
  ];

  for (const root of roots) {
    for (const prop of props) {
      if (Array.isArray(root[prop])) setEmptyArray(root, prop, stats);
      else if (keyLooksLikeAd(prop)) deleteKey(root, prop, stats);
    }
  }
}

function cleanHotword(payload, stats) {
  if (!isPlainObject(payload.data)) return;
  const blocked = ["ad", "ads", "ai_", "ainative", "alimama", "banner", "his_input_tip", "hot_tip", "recommend"];
  for (const key of Object.keys(payload.data)) {
    const lower = key.toLowerCase();
    if (blocked.some((marker) => lower.includes(marker))) {
      payload.data[key] = { status: 1, version: "", value: "" };
      stats.replaced += 1;
    }
  }
}

function filterCardContainer(container, stats) {
  if (!isPlainObject(container)) return;

  for (const key of Object.keys(container)) {
    const value = container[key];
    if (Array.isArray(value)) {
      const before = value.length;
      container[key] = value.filter((item) => !valueLooksLikeAd(item));
      if (container[key].length !== before) stats.filtered += before - container[key].length;
    } else if (isPlainObject(value)) {
      if (keyLooksLikeAd(key) || valueLooksLikeAd(value)) {
        delete container[key];
        stats.deleted += 1;
      }
    }
  }
}

function cleanMainPage(payload, stats) {
  if (!isPlainObject(payload.data)) return;

  deleteKey(payload.data, "feedAd", stats);
  deleteKey(payload.data, "popup", stats);
  deleteKey(payload.data, "recommendAd", stats);
  setEmptyArray(payload.data, "ad", stats);
  setEmptyArray(payload.data, "ads", stats);
  setEmptyArray(payload.data, "banner", stats);
  filterCardContainer(payload.data, stats);

  if (isPlainObject(payload.data.cardList)) {
    const entries = Object.entries(payload.data.cardList);
    const kept = entries.filter(([key, value]) => {
      const type = textOf(value && value.dataType);
      if (SAFE_MAIN_PAGE_TYPES.has(type)) return true;
      return !(keyLooksLikeAd(key) || valueLooksLikeAd(value));
    });
    if (kept.length !== entries.length) {
      payload.data.cardList = Object.fromEntries(kept);
      stats.filtered += entries.length - kept.length;
    }
  }

  for (const child of safeObjectValues(payload.data)) {
    if (isPlainObject(child)) filterCardContainer(child, stats);
  }
}

function cleanPayload(payload, endpoint) {
  const stats = {
    arrays: 0,
    deleted: 0,
    filtered: 0,
    replaced: 0,
  };

  if (endpoint.includes("valueadded/alimama/splash_screen") || endpoint.includes("aos/alimama/splash_screen")) cleanSplash(payload, stats);
  else if (endpoint.includes("msgbox/pull") || endpoint.includes("message/notice/list")) cleanMessages(payload, stats);
  else if (endpoint.includes("shield/dsp/profile/index/nodefaas")) cleanDspProfile(payload, stats);
  else if (endpoint.includes("shield/search/new_hotword")) cleanHotword(payload, stats);
  else if (endpoint.includes("faas/amap-navigation/main-page")) cleanMainPage(payload, stats);

  return stats;
}

function doneUnchanged(reason) {
  debug(`unchanged: ${reason}`);
  $done({});
}

try {
  const endpoint = endpointFromUrl($request.url);
  const text = bodyText($response.body);
  if (!text) doneUnchanged("empty body");
  else {
    const payload = JSON.parse(text);
    const stats = cleanPayload(payload, endpoint);
    debug(`${endpoint} arrays=${stats.arrays} deleted=${stats.deleted} filtered=${stats.filtered} replaced=${stats.replaced}`);
    const changed = stats.arrays + stats.deleted + stats.filtered + stats.replaced;
    if (!changed) $done({});
    else $done({ body: JSON.stringify(payload) });
  }
} catch (error) {
  logbook(`error: ${error && error.message ? error.message : error}`);
  $done({});
}
