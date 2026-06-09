/*
 * Self-written CamScanner cleaner for Surge.
 *
 * Behavior:
 * - Removes ad, splash, popup, promotion, marketing, campaign, notice and
 *   tracking containers from selected CamScanner / INTSIG JSON responses.
 * - Keeps purchase, account, OCR, PDF conversion, cloud sync and document
 *   business payloads intact.
 * - Does not forge membership, subscription, trial, quota, receipt or purchase
 *   state.
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
  const text = `[CamScanner Self] ${message}`;
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

function hasOwn(value, key) {
  return Object.prototype.hasOwnProperty.call(value, key);
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

function endpointFromUrl(url) {
  try {
    const parsed = new URL(url);
    return parsed.pathname.replace(/^\/+/, "");
  } catch {
    const match = String(url || "").match(/^https?:\/\/[^/]+\/([^?]+)/);
    return match ? match[1] : "";
  }
}

const MEMBERSHIP_MARKERS = [
  "account",
  "balance",
  "billing",
  "consume",
  "coupon",
  "credit",
  "license",
  "order",
  "pay",
  "payment",
  "premium",
  "property",
  "purchase",
  "quota",
  "receipt",
  "renew",
  "subscribe",
  "subscription",
  "trial",
  "user",
  "vip",
  "wallet",
];

const AD_VALUE_TOKENS = new Set([
  "ad",
  "ads",
  "advert",
  "advertise",
  "advertisement",
  "banner",
  "campaign",
  "commercial",
  "interstitial",
  "marketing",
  "popup",
  "promotion",
  "splash",
]);

const AD_VALUE_SUBSTRINGS = [
  "advert",
  "interstitial",
  "popup",
  "splash",
  "广告",
  "开屏",
  "弹窗",
  "推广",
  "营销",
];

const SAFE_KEYS = new Set([
  "address",
  "admin",
  "advanced",
  "advantage",
  "advisor",
  "badge",
  "download",
  "metadata",
  "recommend_name",
  "upload",
  "upload_time",
]);

const AD_KEY_TOKENS = new Set([
  "ad",
  "ads",
  "advert",
  "advertise",
  "advertisement",
  "banner",
  "campaign",
  "commercial",
  "displayad",
  "float",
  "funcpopup",
  "interstitial",
  "market",
  "marketing",
  "notice",
  "operate",
  "operation",
  "popup",
  "popwindow",
  "promotion",
  "recommendad",
  "splash",
  "startup",
  "tracking",
]);

const AD_KEY_SUBSTRINGS = [
  "adid",
  "adslot",
  "advert",
  "displayad",
  "display_ad",
  "func_popup",
  "funcpopup",
  "interstitial",
  "new_func_popup",
  "popup",
  "popwindow",
  "recommend_ad",
  "recommendad",
  "splash",
];

function endpointLooksSensitive(endpoint) {
  const lower = String(endpoint || "").toLowerCase();
  return MEMBERSHIP_MARKERS.some((marker) => lower.includes(marker));
}

function keyLooksSensitive(key) {
  const lower = String(key || "").toLowerCase();
  return MEMBERSHIP_MARKERS.some((marker) => lower.includes(marker));
}

function keyTokens(key) {
  return String(key || "")
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
}

function textTokens(text) {
  return String(text || "")
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
}

function keyLooksLikeAd(key) {
  const lower = String(key || "").toLowerCase();
  if (!lower || SAFE_KEYS.has(lower) || keyLooksSensitive(lower)) return false;
  const tokens = keyTokens(key);
  return (
    tokens.some((token) => AD_KEY_TOKENS.has(token)) ||
    AD_KEY_SUBSTRINGS.some((marker) => lower.includes(marker))
  );
}

function valueLooksLikeAd(value) {
  if (!isPlainObject(value)) return false;
  const joined = [
    value.type,
    value.adType,
    value.ad_type,
    value.bizType,
    value.biz_type,
    value.cardType,
    value.card_type,
    value.category,
    value.name,
    value.scene,
    value.source,
    value.template,
    value.title,
  ]
    .map(textOf)
    .join(" ")
    .toLowerCase();
  const tokens = textTokens(joined);
  return (
    tokens.some((token) => AD_VALUE_TOKENS.has(token)) ||
    AD_VALUE_SUBSTRINGS.some((marker) => joined.includes(marker))
  );
}

function neutralValue(value) {
  if (Array.isArray(value)) return [];
  if (isPlainObject(value)) return {};
  if (typeof value === "boolean") return false;
  if (typeof value === "number") return 0;
  if (typeof value === "string") return "";
  return null;
}

function removeAdLikeFields(value, stats, depth) {
  if (!value || depth > 12) return;

  if (Array.isArray(value)) {
    for (let i = value.length - 1; i >= 0; i -= 1) {
      const item = value[i];
      if (valueLooksLikeAd(item)) {
        value.splice(i, 1);
        stats.filtered += 1;
      } else {
        removeAdLikeFields(item, stats, depth + 1);
      }
    }
    return;
  }

  if (!isPlainObject(value)) return;

  for (const key of Object.keys(value)) {
    const child = value[key];

    if (keyLooksLikeAd(key)) {
      value[key] = neutralValue(child);
      stats.neutralized += 1;
      continue;
    }

    if (Array.isArray(child)) {
      const before = child.length;
      value[key] = child.filter((item) => !valueLooksLikeAd(item));
      if (value[key].length !== before) stats.filtered += before - value[key].length;
      removeAdLikeFields(value[key], stats, depth + 1);
      continue;
    }

    if (isPlainObject(child) && valueLooksLikeAd(child)) {
      value[key] = {};
      stats.neutralized += 1;
      continue;
    }

    removeAdLikeFields(child, stats, depth + 1);
  }
}

function normalizeKnownContainers(payload, stats) {
  const roots = [payload];
  if (isPlainObject(payload.data)) roots.push(payload.data);
  if (isPlainObject(payload.result)) roots.push(payload.result);
  if (isPlainObject(payload.body)) roots.push(payload.body);

  const arrayKeys = [
    "ad_list",
    "adList",
    "ads",
    "banner_list",
    "bannerList",
    "campaign_list",
    "campaignList",
    "commercial_list",
    "commercialList",
    "notice_list",
    "noticeList",
    "operation_list",
    "operationList",
    "popup_list",
    "popupList",
    "promotion_list",
    "promotionList",
    "splash_list",
    "splashList",
  ];
  const objectKeys = [
    "ad",
    "advert",
    "advertisement",
    "banner",
    "campaign",
    "commercial",
    "marketing",
    "popup",
    "promotion",
    "splash",
  ];

  for (const root of roots) {
    for (const key of arrayKeys) {
      if (Array.isArray(root[key]) && root[key].length) {
        root[key] = [];
        stats.neutralized += 1;
      }
    }
    for (const key of objectKeys) {
      if (hasOwn(root, key) && !keyLooksSensitive(key)) {
        root[key] = neutralValue(root[key]);
        stats.neutralized += 1;
      }
    }
  }
}

function cleanPayload(payload, endpoint) {
  const stats = {
    filtered: 0,
    neutralized: 0,
  };

  if (endpointLooksSensitive(endpoint)) {
    stats.skipped = true;
    return stats;
  }

  normalizeKnownContainers(payload, stats);
  removeAdLikeFields(payload, stats, 0);
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
  else if (!/^\s*[\[{]/.test(text)) doneUnchanged("non-json body");
  else {
    const payload = JSON.parse(text);
    const stats = cleanPayload(payload, endpoint);
    if (stats.skipped) {
      doneUnchanged(`sensitive endpoint ${endpoint}`);
    } else {
      debug(`${endpoint} filtered=${stats.filtered} neutralized=${stats.neutralized}`);
      $done({ body: JSON.stringify(payload) });
    }
  }
} catch (error) {
  logbook(`error: ${error && error.message ? error.message : error}`);
  $done({});
}
