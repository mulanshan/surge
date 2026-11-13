/*
 * Self-written CamScanner cleaner for Surge.
 *
 * Behavior:
 * - Removes exact ad, splash, popup, promotion, marketing and campaign
 *   containers from selected CamScanner / INTSIG JSON responses.
 * - Keeps purchase, account, OCR, PDF conversion, cloud sync and document
 *   business payloads intact.
 * - Does not forge membership, subscription, trial, quota, receipt or purchase
 *   state.
 * - Does not issue network requests, read cookies, upload data, or include
 *   third-party source code.
 */

const DEFAULTS = {
  cleanAds: true,
  debug: false,
};

const UTF8_DECODER = new TextDecoder();
const config = parseArgument();

function parseArgument() {
  try {
    const parsed = JSON.parse(typeof $argument === "string" ? $argument : "{}");
    if (!isPlainObject(parsed)) return { ...DEFAULTS };
    return {
      cleanAds: typeof parsed.cleanAds === "boolean" ? parsed.cleanAds : DEFAULTS.cleanAds,
      debug: parsed.debug === true,
    };
  } catch {
    return { ...DEFAULTS };
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
  if (body instanceof Uint8Array) return UTF8_DECODER.decode(body);
  if (body instanceof ArrayBuffer) return UTF8_DECODER.decode(new Uint8Array(body));
  return "";
}

function isSuccessfulResponse(response) {
  const status = response && response.status;
  return typeof status !== "number" || (status >= 200 && status < 300);
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

function endpointFromUrl(url) {
  const match = String(url || "").match(/^https?:\/\/[^/]+\/([^?#]+)/);
  return match ? match[1].replace(/^\/+/, "") : "";
}

const SENSITIVE_ENDPOINT_MARKERS = [
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
  "vip",
  "wallet",
];

const PROTECTED_KEY_MARKERS = [
  ...SENSITIVE_ENDPOINT_MARKERS,
  "camera",
  "cloud",
  "doc",
  "document",
  "export",
  "folder",
  "ocr",
  "pdf",
  "scan",
  "share",
  "sync",
  "template",
  "user",
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
  "startpic",
]);

const AD_VALUE_SUBSTRINGS = [
  "advert",
  "interstitial",
  "popup",
  "splash",
  "startpic",
];

const SAFE_KEYS = new Set([
  "address",
  "admin",
  "advanced",
  "advantage",
  "advisor",
  "badge",
  "download",
  "float_btn",
  "float_button",
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
  "floatad",
  "floatingad",
  "funcpopup",
  "interstitial",
  "marketing",
  "popup",
  "popwindow",
  "promotion",
  "recommendad",
  "splash",
  "startpic",
  "startupad",
  "tracking",
]);

const AD_KEY_SUBSTRINGS = [
  "adid",
  "adslot",
  "advert",
  "displayad",
  "display_ad",
  "float_ad",
  "floating_ad",
  "func_popup",
  "funcpopup",
  "interstitial",
  "new_func_popup",
  "popup",
  "popwindow",
  "recommend_ad",
  "recommendad",
  "splash",
  "start_pic",
  "startpic",
  "startup_ad",
];

const SUPPORTED_ENDPOINT_RE =
  /^(?:sync\/(?:get_ad_(?:data|control|cfg)|get_page_cfg(?:_v2)?|get_new_func_popup_cfg)|user\/cs\/operating\/app\/get_startpic)$/i;

function endpointLooksSensitive(endpoint) {
  const lower = String(endpoint || "").toLowerCase();
  return SENSITIVE_ENDPOINT_MARKERS.some((marker) => lower.includes(marker));
}

function keyLooksProtected(key) {
  const lower = String(key || "").toLowerCase();
  if (!lower || SAFE_KEYS.has(lower)) return true;
  const tokens = keyTokens(key);
  return tokens.some((token) => PROTECTED_KEY_MARKERS.includes(token));
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
  if (!lower || keyLooksProtected(key)) return false;
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
  ]
    .map(textOf)
    .join(" ")
    .toLowerCase();
  const tokens = textTokens(joined);
  if (
    tokens.some((token) => AD_VALUE_TOKENS.has(token)) ||
    AD_VALUE_SUBSTRINGS.some((marker) => joined.includes(marker))
  ) return true;

  return [value.name, value.title].some((candidate) =>
    /^(?:ad|ads|advertisement|sponsored|promoted|广告|赞助|推广|营销|开屏|弹窗)$/i.test(textOf(candidate).trim()),
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
    if (keyLooksProtected(key)) continue;
    const child = value[key];

    if (keyLooksLikeAd(key)) {
      const next = neutralValue(child);
      if (JSON.stringify(child) !== JSON.stringify(next)) {
        value[key] = next;
        stats.neutralized += 1;
      }
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
      if (Object.keys(child).length > 0) {
        value[key] = {};
        stats.neutralized += 1;
      }
      continue;
    }

    removeAdLikeFields(child, stats, depth + 1);
  }
}

function normalizeKnownContainers(payload, stats, endpoint) {
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
    "popup_list",
    "popupList",
    "promotion_list",
    "promotionList",
    "splash_list",
    "splashList",
    "startpic_list",
    "startpicList",
    "start_pic_list",
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
    "startpic",
    "start_pic",
  ];

  const lowerEndpoint = endpoint.toLowerCase();
  if (lowerEndpoint.endsWith("get_new_func_popup_cfg")) {
    arrayKeys.push("func_popup_list", "funcPopupList", "new_func_popup_list", "newFuncPopupList");
    objectKeys.push("func_popup", "funcPopup", "new_func_popup", "newFuncPopup", "popwindow");
  }
  if (lowerEndpoint.endsWith("get_startpic") || /get_ad_(?:data|control|cfg)$/.test(lowerEndpoint)) {
    arrayKeys.push("list", "items", "pic_list");
    if (isPlainObject(payload.data) && Object.keys(payload.data).length > 0) {
      payload.data = {};
      stats.neutralized += 1;
    }
  }

  for (const root of roots) {
    for (const key of arrayKeys) {
      if (Array.isArray(root[key]) && root[key].length) {
        root[key] = [];
        stats.neutralized += 1;
      }
    }
    for (const key of objectKeys) {
      if (hasOwn(root, key) && !keyLooksProtected(key)) {
        const next = neutralValue(root[key]);
        if (JSON.stringify(root[key]) !== JSON.stringify(next)) {
          root[key] = next;
          stats.neutralized += 1;
        }
      }
    }
  }
}

function cleanPayload(payload, endpoint) {
  const stats = {
    filtered: 0,
    neutralized: 0,
    skipped: false,
  };

  if (endpointLooksSensitive(endpoint) || !SUPPORTED_ENDPOINT_RE.test(endpoint)) {
    stats.skipped = true;
    return stats;
  }

  normalizeKnownContainers(payload, stats, endpoint);
  removeAdLikeFields(payload, stats, 0);
  return stats;
}

function doneUnchanged(reason) {
  debug(`unchanged: ${reason}`);
  $done({});
}

try {
  const endpoint = endpointFromUrl($request && $request.url);
  if (!config.cleanAds) {
    doneUnchanged("cleanAds disabled");
  } else if (!isSuccessfulResponse($response)) {
    doneUnchanged("non-success status");
  } else if (endpointLooksSensitive(endpoint) || !SUPPORTED_ENDPOINT_RE.test(endpoint)) {
    doneUnchanged(`unsupported or sensitive endpoint ${endpoint || "unknown"}`);
  } else {
    const text = bodyText($response && $response.body);
    if (!text) doneUnchanged("empty body");
    else if (!/^\s*[\[{]/.test(text)) doneUnchanged("non-json body");
    else {
      const payload = JSON.parse(text);
      if (!isPlainObject(payload)) {
        doneUnchanged("non-object JSON");
      } else {
        const stats = cleanPayload(payload, endpoint);
        if (stats.skipped) {
          doneUnchanged(`skipped ${endpoint}`);
        } else {
          debug(`${endpoint} filtered=${stats.filtered} neutralized=${stats.neutralized}`);
          const changed = stats.filtered + stats.neutralized;
          if (!changed) $done({});
          else $done({ body: JSON.stringify(payload) });
        }
      }
    }
  }
} catch (error) {
  logbook(`error: ${error && error.message ? error.message : error}`);
  $done({});
}
