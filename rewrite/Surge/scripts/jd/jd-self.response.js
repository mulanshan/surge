/*
 * Self-written JD cleaner for Surge.
 *
 * Security boundaries:
 * - Only processes selected api.m.jd.com/client.action JSON responses.
 * - Removes strongly identified advertising, splash, popup and marketing nodes.
 * - Preserves account, cart, product, order, payment, refund, address,
 *   logistics, membership and coupon business data.
 * - Does not forge privileges, prices, balances, orders or membership state.
 * - Does not issue network requests, read cookies, upload data, use eval, or
 *   include third-party source code.
 */

const DEFAULTS = {
  debug: false,
  disableDiagnostics: true,
  cleanOrderPromotions: true,
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
  const text = `[JD Self] ${message}`;
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

function bodyText(body) {
  if (typeof body === "string") return body;
  if (body instanceof Uint8Array) return new TextDecoder().decode(body);
  if (body instanceof ArrayBuffer) return new TextDecoder().decode(new Uint8Array(body));
  return "";
}

function functionIdFromUrl(url) {
  const match = String(url || "").match(/[?&]functionId=([^&#]+)/);
  if (!match) return "";
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

function functionIdFromBody(body) {
  const text = bodyText(body);
  if (!text || text.length > 1024 * 1024) return "";

  const formMatch = text.match(/(?:^|&)functionId=([^&]+)/);
  if (formMatch) {
    try {
      return decodeURIComponent(formMatch[1].replace(/\+/g, " "));
    } catch {
      return formMatch[1];
    }
  }

  if (/^\s*\{/.test(text)) {
    try {
      const parsed = JSON.parse(text);
      return typeof parsed.functionId === "string" ? parsed.functionId : "";
    } catch {
      return "";
    }
  }
  return "";
}

function functionIdFromRequest(request) {
  const fromUrl = functionIdFromUrl(request && request.url);
  return fromUrl || functionIdFromBody(request && request.body);
}

function hasOwn(value, key) {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function textOf(value) {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

function nameTokens(value) {
  return String(value || "")
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
}

const PROTECTED_TOKENS = new Set([
  "account",
  "address",
  "aftersale",
  "balance",
  "billing",
  "cart",
  "checkout",
  "coupon",
  "credit",
  "goods",
  "invoice",
  "item",
  "logistics",
  "member",
  "membership",
  "order",
  "pay",
  "payment",
  "plus",
  "price",
  "product",
  "quota",
  "receipt",
  "refund",
  "return",
  "shop",
  "sku",
  "track",
  "user",
  "vip",
  "wallet",
  "ware",
]);

const AD_KEY_TOKENS = new Set([
  "ad",
  "ads",
  "advert",
  "advertise",
  "advertisement",
  "banner",
  "commercial",
  "floating",
  "interstitial",
  "marketing",
  "popup",
  "promotion",
  "splash",
]);

const AD_KEY_EXACT = new Set([
  "adlist",
  "advertiselist",
  "bannerlist",
  "commerciallist",
  "deliverlayer",
  "floatlayer",
  "floatingad",
  "marketingresource",
  "poplayer",
  "popwindow",
  "promotionlist",
  "splashlist",
  "startimage",
  "welcomead",
]);

const AD_TYPE_VALUES = new Set([
  "ad",
  "ads",
  "advert",
  "advertise",
  "advertisement",
  "banner",
  "commercial",
  "floating_ad",
  "interstitial",
  "marketing",
  "popup",
  "promotion",
  "splash",
]);

const AD_TEXT_MARKERS = ["广告", "推广", "营销弹窗", "开屏广告"];

function keyLooksProtected(key) {
  return nameTokens(key).some((token) => PROTECTED_TOKENS.has(token));
}

function keyLooksLikeAd(key) {
  const normalized = String(key || "").replace(/[^a-z0-9]/gi, "").toLowerCase();
  if (!normalized || keyLooksProtected(key)) return false;
  return AD_KEY_EXACT.has(normalized) || nameTokens(key).some((token) => AD_KEY_TOKENS.has(token));
}

function explicitAdFlag(value) {
  if (!isPlainObject(value)) return false;
  const keys = ["isAd", "is_ad", "adFlag", "ad_flag", "advertiseFlag", "advertise_flag"];
  return keys.some((key) => hasOwn(value, key) && (value[key] === true || value[key] === 1 || value[key] === "1"));
}

function objectLooksLikeAd(value) {
  if (!isPlainObject(value)) return false;
  if (explicitAdFlag(value)) return true;

  const typeValues = [
    value.type,
    value.adType,
    value.ad_type,
    value.bizType,
    value.biz_type,
    value.cardType,
    value.card_type,
    value.materialType,
    value.material_type,
    value.template,
  ];
  if (typeValues.some((item) => AD_TYPE_VALUES.has(textOf(item).trim().toLowerCase()))) return true;

  const labels = [value.label, value.name, value.subtitle, value.title]
    .map(textOf)
    .join(" ");
  return AD_TEXT_MARKERS.some((marker) => labels.includes(marker));
}

function neutralValue(value) {
  if (Array.isArray(value)) return [];
  if (isPlainObject(value)) return {};
  if (typeof value === "boolean") return false;
  if (typeof value === "number") return 0;
  return "";
}

function cleanTree(node, stats, depth) {
  if (!isPlainObject(node) || depth > 7) return;

  for (const key of Object.keys(node)) {
    if (keyLooksProtected(key)) continue;

    const value = node[key];
    if (keyLooksLikeAd(key)) {
      node[key] = neutralValue(value);
      stats.neutralized += 1;
      continue;
    }

    if (Array.isArray(value)) {
      const kept = value.filter((item) => !objectLooksLikeAd(item));
      if (kept.length !== value.length) stats.filtered += value.length - kept.length;
      node[key] = kept;
      for (const item of kept) cleanTree(item, stats, depth + 1);
      continue;
    }

    if (isPlainObject(value)) {
      if (objectLooksLikeAd(value)) {
        node[key] = {};
        stats.neutralized += 1;
      } else {
        cleanTree(value, stats, depth + 1);
      }
    }
  }
}

function setPathIfPresent(root, path, value, stats) {
  let target = root;
  for (let index = 0; index < path.length - 1; index += 1) {
    if (!isPlainObject(target) || !isPlainObject(target[path[index]])) return;
    target = target[path[index]];
  }
  const key = path[path.length - 1];
  if (isPlainObject(target) && hasOwn(target, key) && target[key] !== value) {
    target[key] = value;
    stats.diagnostics += 1;
  }
}

function disableDiagnostics(payload, stats) {
  setPathIfPresent(payload, ["data", "JDMessage", "socketmonitor", "isSocketEstablishedAhead"], 0, stats);
  setPathIfPresent(payload, ["data", "JDMessage", "socketmonitor", "isSocketReport"], 0, stats);
  setPathIfPresent(payload, ["data", "JDHttpToolKit", "httpdns", "httpdns"], 0, stats);
}

const RECOMMENDATION_ENDPOINTS = new Set([
  "searchBoxWord",
  "stationPullService",
  "uniformRecommend",
  "uniformRecommend0",
  "uniformRecommend6",
]);

const RECOMMENDATION_KEYS = [
  "floorList",
  "list",
  "recommendList",
  "result",
  "searchBoxWord",
  "stationList",
  "wareList",
  "words",
];

function cleanRecommendationPayload(payload, stats) {
  if (Array.isArray(payload.data)) {
    if (payload.data.length) stats.neutralized += 1;
    payload.data = [];
    return;
  }
  if (!isPlainObject(payload.data)) return;

  for (const key of RECOMMENDATION_KEYS) {
    if (Array.isArray(payload.data[key]) && payload.data[key].length) {
      payload.data[key] = [];
      stats.neutralized += 1;
    }
  }
  cleanTree(payload.data, stats, 0);
}

const ORDER_ENDPOINTS = new Set(["myOrderInfo", "orderTrackBusiness"]);
const CONTENT_ENDPOINTS = new Set([
  "deliverLayer",
  "getTabHomeInfo",
  "myOrderInfo",
  "orderTrackBusiness",
  "personinfoBusiness",
  "start",
  "welcomeHome",
]);

const KNOWN_ENDPOINTS = new Set([
  "basicConfig",
  ...RECOMMENDATION_ENDPOINTS,
  ...CONTENT_ENDPOINTS,
]);

function cleanPayload(payload, functionId) {
  const stats = {
    diagnostics: 0,
    filtered: 0,
    neutralized: 0,
    skipped: false,
  };

  if (functionId === "basicConfig") {
    if (config.disableDiagnostics) disableDiagnostics(payload, stats);
    return stats;
  }

  if (ORDER_ENDPOINTS.has(functionId) && !config.cleanOrderPromotions) {
    stats.skipped = true;
    return stats;
  }

  if (RECOMMENDATION_ENDPOINTS.has(functionId)) {
    cleanRecommendationPayload(payload, stats);
  } else if (CONTENT_ENDPOINTS.has(functionId)) {
    cleanTree(payload, stats, 0);
  } else {
    stats.skipped = true;
  }

  return stats;
}

function doneUnchanged(reason) {
  debug(`unchanged: ${reason}`);
  $done({});
}

try {
  const functionId = functionIdFromRequest($request);
  if (!KNOWN_ENDPOINTS.has(functionId)) {
    doneUnchanged(`unknown ${functionId || "functionId"}`);
  } else {
    const text = bodyText($response.body);
    if (!text) {
      doneUnchanged("empty body");
    } else if (!/^\s*[\[{]/.test(text)) {
      doneUnchanged("non-json body");
    } else {
      const payload = JSON.parse(text);
      if (!isPlainObject(payload)) {
        doneUnchanged("non-object JSON");
      } else {
        const stats = cleanPayload(payload, functionId);
        if (stats.skipped) {
          doneUnchanged(`skipped ${functionId || "unknown"}`);
        } else {
          debug(`${functionId} diagnostics=${stats.diagnostics} filtered=${stats.filtered} neutralized=${stats.neutralized}`);
          if (stats.diagnostics || stats.filtered || stats.neutralized) {
            $done({ body: JSON.stringify(payload) });
          } else {
            doneUnchanged(`no matching fields in ${functionId}`);
          }
        }
      }
    }
  }
} catch (error) {
  logbook(`error: ${error && error.message ? error.message : error}`);
  $done({});
}
